import re
import json
from . import utils

logger = utils.setup_logger(__name__)

# -------------------------------------------------------------------
# [[BS]] backslash-token scheme (preferred)
# If the model follows the drill prompt correctly, it should output [[BS]]
# instead of raw "\" for LaTeX, so this validator will mostly just parse JSON.
# The escaping logic below remains as a safety net for legacy / non-compliant outputs.
# -------------------------------------------------------------------
_BS_TOKEN = "[[BS]]"

# Regex + helper to repair invalid JSON backslash escapes coming from LaTeX.
# JSON only allows: \" \\ \/ \b \f \n \r \t \uXXXX

# 1) FIX: LaTeX commands that START with valid JSON escapes:
#    \t (tab)  -> \text, \theta, \times, \tan, ...
#    \f (formfeed) -> \frac, \forall, ...
#    \b (backspace) -> \beta, \begin, ...
#    \r (carriage return) -> \rho, \right, \rangle, ...
#
# We ONLY apply when the escape is followed by a letter, so we don't touch
# normal JSON escapes like "\t " used intentionally (rare), and we DO NOT
# touch "\n" because you legitimately use \n for line breaks.
_LATEX_VALID_ESCAPE_PREFIX_RE = re.compile(r'(?<!\\)\\([bfrt])(?=[A-Za-z])')

# 2) FIX: \u is "valid" only if it is followed by 4 hex digits.
# LaTeX has lots of commands starting with \u (e.g. \underline).
# If the model outputs "\underline" in JSON source, json.loads will fail
# with "Invalid \uXXXX escape". So we convert "\uX..." -> "\\uX..." unless
# it's a real unicode escape.
_BAD_UNICODE_ESCAPE_RE = re.compile(r'(?<!\\)\\u(?![0-9a-fA-F]{4})')

# 3) Your original invalid-escape repair (kept)
_INVALID_JSON_ESCAPE_RE = re.compile(r'(?<!\\)\\([^"\\/bfnrtu])')


def _escape_invalid_json_backslashes(s: str) -> str:
    r"""
    Repair invalid JSON backslash escapes such as '\mathbb', '\langle', '\zeta'
    written with a single backslash in the JSON source (e.g. '\mathbb{N}' inside
    a JSON string).

    ALSO repairs LaTeX commands that start with JSON-valid escapes:
      - \text, \theta, \times, \tan, ...
      - \frac, \forall, ...
      - \beta, \begin, ...
      - \rho, \right, \rangle, ...
    because JSON would otherwise interpret \t, \f, \b, \r as control escapes.

    We deliberately:
      - leave already-escaped sequences like '\\\\mathbb' unchanged (negative lookbehind).
      - do NOT touch '\n' because you legitimately use \n for line breaks in JSON strings.

    Note:
      - If the model uses the [[BS]] scheme, there may be no raw backslashes to repair.
    """
    if not s:
        return s

    # Fast path: nothing to repair
    if "\\" not in s:
        return s

    # (A) Fix \u that is NOT a real unicode escape (\uXXXX)
    s = _BAD_UNICODE_ESCAPE_RE.sub(r"\\\\u", s)

    # (B) Fix LaTeX commands starting with \b \f \r \t  (but not \n)
    s = _LATEX_VALID_ESCAPE_PREFIX_RE.sub(r"\\\\\1", s)

    # (C) Fix all other invalid escapes (\gamma, \pi, \leq, etc.)
    s = _INVALID_JSON_ESCAPE_RE.sub(r"\\\\\1", s)

    return s


def _replace_bs_tokens(obj):
    """
    Recursively replace the [[BS]] token with a single backslash in all strings.

    This runs AFTER json.loads(), so it cannot break JSON validity.
    It applies to all nested fields, including visual_data text labels, etc.
    """
    if obj is None:
        return None

    if isinstance(obj, str):
        if _BS_TOKEN in obj:
            return obj.replace(_BS_TOKEN, "\\")
        return obj

    if isinstance(obj, list):
        return [_replace_bs_tokens(x) for x in obj]

    if isinstance(obj, dict):
        # ✅ Also sanitize keys (model shouldn't put LaTeX in keys, but this makes it bulletproof)
        out = {}
        for k, v in obj.items():
            new_k = _replace_bs_tokens(k) if isinstance(k, str) else k
            out[new_k] = _replace_bs_tokens(v)
        return out

    # numbers / bools / other types
    return obj


