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


def create_question(gemini_model, full_reference_text, target_part_ref, correction_feedback=None):
    """
    Creates a new, self-contained question inspired by a specific part of a reference question.
    If correction_feedback is provided, it attempts to fix a previously failed generation.
    """
    target_part_id = target_part_ref.get("original_question", {}).get("id", "N/A")
    target_part_content = target_part_ref.get("original_question", {}).get("content", "")
    target_part_answer = target_part_ref.get("original_answer", {}).get("content", "")

    correction_prompt_section = ""
    if correction_feedback:
        logger.info(f"Regenerating for part '{target_part_id}' with checker feedback.")
        logger.debug("Full correction feedback for %s: %s", target_part_id, correction_feedback)
        correction_prompt_section = f"""
    --- CORRECTION INSTRUCTIONS ---
    Your previous attempt was REJECTED for the following reason: "{correction_feedback}"
    You MUST generate the question again and fix this specific error while still following all original instructions.
    """
    else:
        logger.info(f"Generating new question inspired by part '{target_part_id}'.")

    prompt = f"""
    You are an expert A-level Mathematics content creator. Your task is to create a NEW, ORIGINAL, and SELF-CONTAINED A-level question.
    {correction_prompt_section}
    --- CONTEXT: THE FULL ORIGINAL QUESTION ---
    {full_reference_text}

    --- INSPIRATION: THE TARGET PART ---
    This is the specific part of the original question you should use as inspiration for the skill to be tested.
    - Reference Part Content: "{target_part_content}"
    - Reference Part Solution: "{target_part_answer}"

    --- YOUR TASK ---
    Create a single, new, self-contained question that tests the same mathematical skill as the target part above, following the specified OUTPUT FORMAT.

    **CRITICAL INSTRUCTIONS**:
    1.  **Self-Contained**: Your new question MUST have its own setup (a "question_stem") and a single question part.
    2.  **Invent New Values**: You MUST invent new functions, numbers, and scenarios.
    3.  **GUARANTEE A CLEAN ANSWER**: The values you invent MUST lead to a clean, elegant solution (e.g., integers, simple fractions, or simple surds).
    4.  **Contextual Visuals Only**: The 'visual_data' you generate must only contain information that helps the user understand the question. It must NEVER contain the answer itself. For example, if the question is 'Find the turning point', do NOT include 'turning_points' in the data. If the question is 'Calculate the shaded area', you SHOULD include the 'shaded_regions' data.
    5.  **Include Visuals if Appropriate**: If the skill is inherently visual, generate the 'visual_data' object.
    6.  **Calculator Use**: Determine if a calculator is required and set the 'calculator_required' field.
    7.  **NO DRAWING QUESTIONS**: The "question_text" you create must NEVER ask the student to "sketch", "draw", or "plot" a graph. If the reference question asks the student to draw, you must adapt the question to test the same knowledge with a text-based answer. For example, instead of "Sketch the graph of y = x^2", you could ask, "Describe the key features of the graph y = x^2, such as its shape, vertex, and any intercepts."

    **OUTPUT FORMAT**:
    Your output MUST be a single, valid JSON object with the following structure:
    {{
      "question_stem": "A concise introduction/setup for your new question.",
      "parts": [
        {{
          "part_label": "a",
          "question_text": "The single task for the user to perform.",
          "solution_text": "The detailed, step-by-step solution to your new question."
        }}
      ],
      "calculator_required": true,
      "visual_data": {{...}} // Omit this key entirely if no visual is needed
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
                "visual_features": {{ "type": "parabola", "x_intercepts": null, "y_intercept": 7, "turning_points": [{{ "x": 2, "y": 3 }}], "axes_range": {{ "x_min": -1, "x_max": 5, "y_min": 0, "y_max": 10 }} }}
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
    - All backslashes `\\` within JSON string values MUST be escaped (e.g., `"\\\\(x^2\\\\)"`).

    **FINAL CHECK**: Before responding, ensure the question has a clean solution and the JSON is valid. Output ONLY the JSON object.
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
