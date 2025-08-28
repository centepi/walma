import os
import re
import json
import google.generativeai as genai
from config import settings
from . import utils

# Unified logger (do not override global level here)
logger = utils.setup_logger(__name__)

# Optional debug echo toggles (off by default)
ECHO_PROMPTS = os.getenv("LOG_AI_MATCHER_PROMPTS", "").strip().lower() in {"1", "true", "yes"}
ECHO_RESPONSES = os.getenv("LOG_AI_MATCHER_RESPONSES", "").strip().lower() in {"1", "true", "yes"}


def _initialize_gemini_client():
    """Initializes and returns the Gemini client."""
    try:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_MODEL_NAME)
        logger.info("Matcher: Gemini client initialized.")
        return model
    except Exception as e:
        logger.error("Matcher: failed to initialize Gemini client — %s", e)
        return None


def _identify_parent_questions(question_items_list):
    """
    Identifies questions that are just context for sub-parts.
    A question is a parent if it's a 'num' type followed by an 'alpha' or 'roman' type.
    Returns a set of the indices of parent questions.
    """
    parent_question_indices = set()
    for i in range(len(question_items_list) - 1):
        current_q = question_items_list[i]
        next_q = question_items_list[i + 1]

        is_parent = (current_q.get('type') == 'num' and
                     next_q.get('type') in ['alpha', 'roman'])

        if is_parent:
            parent_question_indices.add(i)

    # Also check if a 'num' question has no content, making it a likely parent
    for i, q_item in enumerate(question_items_list):
        content = q_item.get('content') or ''
        if q_item.get('type') == 'num' and not content.strip():
            parent_question_indices.add(i)

    logger.info("Matcher: identified %d parent/context questions.", len(parent_question_indices))
    return parent_question_indices


def _build_answer_index(answer_items_list):
    """
    Builds a map from answer ID -> list of indices (to handle duplicate IDs safely).
    """
    index = {}
    for idx, ans in enumerate(answer_items_list):
        aid = (ans.get("id") or "").strip()
        if not aid:
            continue
        index.setdefault(aid, []).append(idx)
    return index


def _pop_answer_by_id(answer_items_list, answer_index_map, target_id):
    """
    Pops (returns and removes) the first available answer matching target_id from the list + index.
    Returns (answer_item or None, removed_index or None).
    """
    positions = answer_index_map.get(target_id) or []
    if not positions:
        return None, None
    pop_idx = positions.pop(0)
    # Remove this index from all lists in the map (compact references)
    for key, pos_list in answer_index_map.items():
        answer_index_map[key] = [p for p in pos_list if p != pop_idx]
    # Actually pop from the list, and repair the index map offsets > pop_idx
    ans_item = answer_items_list.pop(pop_idx)
    # Rebuild the entire map (simpler + safe) since indices shifted
    new_map = _build_answer_index(answer_items_list)
    answer_index_map.clear()
    answer_index_map.update(new_map)
    return ans_item, pop_idx


def _parse_ai_choice(text: str, num_candidates: int):
    """
    Try to parse the model's reply into an index or None.

    Accepts:
      - "3", "3.", "Candidate 3", "choose 3", etc. -> 3
      - "None" / "none" / "no match" -> None (signal no match)
    """
    if not text:
        return None

    t = text.strip().lower()

    # No-match patterns
    if t in {"none", "no", "no match", "no-match", "n/a"}:
        return None

    # Extract leading or first integer in the text
    m = re.search(r'\b(\d+)\b', t)
    if not m:
        return None

    idx = int(m.group(1))
    if 0 <= idx < num_candidates:
        return idx

    # Sometimes the LLM starts counting at 1 (rare; our prompt implies 0-based)
    if 1 <= idx <= num_candidates:
        # Convert to 0-based if it looks like 1-based
        if idx - 1 >= 0:
            return idx - 1

    return None


