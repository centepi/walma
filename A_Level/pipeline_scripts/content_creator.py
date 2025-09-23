# pipeline_scripts/content_creator.py
import os
import re
import json
import google.generativeai as genai

from config import settings
from . import utils
from . import graph_utils
from . import response_validator
from .prompts_presets import build_creator_prompt
from .constants import CASPolicy

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


# -------------------------
# Output normalization
# -------------------------
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


# -------------------------
# Lightweight answer_spec synthesis (optional)
# -------------------------
_DERIVATIVE_CUES = re.compile(
    r"(differentiate|dy/dx|f'\(x\)|derivative\s+of|find\s+f'\(x\))",
    re.IGNORECASE,
)
_FUNC_EQ_PAT = re.compile(
    r"(?:^|[\s,:;])(?:y\s*=\s*|[a-zA-Z]\s*\(\s*x\s*\)\s*=\s*)(?P<expr>[^;.\n\r]+)",
    re.IGNORECASE,
)

def _pyexpr(s: str) -> str:
    """Normalize common math text to Python/SymPy-ish."""
    if not isinstance(s, str):
        return s
    t = s.strip()
    t = t.replace("^", "**")
    t = t.replace("×", "*").replace("·", "*")
    t = t.replace("−", "-").replace("—", "-").replace("–", "-")
    t = t.replace("ln", "log")
    return t

def _maybe_build_derivative_spec(stem: str, qtext: str, final_answer: str) -> dict | None:
    """
    If the question clearly asks for a general derivative (not 'at x=a'),
    and we can spot y=f(x) / f(x)=..., build:
        {"kind":"derivative","of":"<expr>","result":"<final_answer>","order":1}
    """
    if not final_answer or not isinstance(final_answer, str):
        return None

    text = f"{stem}\n{qtext}"
    if not _DERIVATIVE_CUES.search(text):
        return None

    # Heuristic: avoid 'at x = a' pure numeric gradient questions
    if re.search(r"\bat\s*x\s*=\s*[-+]?\d+(\.\d+)?\b", text, re.IGNORECASE):
        return None

    m = _FUNC_EQ_PAT.search(text)
    if not m:
        return None

    of_expr = _pyexpr(m.group("expr"))
    res_expr = _pyexpr(final_answer)

    # Very rough guard: result should look like an expression in x (not just a number)
    if re.fullmatch(r"[-+]?\d+(\.\d+)?", res_expr):
        return None

    return {
        "kind": "derivative",
        "of": of_expr,
        "result": res_expr,
        "order": 1,
        "variables": ["x"],
    }


def _synthesize_answer_spec_if_missing(content_object: dict) -> dict:
    """
    If CAS is not OFF and answer_spec is missing, attempt a tiny set of heuristics
    to provide one. Currently supports general-derivative cases only.
    """
    try:
        if (settings.CAS_POLICY or CASPolicy.OFF).lower().strip() == CASPolicy.OFF:
            return content_object

        if isinstance(content_object.get("answer_spec"), dict):
            return content_object  # already present

        part = (content_object.get("parts") or [{}])[0]
        stem = content_object.get("question_stem", "")
        qtext = part.get("question_text", "")
        final_ans = part.get("final_answer", "")

        spec = _maybe_build_derivative_spec(stem, qtext, final_ans)
        if spec:
            content_object["answer_spec"] = spec
            logger.debug("CAS: synthesized answer_spec=%s", spec)
        return content_object
    except Exception as e:
        logger.debug("CAS: synthesize skipped due to error: %s", e)
        return content_object


# -------------------------
# Main API
# -------------------------
def create_question(
    gemini_model,
    full_reference_text,
    target_part_ref,
    correction_feedback=None,
    keep_structure: bool = False,
):
    """
    Creates a new, self-contained question inspired by a specific part of a reference question.
    If correction_feedback is provided, it attempts to fix a previously failed generation.

    NOTE: We ask the model to include a concise 'final_answer' inside the first part
    so downstream CAS validation can run quickly and reliably. If CAS is enabled and
    the model omits 'answer_spec', we try a tiny heuristic to synthesize one for
    common derivative-style items.
    """
    target_part_id = target_part_ref.get("original_question", {}).get("id", "N/A")
    target_part_content = target_part_ref.get("original_question", {}).get("content", "")
    target_part_answer = target_part_ref.get("original_answer", {}).get("content", "")

    if correction_feedback:
        logger.info(f"Regenerating for part '{target_part_id}' with checker/CAS feedback.")
        logger.debug("Full correction feedback for %s: %s", target_part_id, correction_feedback)
        correction_prompt_section = (
            f"\n--- CORRECTION INSTRUCTIONS ---\n"
            f'Your previous attempt was REJECTED for the following reason: "{correction_feedback}"\n'
            f"You MUST generate the question again and fix this specific error while still following all original instructions.\n"
        )
    else:
        logger.info(f"Generating new question inspired by part '{target_part_id}'.")
        correction_prompt_section = ""

    # Build the prompt via shared presets (keeps behavior consistent across modules)
    prompt = build_creator_prompt(
        context_header=getattr(settings, "GENERATION_CONTEXT_PROMPT", "").strip(),
        full_reference_text=full_reference_text,
        target_part_content=target_part_content,
        target_part_answer=target_part_answer,
        correction_prompt_section=correction_prompt_section,
        keep_structure=bool(keep_structure),
    )

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

    # If CAS is enabled but spec missing, attempt minimal synthesis for common cases
    content_object = _synthesize_answer_spec_if_missing(content_object)

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