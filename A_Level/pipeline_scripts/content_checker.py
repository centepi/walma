# pipeline_scripts/content_checker.py
import json
import google.generativeai as genai

from config import settings
from . import utils
from . import response_validator
from .prompts_presets import build_examiner_prompt
from .constants import CASPolicy

# CAS wrapper (optional but preferred)
try:
    from .checks_cas import run_cas_check
except Exception:  # pragma: no cover
    run_cas_check = None  # If missing, we gracefully skip CAS.

logger = utils.setup_logger(__name__)


def initialize_gemini_client():
    """Initializes the Gemini client for the checker module."""
    try:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        logger.info("Content Checker's Gemini client initialized successfully.")
        return genai.GenerativeModel(settings.GEMINI_MODEL_NAME)
    except Exception as e:
        logger.error(f"Failed to initialize Content Checker's Gemini client: {e}")
        return None


def _safe_dumps(obj) -> str:
    """Robust JSON dump that won’t crash on non-serializable fields."""
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except TypeError:
        safe_obj = json.loads(json.dumps(obj, default=str))
        return json.dumps(safe_obj, indent=2, ensure_ascii=False)


def _merge_cas_feedback(
    ai_feedback: dict,
    cas_ok: bool,
    cas_report: dict,
    policy: str,
) -> dict:
    """
    - OFF: return AI feedback unchanged.
    - PREFER: if CAS fails, append a warning to feedback (do not change is_correct/marks).
    - REQUIRE: if CAS fails, force is_correct=False, marks=0, and explain why.
    """
    policy = (policy or CASPolicy.OFF).lower().strip()
    if policy == CASPolicy.OFF or run_cas_check is None:
        return ai_feedback

    if cas_ok:
        return ai_feedback

    # CAS failed — construct a concise message
    kind = cas_report.get("kind", "unknown")
    details = cas_report.get("details") or cas_report.get("reason") or cas_report
    cas_msg = f"CAS check failed ({kind}): {utils.truncate(str(details), 300)}"

    if policy == CASPolicy.PREFER:
        fb = (ai_feedback.get("feedback") or "").strip()
        if fb and not fb.endswith("."):
            fb += "."
        ai_feedback["feedback"] = (fb + f" [CAS WARN] {cas_msg}").strip()
        logger.warning("CAS(PREFER): %s", cas_msg)
        return ai_feedback

    # REQUIRE -> hard fail
    logger.warning("CAS(REQUIRE): forcing rejection. %s", cas_msg)
    return {
        "is_correct": False,
        "feedback": utils.truncate(cas_msg, 500),
        "marks": 0,
    }


def verify_and_mark_question(checker_model, question_object):
    """
    Acts as an AI examiner to verify a question's correctness and assign marks.
    Optionally augments with CAS validation based on settings.CAS_POLICY
    (off | prefer | require). Per-attempt rejections are logged at DEBUG to
    avoid console noise.
    """
    policy = (getattr(settings, "CAS_POLICY", CASPolicy.OFF) or CASPolicy.OFF).lower().strip()
    question_id = (question_object or {}).get("question_number", "N/A")
    logger.info("Examiner: verifying '%s' (CAS_POLICY=%s)", question_id, policy)

    # Prepare the prompt
    question_json_string = _safe_dumps(question_object)
    prompt = build_examiner_prompt(question_json_string=question_json_string, cas_policy=policy)

    # Call the model
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

    # Run CAS (if configured and available)
    cas_ok, cas_report = True, {"kind": "off", "details": "CAS disabled or unavailable"}
    if run_cas_check is not None and policy in (CASPolicy.PREFER, CASPolicy.REQUIRE):
        try:
            cas_ok, cas_report = run_cas_check(question_object, policy=policy)
            tag = "✅" if cas_ok else "❌"
            logger.info("CAS: %s %s", tag, cas_report.get("kind", "unknown"))
        except Exception as e:  # pragma: no cover
            # If CAS itself errors, treat as pass unless REQUIRE (handled in _merge_cas_feedback)
            cas_ok, cas_report = True, {"kind": "error", "details": f"CAS crashed: {e}"}
            logger.error("CAS: unexpected error — %s", e)

    # Merge CAS decision with AI feedback (policy aware)
    checker_feedback = _merge_cas_feedback(checker_feedback, cas_ok, cas_report, policy)

    # Log final decision
    if checker_feedback.get("is_correct"):
        marks = checker_feedback.get("marks")
        logger.info("Examiner: ✅ verified '%s' (marks=%s)", question_id, marks)
    else:
        reason = checker_feedback.get("feedback") or "no reason provided"
        logger.debug("Examiner: rejected '%s' — %s", question_id, utils.truncate(reason, 200))

    return checker_feedback