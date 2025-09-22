# content_creator.py
import os
import re
import json
import google.generativeai as genai
from config import settings
from . import utils
from . import graph_utils
from . import response_validator

logger = utils.setup_logger(__name__)


def initialize_gemini_client():
    """Initializes the Gemini client with the API key."""
    try:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        logger.info("Content Creator's Gemini client initialized successfully.")
        return genai.GenerativeModel(settings.GEMINI_MODEL_NAME)
    except Exception as e:
        logger.error(f"Failed to initialize Content Creator's Gemini client: {e}")
        return None


def _normalize_generated_object(obj: dict) -> dict:
    """
    Post-process guard rails:
      - ensure parts is a 1-length list with a,b,c label defaulting to 'a'
      - trim strings
      - drop empty visual_data dicts
    """
    if not isinstance(obj, dict):
        return obj or {}

    # Trim top-level strings
    for key in ("question_stem",):
        if key in obj and isinstance(obj[key], str):
            obj[key] = obj[key].strip()

    # Parts normalization
    parts = obj.get("parts") or []
    if isinstance(parts, dict):
        parts = [parts]
    if not parts:
        parts = [{
            "part_label": "a",
            "question_text": "",
            "solution_text": ""
        }]
    # Keep only the first part for MVP and ensure required keys
    part = parts[0] or {}
    part.setdefault("part_label", "a")
    part["part_label"] = str(part["part_label"]).strip() or "a"
    for k in ("question_text", "solution_text", "final_answer"):
        if k in part and isinstance(part[k], str):
            part[k] = part[k].strip()
    obj["parts"] = [part]

    # calculator_required default
    if "calculator_required" not in obj:
        obj["calculator_required"] = False

    # Clean empty visual_data
    if isinstance(obj.get("visual_data"), dict) and not obj["visual_data"]:
        obj.pop("visual_data", None)

    return obj


