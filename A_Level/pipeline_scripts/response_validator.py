import re
import json
from . import utils

logger = utils.setup_logger(__name__)


def _parse_and_repair(raw_text: str):
    """
    Takes a raw string from an AI, attempts to repair common errors,
    and parses it into a JSON object.
    """
    if not raw_text:
        logger.warning("Validator: empty response.")
        return None

    # Raw payloads can be huge: keep in file log only.
    logger.debug("Validator: attempting parse. Raw (first 500 chars): %s", raw_text[:500])

    try:
        # Step 1: Find the JSON block, even if it's wrapped in markdown.
        json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw_text)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match_plain = re.search(r'\{[\s\S]*\}', raw_text)
            if not json_match_plain:
                logger.warning("Validator: no JSON object found in AI response.")
                logger.debug("Validator: full raw (first 2000 chars): %s", raw_text[:2000])
                return None
            json_str = json_match_plain.group(0)

        # Step 2: Clean up common formatting issues.
        control_char_re = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
        json_str = control_char_re.sub('', json_str)
        json_str = (json_str
                    .replace('\u00a0', ' ')
                    .replace('“', '"').replace('”', '"')
                    .replace("‘", "'").replace("’", "'"))

        # Step 3: Remove trailing commas before closing braces/brackets.
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

        # Step 4: Attempt to parse.
        parsed_data = json.loads(json_str)

        logger.debug("Validator: JSON parsed successfully.")
        return parsed_data

    except Exception as e:
        # Console gets a short, high-signal message; details go to file DEBUG.
        short = utils.truncate(str(e), limit=160)
        logger.warning("Validator: parse failed after repair attempts — %s", short)
        logger.debug("Validator: original raw (first 2000 chars): %s", raw_text[:2000])
        return None


def validate_and_correct_response(
    chat_session,
    gemini_model,
    initial_response_text: str
):
    """
    The main 'Quality Inspector' function. Validates and optionally corrects the model response.
    """
    current_response_text = initial_response_text

    # Import the correction function here to avoid circular dependency issues
    from . import content_creator
    correction_func = content_creator.request_ai_correction

    for attempt in range(2):
        logger.debug("Validator: validation attempt %d", attempt + 1)

        parsed_data = _parse_and_repair(current_response_text)
        if parsed_data:
            logger.info("Validator: validation successful.")
            return parsed_data

        logger.warning("Validator: validation failed on attempt %d.", attempt + 1)

        if attempt == 0:
            logger.debug("Validator: attempting AI self-correction…")
            # Generic but effective error message for correction prompt
            error_message = "The previous response was not valid JSON."
            current_response_text = correction_func(chat_session, error_message, current_response_text)

            if not current_response_text:
                logger.error("Validator: AI self-correction failed (no response).")
                break
        else:
            logger.error("Validator: final validation attempt failed after self-correction.")

    return None
