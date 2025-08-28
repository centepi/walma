import os
import re
import json
import google.generativeai as genai
from config import settings
from . import utils
from . import response_validator

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


def verify_and_mark_question(checker_model, question_object):
    """
    Acts as an AI examiner to verify a question's correctness and assign marks.
    NOTE: Per-attempt rejections are logged at DEBUG to avoid console noise.
    """
    question_id = question_object.get("question_number", "N/A")
    logger.info("Examiner: verifying '%s'", question_id)

    # Convert the question object to a clean JSON string for the AI to review
    question_json_string = json.dumps(question_object, indent=2)

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

    if checker_feedback.get("is_correct"):
        marks = checker_feedback.get("marks")
        logger.info("Examiner: ✅ verified '%s' (marks=%s)", question_id, marks)
    else:
        reason = checker_feedback.get("feedback") or "no reason provided"
        # Demoted to DEBUG to avoid mid-attempt noise
        logger.debug("Examiner: rejected '%s' — %s", question_id, utils.truncate(reason, 200))

    return checker_feedback