def match_items_with_ai(question_items_list, answer_items_list):
    """
    Matches questions to answers using exact-ID matching first, then an AI-powered fallback.
    """
    logger.info("Matcher: starting ID-aware matching…")

    # Fast path: if IDs match exactly, pair without calling the model.
    # Keep a mutable copy of answers for removal.
    available_answers = list(answer_items_list)
    answer_index = _build_answer_index(available_answers)

    paired_references = []
    unmatched_questions = []

    parent_indices = _identify_parent_questions(question_items_list)

    # Prepare model (only if we need it)
    gemini_model = None

    for i, q_item in enumerate(question_items_list):
        # Skip parent questions that are just for context
        if i in parent_indices:
            logger.debug("Matcher: skipping parent/context question '%s' (ID: %s)",
                         q_item.get('raw_label'), q_item.get('id'))
            unmatched_questions.append(q_item)
            continue

        target_id = (q_item.get('id') or "").strip()
        if not target_id:
            logger.warning("Matcher: question '%s' is missing an ID. Skipping.", q_item.get('raw_label'))
            unmatched_questions.append(q_item)
            continue

        # --- 1) Exact ID match (no AI) ---
        exact_ans, exact_pos = _pop_answer_by_id(available_answers, answer_index, target_id)
        if exact_ans is not None:
            paired_references.append({
                "question_id": target_id,
                "original_question": q_item,
                "original_answer": exact_ans
            })
            logger.info("Matcher: paired by ID — Q '%s' ↔ A '%s'.", target_id, exact_ans.get('id'))
            continue

        # --- 2) AI fallback ---
        # Lazy init the model only when needed
        if gemini_model is None:
            gemini_model = _initialize_gemini_client()
            if not gemini_model:
                logger.error("Matcher: cannot run AI fallback (model init failed).")
                break

        # Rebuild the answer candidates list for AI with minimal content
        # (We include content, but avoid logging it unless ECHO_PROMPTS is on.)
        answer_candidates_text = ""
        for j, ans_item in enumerate(available_answers):
            answer_candidates_text += (
                f"Answer Candidate {j}:\n"
                f"ID: {ans_item.get('id', 'N/A')}\n"
                f"Label: {ans_item.get('raw_label', 'N/A')}\n"
                f"Content: {ans_item.get('content', '')}\n---\n"
            )

        q_content = (q_item.get('content') or '').strip()

        prompt = f"""
        You are an expert at matching questions to their corresponding answers using a unique ID system.

        --- The Question to Match ---
        ID: "{target_id}"
        Content: "{q_content}"

        --- Answer Candidates ---
        {answer_candidates_text}

        --- Your Task ---
        Your primary goal is to find the Answer Candidate with the ID that EXACTLY matches the Question's ID ("{target_id}").

        1.  **ID Match First**: Scan the 'ID' field of every Answer Candidate. If you find an exact match for "{target_id}", respond with that candidate's number. This is the most reliable method.
        2.  **Content Match as Fallback**: If, and ONLY if, you cannot find an exact ID match, then analyze the content of the question and candidates to find the most logical pairing.
        3.  **No Match**: If you are certain that none of the candidates are a correct match (neither by ID nor by content), respond with the word 'None'.

        Respond with ONLY the number of the correct Answer Candidate (e.g., '3') or the word 'None'.
        """

        if ECHO_PROMPTS:
            logger.debug("Matcher[AI] Prompt (first 800 chars): %s", utils.truncate(prompt, 800))

        try:
            logger.debug("Matcher: AI fallback for question ID '%s'…", target_id)
            response = gemini_model.generate_content(prompt)
            response_text = (response.text or "").strip()

            if ECHO_RESPONSES:
                logger.debug("Matcher[AI] Raw response: %s", utils.truncate(response_text, 300))

            # Parse the model's choice robustly
            choice = _parse_ai_choice(response_text, num_candidates=len(available_answers))

            if choice is None:
                logger.info("Matcher: AI reported no match for question '%s'.", target_id)
                unmatched_questions.append(q_item)
                continue

            if 0 <= choice < len(available_answers):
                matching_answer_item = available_answers.pop(choice)
                # Rebuild the index map after removal
                answer_index.clear()
                answer_index.update(_build_answer_index(available_answers))

                paired_references.append({
                    "question_id": target_id,
                    "original_question": q_item,
                    "original_answer": matching_answer_item
                })
                logger.info("Matcher: paired via AI — Q '%s' ↔ A '%s' (candidate %d).",
                            target_id, matching_answer_item.get('id'), choice)
            else:
                logger.warning("Matcher: AI gave invalid index %s for '%s'.", str(choice), target_id)
                unmatched_questions.append(q_item)

        except Exception as e:
            logger.error("Matcher: error during AI matching for '%s' — %s", target_id, e)
            unmatched_questions.append(q_item)

    # Any remaining answers are unmatched
    unmatched_answers = available_answers

    logger.info("Matcher: complete. Pairs=%d, UnmatchedQ=%d, UnmatchedA=%d",
                len(paired_references), len(unmatched_questions), len(unmatched_answers))

    unmatched_items = {
        "unmatched_questions": unmatched_questions,
        "unmatched_answers": unmatched_answers
    }

    return paired_references, unmatched_items


if __name__ == '__main__':
    pass