def create_question(gemini_model, full_reference_text, target_part_ref, correction_feedback=None):
    """
    Creates a new, self-contained question inspired by a specific part of a reference question.
    If correction_feedback is provided, it attempts to fix a previously failed generation.

    NOTE: We ask the model to include a concise 'final_answer' inside the first part
    so downstream CAS validation can run quickly and reliably.
    """
    target_part_id = target_part_ref.get("original_question", {}).get("id", "N/A")
    target_part_content = target_part_ref.get("original_question", {}).get("content", "")
    target_part_answer = target_part_ref.get("original_answer", {}).get("content", "")

    correction_prompt_section = ""
    if correction_feedback:
        logger.info(f"Regenerating for part '{target_part_id}' with checker/CAS feedback.")
        logger.debug("Full correction feedback for %s: %s", target_part_id, correction_feedback)
        correction_prompt_section = f"""
    --- CORRECTION INSTRUCTIONS ---
    Your previous attempt was REJECTED for the following reason: "{correction_feedback}"
    You MUST generate the question again and fix this specific error while still following all original instructions.
    """

    else:
        logger.info(f"Generating new question inspired by part '{target_part_id}'.")

    # Allow a configurable syllabus/context header
    context_header = getattr(settings, "GENERATION_CONTEXT_PROMPT", "").strip()

    prompt = f"""
    {context_header}

    You are an expert A-level Mathematics content creator. Your task is to create a NEW, ORIGINAL, and SELF-CONTAINED A-level question.
    {correction_prompt_section}
    --- CONTEXT: THE FULL ORIGINAL QUESTION (for skill + style only; do NOT copy) ---
    {full_reference_text}

    --- INSPIRATION: THE TARGET PART ---
    This is the specific part of the original question you should use as inspiration for the skill to be tested.
    - Reference Part Content: "{target_part_content}"
    - Reference Part Solution (if available): "{target_part_answer}"

    --- YOUR TASK ---
    Create ONE self-contained question that tests the same mathematical skill as the target part above, following the specified OUTPUT FORMAT.

    **CRITICAL INSTRUCTIONS**:
    1.  **Self-Contained**: Provide a clear "question_stem" and exactly ONE part in "parts".
    2.  **Invent New Values**: Use fresh numbers/functions/scenarios. Do not copy text.
    3.  **GUARANTEE A CLEAN ANSWER**: Choose values that lead to a neat final result (integers, simple fractions, or simple surds).
    4.  **Contextual Visuals Only**: Any 'visual_data' must aid understanding and must NEVER encode or reveal the answer (e.g., do NOT include turning_points if the task is to find the turning point).
    5.  **Include Visuals if Appropriate**: If the skill is inherently visual, include a 'visual_data' object as described below.
    6.  **Calculator Use**: Set 'calculator_required' appropriately.
    7.  **NO DRAWING REQUESTS**: Do not ask the user to "sketch/draw/plot". Convert such tasks into textual reasoning requirements.
    8.  **FINAL ANSWER FIELD**: Inside the single part object, include a 'final_answer' string that is the fully simplified final numeric value or algebraic expression required by the question (e.g., "5/2", "3√2", "(x-2)(x+3)", "2x+1"). This must be short and CAS-friendly (no prose).

    **OUTPUT FORMAT**:
    Your output MUST be a single, valid JSON object with the following structure:
    {{
      "question_stem": "A concise introduction/setup for your new question.",
      "parts": [
        {{
          "part_label": "a",
          "question_text": "The single task for the user to perform.",
          "solution_text": "The detailed, step-by-step solution to your new question.",
          "final_answer": "A SHORT, simplified final numeric value or algebraic expression only."
        }}
      ],
      "calculator_required": true,
      "visual_data": {{...}}  // Omit this key entirely if no visual is needed
    }}

    **'visual_data' structure (if needed)**:
    The 'visual_data' object must contain a 'graphs' array. You can also add OPTIONAL arrays for 'labeled_points' and 'shaded_regions'.
    Example of a rich 'visual_data' object:
    {{
        "graphs": [
            {{
                "id": "g1",
                "label": "y = f(x)",
                "explicit_function": "A Python-compatible expression like 'x**2 - 4*x + 7'",
                "visual_features": {{
                    "type": "parabola",
                    "x_intercepts": null,
                    "y_intercept": 7,
                    "turning_points": [{{ "x": 2, "y": 3 }}],
                    "axes_range": {{ "x_min": -1, "x_max": 5, "y_min": 0, "y_max": 10 }}
                }}
            }}
        ],
        "labeled_points": [
            {{ "label": "A", "x": 1.0, "y": 4.0 }}
        ],
        "shaded_regions": [
            {{
                "upper_bound_id": "g1",
                "lower_bound_id": "y=0",
                "x_start": 1.0,
                "x_end": 4.0
            }}
        ]
    }}

    **JSON TECHNICAL RULES**:
    - All backslashes '\\\\' within JSON string values MUST be escaped.
    - Output ONLY the JSON object. No extra commentary.

    **FINAL CHECK**: Ensure the question has a clean solution; 'final_answer' is short & simplified; and the JSON is valid.
    """

    try:
        chat = gemini_model.start_chat()
        response = chat.send_message(prompt)
        raw_text_response = response.text
    except Exception as e:
        logger.error(f"An error occurred during question generation for seed '{target_part_id}': {e}")
        return None

    content_object = response_validator.validate_and_correct_response(
        chat, gemini_model, raw_text_response
    )

    if not content_object:
        logger.error(f"Failed to generate or validate content for seed '{target_part_id}'.")
        return None

    # Normalize/guard
    content_object = _normalize_generated_object(content_object)

    # After successful validation, process any visual data using the master function
    visual_data = content_object.get("visual_data")
    if visual_data:
        logger.debug("Visual data present for seed '%s'. Processing…", target_part_id)
        graph_utils.process_and_sample_visual_data(visual_data)
    else:
        logger.debug("No visual data generated for seed '%s'.", target_part_id)

    return content_object


def request_ai_correction(chat_session, error_message, original_text, context_text=None):
    """Asks the AI to correct its last response based on a validation error."""
    short_err = utils.truncate(str(error_message), limit=140)
    logger.debug("Requesting AI self-correction. Reason: %s", short_err)

    prompt = f"""
    Your last response could not be parsed and failed with the following error: '{error_message}'.

    Here is the full, problematic response you sent:
    --- FAULTY RESPONSE ---
    {original_text}
    --- END FAULTY RESPONSE ---

    Please provide the same content again, but ensure it is a single, perfectly valid JSON object with all backslashes and special characters correctly escaped for JSON.
    Do not include any explanation or apologies, only the corrected JSON object.
    """
    try:
        response = chat_session.send_message(prompt)
        logger.debug("Self-correction response received (first 200 chars): %s", (response.text or "")[:200])
        return response.text
    except Exception as e:
        logger.error(f"An error occurred during AI self-correction request: {e}")
        return None