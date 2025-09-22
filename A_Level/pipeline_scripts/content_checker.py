import os
import re
import json
import google.generativeai as genai
from config import settings
from . import utils
from . import response_validator

# Optional CAS (SymPy) validator
try:
    from . import cas_validator
except Exception:
    cas_validator = None  # CAS is optional for MVP

logger = utils.setup_logger(__name__)

# Read CAS mode from settings (safe default = "off")
# Supported: "off" (skip), "warn" (log + annotate feedback), "strict" (fail if CAS fails)
CAS_MODE = (getattr(settings, "CAS_VALIDATION_MODE", "off") or "off").strip().lower()
CAS_MODE = CAS_MODE if CAS_MODE in {"off", "warn", "strict"} else "off"


def initialize_gemini_client():
    """Initializes the Gemini client for the checker module."""
    try:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        logger.info("Content Checker's Gemini client initialized successfully.")
        return genai.GenerativeModel(settings.GEMINI_MODEL_NAME)
    except Exception as e:
        logger.error(f"Failed to initialize Content Checker's Gemini client: {e}")
        return None


def _extract_answer_spec(question_object: dict) -> dict | None:
    """
    Pull an answer_spec if present.
    Priority:
      1) top-level question_object["answer_spec"]
      2) first part's ["answer_spec"] if present
    We do NOT try to infer from 'final_answer' for MVP safety.
    """
    if not isinstance(question_object, dict):
        return None
    spec = question_object.get("answer_spec")
    if isinstance(spec, dict):
        return spec
    parts = question_object.get("parts")
    if isinstance(parts, list) and parts:
        pspec = parts[0].get("answer_spec") if isinstance(parts[0], dict) else None
        if isinstance(pspec, dict):
            return pspec
    return None


def _apply_cas_validation_if_enabled(question_object: dict, ai_feedback: dict) -> dict:
    """
    Optionally run CAS validation and merge its outcome with the AI examiner feedback.

    Rules:
      - CAS_MODE == "off": return ai_feedback unchanged.
      - If no cas_validator or no answer_spec: log and return ai_feedback unchanged.
      - If CAS passes: no change.
      - If CAS fails:
          * warn  -> append CAS note to feedback, keep AI decision
          * strict-> force is_correct=False, marks=0, annotate feedback
    """
    if CAS_MODE == "off":
        return ai_feedback

    if cas_validator is None:
        logger.info("CAS: validator not available (module import failed). Skipping CAS.")
        return ai_feedback

    spec = _extract_answer_spec(question_object)
    if not spec:
        logger.info("CAS: no answer_spec present on question. Skipping CAS.")
        return ai_feedback

    try:
        ok, report = cas_validator.validate({"answer_spec": spec})
    except Exception as e:
        logger.error("CAS: unexpected error during validation — %s", e)
        return ai_feedback

    if ok:
        logger.info("CAS: ✅ validation passed (kind=%s).", report.get("kind"))
        return ai_feedback

    # CAS failed — decide by mode
    details = report.get("details") or report.get("reason") or report
    cas_msg = f"CAS check failed ({report.get('kind','unknown')}): {details}"

    if CAS_MODE == "warn":
        # Keep AI verdict but annotate feedback
        fb = (ai_feedback.get("feedback") or "").strip()
        if fb and not fb.endswith("."):
            fb += "."
        ai_feedback["feedback"] = (fb + f" [CAS WARN] {utils.truncate(str(cas_msg), 300)}").strip()
        logger.warning("CAS: ❗ warn-only failure — %s", cas_msg)
        return ai_feedback

    # strict
    logger.warning("CAS: ❌ strict failure — forcing rejection. %s", cas_msg)
    return {
        "is_correct": False,
        "feedback": f"{utils.truncate(str(cas_msg), 500)}",
        "marks": 0
    }


def verify_and_mark_question(checker_model, question_object):
    """
    Acts as an AI examiner to verify a question's correctness and assign marks.
    Optionally augments with CAS validation based on settings.CAS_VALIDATION_MODE.
    NOTE: Per-attempt rejections are logged at DEBUG to avoid console noise.
    """
    question_id = question_object.get("question_number", "N/A")
    logger.info("Examiner: verifying '%s' (CAS_MODE=%s)", question_id, CAS_MODE)

    # Convert the question object to a clean JSON string for the AI to review
    try:
        question_json_string = json.dumps(question_object, indent=2, ensure_ascii=False)
    except TypeError:
        # Fallback: remove non-serializable fields
        safe_obj = json.loads(json.dumps(question_object, default=str))
        question_json_string = json.dumps(safe_obj, indent=2, ensure_ascii=False)

    prompt = f"""
    You are a meticulous and strict A-level Mathematics examiner. Your task is to review the following auto-generated question and its solution.

    --- QUESTION TO REVIEW ---
    ```json
    {question_json_string}
    ```

    --- YOUR TASKS ---
    1.  **Verify Correctness**: Carefully check the 'solution_text'. Is the mathematics sound? Are there any logical errors? Does the solution correctly answer the 'question_text'?
    2.  **Assign Marks**: If and only if the question is 100% correct, assign a fair mark based on the complexity and number of steps required.

    --- OUTPUT FORMAT ---
    You MUST respond with a single, valid JSON object in the following format. Do NOT add any other text or explanation.

    **If the question is FLAWED, use this format:**
    ```json
    {{
      "is_correct": false,
      "feedback": "A brief, clear explanation of the mistake. For example: 'In the solution, the derivative of 2x^3 is stated as 6x, but it should be 6x^2. This makes the rest of the solution incorrect.'",
      "marks": 0
    }}
    ```

    **If the question is PERFECT, use this format:**
    ```json
    {{
      "is_correct": true,
      "feedback": "OK",
      "marks": <an integer from 1 to 8 representing the fair mark>
    }}
    ```
    """

    try:
        chat = checker_model.start_chat()
        response = chat.send_message(prompt)
        raw_text_response = response.text
    except Exception as e:
        logger.error("Examiner: error calling model for '%s' — %s", question_id, e)
        return None

    # Parse & validate the examiner's response
    checker_feedback = response_validator.validate_and_correct_response(
        chat, checker_model, raw_text_response
    )

    if not checker_feedback:
        logger.error("Examiner: failed to parse feedback for '%s'.", question_id)
        return None

    # Optional CAS pass
    checker_feedback = _apply_cas_validation_if_enabled(question_object, checker_feedback)

    if checker_feedback.get("is_correct"):
        marks = checker_feedback.get("marks")
        logger.info("Examiner: ✅ verified '%s' (marks=%s)", question_id, marks)
    else:
        reason = checker_feedback.get("feedback") or "no reason provided"
        # Demoted to DEBUG to avoid mid-attempt noise
        logger.debug("Examiner: rejected '%s' — %s", question_id, utils.truncate(reason, 200))

    return checker_feedback