# ✅ NEW: Fix literal "\n" / "\t" sequences that should have been real newlines/tabs.
# This runs AFTER json.loads(), so it cannot break JSON validity.
def _normalize_visible_escapes(obj):
    """
    Recursively converts literal escape sequences into real characters in all strings:
      - "\\n" -> "\n"
      - "\\t" -> "\t"

    This prevents UI from showing "\n" when the model accidentally emitted "\\n" in JSON source.
    Safe to run even if strings already contain real newlines/tabs (no-op).
    """
    if obj is None:
        return None

    if isinstance(obj, str):
        if "\\n" in obj or "\\t" in obj:
            return obj.replace("\\n", "\n").replace("\\t", "\t")
        return obj

    if isinstance(obj, list):
        return [_normalize_visible_escapes(x) for x in obj]

    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            new_k = _normalize_visible_escapes(k) if isinstance(k, str) else k
            out[new_k] = _normalize_visible_escapes(v)
        return out

    return obj


def _parse_and_repair(raw_text: str):
    r"""
    Takes a raw string from an AI, attempts to repair common errors,
    and parses it into a JSON object.

    Deliberately minimal:
    - Find the JSON block (optionally inside ```json ... ```).
    - Strip control characters and smart quotes.
    - Repair invalid backslash escapes (e.g. \mathbb, \text, \theta) for JSON.
    - Remove trailing commas before } or ].
    - Parse with json.loads.
    - Replace [[BS]] tokens with real backslashes AFTER parsing.

    NOTE: We do not touch or normalize any math fences here.
    Whatever the model outputs inside strings is preserved (up to the
    minimal escaping needed for valid JSON).
    """
    if not raw_text:
        logger.warning("Validator: empty response.")
        return None

    logger.debug("Validator: attempting parse. Raw (first 500 chars): %s", raw_text[:500])

    try:
        # Step 1: Find the JSON block, even if it's wrapped in markdown.
        json_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw_text)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match_plain = re.search(r"\{[\s\S]*\}", raw_text)
            if not json_match_plain:
                logger.warning("Validator: no JSON object found in AI response.")
                logger.debug("Validator: full raw (first 2000 chars): %s", raw_text[:2000])
                return None
            json_str = json_match_plain.group(0)

        # Step 2: Clean up common formatting issues.
        control_char_re = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
        json_str = control_char_re.sub("", json_str)
        json_str = (
            json_str
            .replace("\u00a0", " ")
            .replace("“", '"').replace("”", '"')
            .replace("‘", "'").replace("’", "'")
        )

        # Step 2b: Repair invalid JSON backslash escapes coming from legacy LaTeX commands.
        # If model uses [[BS]] scheme, this is typically a no-op.
        json_str = _escape_invalid_json_backslashes(json_str)

        # Step 3: Remove trailing commas before closing braces/brackets.
        json_str = re.sub(r",\s*([}\]])", r"\1", json_str)

        # Step 4: Attempt to parse.
        parsed_data = json.loads(json_str)
        logger.debug("Validator: JSON parsed successfully.")

        # Step 5: Replace [[BS]] tokens with real backslashes (safe: after parsing).
        parsed_data = _replace_bs_tokens(parsed_data)

        # ✅ Step 6: Normalize accidental visible escapes (e.g. "\\n" showing as "\n" in UI).
        parsed_data = _normalize_visible_escapes(parsed_data)

        return parsed_data

    except Exception as e:
        short = utils.truncate(str(e), limit=160)
        logger.warning("Validator: parse failed after repair attempts — %s", short)
        logger.debug("Validator: original raw (first 2000 chars): %s", raw_text[:2000])
        return None


def validate_and_correct_response(
    chat_session,
    gemini_model,
    initial_response_text: str
):
    r"""
    The main 'Quality Inspector' function. Validates and optionally corrects the model response.

    - First attempt: parse/repair.
    - If that fails: ask the model once to self-correct into valid JSON.
    - Second attempt: parse again.
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
            error_message = "The previous response was not valid JSON."
            current_response_text = correction_func(
                chat_session,
                error_message,
                current_response_text
            )

            if not current_response_text:
                logger.error("Validator: AI self-correction failed (no response).")
                break
        else:
            logger.error("Validator: final validation attempt failed after self-correction.")

    return None