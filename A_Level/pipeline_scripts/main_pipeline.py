# pipeline_scripts/main_pipeline.py
import os
import re
import json
import datetime
from typing import Optional

from config import settings
from . import utils
from . import document_analyzer
from . import document_sorter
from . import item_matcher
from . import content_creator
from . import firebase_uploader
from . import content_checker
from . import cas_validator              # CAS engine (SymPy-based)
from . import checks_cas                 # NEW: build answer_spec from generated objects
from . import structure_guard            # NEW: topicality/coherence screen

logger = utils.setup_logger(__name__)


# ---------- ID / hierarchy helpers (leaf-only rule) ----------

def _build_id_set(items):
    ids = set()
    for it in items or []:
        qid = (it.get("id") or "").strip()
        if qid:
            ids.add(qid)
    return ids


def _has_child_id(target_id: str, all_ids: set[str]) -> bool:
    """
    'Parent' if any other ID *extends* it with a trailing letter.
    Examples:
      '1'  -> parent if '1a', '1b', '1ai' exist.
      '3a' -> parent if '3ai', '3aii' exist.
    Safeguards:
      - '1' is NOT parent of '10' (next char is digit, not alpha).
    """
    if not target_id:
        return False
    tlen = len(target_id)
    for other in all_ids:
        if other == target_id or len(other) <= tlen:
            continue
        if other.startswith(target_id):
            next_ch = other[tlen]
            if next_ch.isalpha():
                return True
    return False


def _main_numeric_id(qid: str) -> str:
    m = re.match(r"(\d+)", str(qid or ""))
    return m.group(1) if m else str(qid or "")


# ---------- FIX #3: numbering helpers (append under existing) ----------

_NUM_PREFIX_RE = re.compile(r"^(\d+)")

def _extract_int_prefix(val: object) -> Optional[int]:
    """Parse a numeric prefix from int/str like 12, '12', '12a', '12-1' -> 12."""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    s = str(val).strip()
    if not s:
        return None
    m = _NUM_PREFIX_RE.match(s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _get_existing_max_question_number(db_client, *, uid: str, upload_id: str) -> int:
    """
    Look at existing docs in Users/{uid}/Uploads/{upload_id}/Questions and return the
    max numeric question number we can detect.

    We intentionally look at:
      - field 'question_number'
      - field 'logical_question_id'
      - Firestore doc id (e.g. '12', '12-1')
    """
    try:
        coll = (
            db_client.collection("Users")
                     .document(uid)
                     .collection("Uploads")
                     .document(upload_id)
                     .collection("Questions")
        )
        snap = coll.get()
    except Exception as e:
        logger.warning("Could not read existing Questions for %s/%s: %s", uid, upload_id, e)
        return 0

    max_n = 0
    for d in getattr(snap, "documents", []) or []:
        try:
            data = d.to_dict() or {}
        except Exception:
            data = {}

        candidates = [
            _extract_int_prefix(data.get("question_number")),
            _extract_int_prefix(data.get("logical_question_id")),
            _extract_int_prefix(getattr(d, "id", None)),
        ]
        for c in candidates:
            if isinstance(c, int) and c > max_n:
                max_n = c

    return max_n


# ---------- grouping logic ----------

def group_paired_items(paired_refs):
    """
    Groups a flat list of items into hierarchical structures for context gathering.
    This version uses the item's ID to detect the start of a new main question group.
    """
    grouped_questions = []
    current_main_question_group = None
    current_main_question_id = None

    for pair in paired_refs:
        question_id = pair.get("question_id")
        if not question_id:
            logger.warning("Skipping a pair because it lacks a 'question_id'.")
            continue

        # Extract the main question number (e.g., '4' from '4b' or '12' from '12ai')
        main_id = _main_numeric_id(question_id)
        if not main_id or not main_id.isdigit():
            logger.warning(f"Could not determine main question number from id: '{question_id}'. Skipping.")
            continue

        # If the main question number changes, start a new group.
        if main_id != current_main_question_id:
            current_main_question_id = main_id
            current_main_question_group = {"main_pair": pair, "sub_question_pairs": []}
            grouped_questions.append(current_main_question_group)
        # Otherwise, if it's the same main question, add it as a sub-question.
        else:
            if current_main_question_group:
                current_main_question_group["sub_question_pairs"].append(pair)
            else:
                # Edge case safeguard.
                logger.warning(
                    f"Found a sub-question pair (id: {question_id}) with no preceding main question. "
                    "Creating a new group for it."
                )
                current_main_question_group = {"main_pair": pair, "sub_question_pairs": []}
                grouped_questions.append(current_main_question_group)

    logger.info(f"Grouped items into {len(grouped_questions)} main question structures.")
    return grouped_questions


def _build_pseudo_pairs_from_questions(q_items):
    """
    Build 'paired' structures from questions only (no answers), **leaf-only**:
    - Skip any parent/context items (IDs extended by trailing-letter children).
    """
    all_ids = _build_id_set(q_items)
    pseudo = []
    skipped_parents = 0

    for q in q_items or []:
        qid = (q.get("id") or "").strip()
        if not qid:
            continue
        if _has_child_id(qid, all_ids):
            skipped_parents += 1
            continue  # leaf-only filter
        pseudo.append({
            "question_id": qid,
            "original_question": q,
            "original_answer": {}  # none available
        })

    logger.info(
        "Pipeline: built %d pseudo-pairs from questions-only batch (skipped %d parent stems).",
        len(pseudo), skipped_parents
    )
    return pseudo


def _build_parent_context_lookup(q_items):
    """
    Build a lookup for parent/context content by ID and by main numeric ID.
    Returns:
      - id_to_q: {id -> question_item}
      - parent_text_by_main: {main_numeric_id -> stem_text (numeric parent content if present)}
      - parent_texts_all_levels_by_main: {main_numeric_id -> [ (id, content) ... ] } for any parent levels like '1', '1a'
    """
    id_to_q = { (q.get("id") or "").strip(): q for q in (q_items or []) if (q.get("id") or "").strip() }
    all_ids = set(id_to_q.keys())

    parent_text_by_main = {}
    parent_texts_all_levels_by_main = {}

    for qid, q in id_to_q.items():
        if _has_child_id(qid, all_ids):
            text = (q.get("content") or "").strip()
            if not text:
                continue
            main_id = _main_numeric_id(qid)
            if qid == main_id:  # numeric stem (e.g., '1')
                parent_text_by_main[main_id] = text
            parent_texts_all_levels_by_main.setdefault(main_id, []).append((qid, text))

    # Keep deterministic order: sort parents by ID length (numeric first, then alpha, then roman parents)
    for k, arr in parent_texts_all_levels_by_main.items():
        parent_texts_all_levels_by_main[k] = sorted(arr, key=lambda t: (len(t[0]), t[0]))

    return id_to_q, parent_text_by_main, parent_texts_all_levels_by_main


def _compose_group_context_text(main_id_for_filter, all_pairs, id_to_q, parent_text_by_main, parent_all_levels_by_main):
    """
    Compose rich context for generation:
      1) Numeric stem text (e.g., '1') if available.
      2) Any mid-level parent texts ('1a', '1b' that have roman children), labeled as Context.
      3) The visible parts (the leaves) in the group (existing behavior).
    """
    lines = []

    # 1) Numeric stem first
    stem_txt = parent_text_by_main.get(main_id_for_filter, "").strip()
    if stem_txt:
        lines.append(f"Stem ({main_id_for_filter}): {stem_txt}")

    # 2) Mid-level parent texts (if any), excluding the numeric stem to avoid duplication
    for pid, ptxt in parent_all_levels_by_main.get(main_id_for_filter, []):
        if pid == main_id_for_filter:
            continue
        # Only include if this parent is NOT already one of the target leaves
        if not any(((p.get('question_id') or (p.get('original_question', {}) or {}).get('id', '')).strip() == pid) for p in all_pairs):
            lines.append(f"Context ({pid}): {ptxt}")

    # 3) Actual parts (leaves)
    for p in all_pairs:
        pid = (p.get('question_id') or (p.get('original_question', {}) or {}).get('id', '')).strip()
        ptxt = ((p.get('original_question', {}) or {}).get('content') or '').strip()
        if not ptxt:
            continue
        lines.append(f"Part ({pid}): {ptxt}")

    return "\n".join(lines)


# ---------- MCQ detection & collapsing ----------

_ALPHA_ONE_RE = re.compile(r"^(\d+)([a-z])$")

_OPTION_VERB_BLACKLIST = re.compile(
    r"\b(show that|prove|hence|find|solve|determine|evaluate|differentiate|integrate|sketch|plot|state|write down)\b",
    re.IGNORECASE
)

_STEM_MCQ_CUES = re.compile(
    r"\b(which of the following|choose|select|best estimate|which statement is true|closest to|is equal to|is equivalent to|which of these)\b",
    re.IGNORECASE
)

def _is_option_like(text: str) -> bool:
    """Heuristic: short, not directive, looks like an answer option."""
    if not text:
        return False
    t = (text or "").strip()
    if len(t) > 140:
        return False
    if _OPTION_VERB_BLACKLIST.search(t):
        return False
    # Avoid multi-step workings: multiple equals/semicolons suggest reasoning steps
    if t.count("=") >= 2 or t.count(";") >= 2:
        return False
    return True


def _collect_alpha_leaf_pairs(group):
    """Return [(pair, id, alpha_letter, content)] for 1a/1b/... leaves in this group."""
    out = []
    all_pairs = [group.get("main_pair")] + (group.get("sub_question_pairs") or [])
    for p in all_pairs:
        qid = (p.get("question_id") or (p.get("original_question", {}) or {}).get("id", "")).strip()
        m = _ALPHA_ONE_RE.match(qid)
        if not m:
            continue
        alpha = m.group(2).lower()
        content = ((p.get("original_question", {}) or {}).get("content") or "").strip()
        out.append((p, qid, alpha, content))
    return out


def _try_collapse_group_to_mcq(group, id_to_q):
    """
    If this group looks like an MCQ (several alpha leaves that read like options + a stem),
    return (True, synthetic_pair, mcq_reference_text). Otherwise (False, None, None).

    CHANGE: Require explicit MCQ cues in the stem to avoid collapsing genuine multi-part problems.
    """
    alpha_pairs = _collect_alpha_leaf_pairs(group)
    # need 3..6 plausible options
    if not (3 <= len(alpha_pairs) <= 6):
        return False, None, None

    # check all look like options
    if not all(_is_option_like(c) for _, __, ___, c in alpha_pairs):
        return False, None, None

    # get main numeric id and stem text
    main_qid = (group.get("main_pair", {}) or {}).get("question_id") or (group.get("main_pair", {}) or {}).get("original_question", {}).get("id", "")
    main_id = _main_numeric_id(main_qid)
    stem_txt = ((id_to_q.get(main_id) or {}).get("content") or "").strip()

    # Prefer a stem; if not present, decline MCQ collapse
    if not stem_txt:
        return False, None, None

    # NEW: Require explicit MCQ cues in the stem to avoid false positives
    if not _STEM_MCQ_CUES.search(stem_txt):
        return False, None, None

    # Build synthetic pair
    options_sorted = sorted(alpha_pairs, key=lambda t: t[2])  # by alpha
    options_lines = []
    for _, __, alpha, content in options_sorted:
        options_lines.append(f"Option {alpha.upper()}: {content}")

    mcq_reference_text = f"Stem ({main_id}): {stem_txt}\n" + "\n".join(options_lines)

    synthetic_pair = {
        "question_id": main_id,  # treat as one question
        "original_question": {
            "id": main_id,
            "type": "num",
            "raw_label": f"Q{main_id}",
            "content": mcq_reference_text,  # pack stem + options into content for context
        },
        "original_answer": {},
        "synthetic_mcq": True  # signal to bypass parent-skip guard
    }

    return True, synthetic_pair, mcq_reference_text


# ---------- test mode (prints -> logs) ----------

def test_sorter_and_matcher():
    """
    A test function to run only the document sorting, AI matching, and grouping steps.
    """
    logger.info("--- Running in TEST MODE: Sorting and AI Matching Only ---")

    # 1) Sort and Group Source Documents
    processing_jobs = document_sorter.sort_and_group_documents(settings.INPUT_PDF_DIR)
    if not processing_jobs:
        logger.warning("Smart Sorter found no processing jobs. Exiting test.")
        return

    # 2) Process Each Job to Match and Group Items
    for job in processing_jobs:
        job_type = job.get("type")
        base_name = job.get("name", "untitled")
        logger.info(f"[TEST] Processing Job: '{base_name}' (Type: {job_type})")

        q_items, a_items = None, None

        if job_type == "paired":
            q_items = job.get("questions")
            a_items = job.get("answers")
        elif job_type == "interleaved":
            q_items, a_items = document_sorter.split_interleaved_items(job.get("content"))
        elif job_type == "questions_only":
            q_items = job.get("questions") or []
            a_items = []

        if job_type == "questions_only":
            paired_refs = _build_pseudo_pairs_from_questions(q_items)
        else:
            if not (q_items and a_items):
                logger.warning(f"Skipping job '{base_name}' due to missing question or answer items.")
                continue
            paired_refs, unmatched = item_matcher.match_items_with_ai(q_items, a_items)
            if not paired_refs:
                logger.warning(f"AI Matcher found no pairs for job '{base_name}'.")
                continue

        hierarchical_groups = group_paired_items(paired_refs)

        # 3) Summary Report (logged)
        logger.info(
            f"[TEST] Job '{base_name}': pairs={len(paired_refs)}, "
            f"groups={len(hierarchical_groups)}"
        )

        test_output_dir = os.path.join(settings.PROCESSED_DATA_DIR, "test_outputs")
        os.makedirs(test_output_dir, exist_ok=True)
        utils.save_json_file(
            {"paired_refs": paired_refs, "hierarchical_groups": hierarchical_groups},
            os.path.join(test_output_dir, f"{base_name}_AImatch_summary.json")
        )

    logger.info("--- TEST MODE Finished ---")


# ---------- main pipeline with concise logging + run report ----------

def run_full_pipeline(
    *,
    allow_questions_only: bool | None = None,
    keep_structure: bool | None = None,
    cas_policy: str | None = None,
    collection_root: str | None = None,
    uid: Optional[str] = None,
    upload_id: Optional[str] = None,
):
    """The main orchestrator for the 'Self-Contained Skills' generation process."""
    logger.info("--- Starting Full Content Pipeline (Generator–Checker–CAS) ---")

    # Start run report (also captures the per-run log file path)
    run_report = utils.start_run_report()

    # 1) Initialization
    db_client = firebase_uploader.initialize_firebase()
    gemini_content_model = content_creator.initialize_gemini_client()
    gemini_checker_model = content_checker.initialize_gemini_client()
    if not db_client or not gemini_content_model or not gemini_checker_model:
        logger.error("Initialization failed (db/model). Aborting.")
        utils.save_run_report(run_report)
        return

    # If caller didn't pass uid/upload_id, try global fallback (keeps old behavior intact).
    uid = uid or globals().get("uid")
    upload_id = upload_id or globals().get("upload_id")

    # Pre-compute append numbering (Fix #3).
    # If uid/upload_id aren't available (e.g. running standalone), we just don't apply renumbering.
    next_question_number: Optional[int] = None
    if uid and upload_id:
        existing_max = _get_existing_max_question_number(db_client, uid=str(uid), upload_id=str(upload_id))
        next_question_number = int(existing_max) + 1
        logger.info(
            "Append numbering enabled for Users/%s/Uploads/%s — existing max=%s, next=%s",
            uid, upload_id, existing_max, next_question_number
        )
    else:
        logger.warning("Append numbering disabled (uid/upload_id not provided). Standalone run assumed.")

    # 2) Sort and Group Source Documents (PDF folder mode)
    processing_jobs = document_sorter.sort_and_group_documents(settings.INPUT_PDF_DIR)
    if not processing_jobs:
        logger.warning("Smart Sorter found no processing jobs. Exiting pipeline.")
        utils.save_run_report(run_report)
        return

    run_report["totals"]["jobs"] = len(processing_jobs)

    # defaults from settings, can be overridden by args above
    collection_root = collection_root or getattr(settings, "DEFAULT_COLLECTION_ROOT", "Topics")
    cas_policy = (cas_policy or getattr(settings, "CAS_POLICY", "off")).strip().lower()
    if cas_policy not in {"off", "prefer", "require"}:
        cas_policy = "off"
    allow_q_only_flag = (
        settings.ALLOW_QUESTIONS_ONLY if allow_questions_only is None else bool(allow_questions_only)
    )

    # 3) Process Each Job
    for job in processing_jobs:
        job_type = job.get("type")
        base_name = job.get("name", "untitled")
        logger.info(f"Processing Job: '{base_name}' (Type: {job_type})")

        # Honor per-run flag for questions-only jobs
        if job_type == "questions_only" and not allow_q_only_flag:
            logger.info("Skipping questions-only job because allow_questions_only=False.")
            continue

        job_summary = utils.new_job_summary(base_name, job_type)

        q_items, a_items = None, None

        if job_type == "paired":
            q_items = job.get("questions")
            a_items = job.get("answers")
        elif job_type == "interleaved":
            q_items, a_items = document_sorter.split_interleaved_items(job.get("content"))
        elif job_type == "questions_only":
            # allow questions-only uploads (images/PDFs with no mark scheme)
            q_items = job.get("questions") or []
            a_items = []

        # Build context lookups from the original question items (for all job types)
        id_to_q, parent_text_by_main, parent_all_levels_by_main = _build_parent_context_lookup(q_items or [])

        # Create/merge Topic doc metadata only for the Topics root (keeps existing behavior)
        if collection_root == "Topics":
            firebase_uploader.create_or_update_topic(db_client, base_name)

        # 3a) Match items OR build pseudo-pairs (leaf-only for questions_only)
        if job_type == "questions_only":
            paired_refs = _build_pseudo_pairs_from_questions(q_items)
        else:
            if not (q_items and a_items):
                logger.warning(f"Skipping job '{base_name}' due to missing question or answer items.")
                run_report["jobs"].append(job_summary)
                continue
            paired_refs, _ = item_matcher.match_items_with_ai(q_items, a_items)
            if not paired_refs:
                logger.warning(f"No item pairs could be matched for job '{base_name}'. Skipping.")
                run_report["jobs"].append(job_summary)
                continue

        hierarchical_groups = group_paired_items(paired_refs)
        job_summary["groups"] = len(hierarchical_groups)
        run_report["totals"]["groups"] += len(hierarchical_groups)

        # Decide keep-structure behavior for this job
        default_keep_when_q_only = getattr(settings, "KEEP_STRUCTURE_WHEN_QUESTIONS_ONLY", False)
        default_keep = getattr(settings, "KEEP_STRUCTURE_DEFAULT", False)
        if keep_structure is None:
            keep_effective = default_keep_when_q_only if job_type == "questions_only" else default_keep
        else:
            keep_effective = bool(keep_structure)

        # 4) Generate, CAS-validate (optional), Verify (with retry), and Upload
        questions_to_process = getattr(settings, "QUESTIONS_TO_PROCESS", None)  # None or list of main IDs

        for group in hierarchical_groups:
            # Determine main numeric id
            main_q_pair = group.get("main_pair", {}) or {}
            main_qid = main_q_pair.get("question_id") or (main_q_pair.get("original_question", {}) or {}).get("id", "N/A")
            main_id_for_filter = _main_numeric_id(main_qid)

            # Apply optional main-ID filter
            if questions_to_process and main_id_for_filter not in questions_to_process:
                logger.info(f"Skipping group {main_id_for_filter} due to QUESTIONS_TO_PROCESS filter.")
                continue

            # Try MCQ collapse for this group
            is_mcq, synthetic_pair, mcq_ref_text = _try_collapse_group_to_mcq(group, id_to_q)

            if is_mcq:
                all_pairs = [synthetic_pair]
                full_reference_text = mcq_ref_text
                logger.info("MCQ collapse applied for main %s — generating a single MCQ item.", main_id_for_filter)
            else:
                # Build rich group context text (numeric stem + any mid-level parents + the visible parts)
                all_pairs = [group["main_pair"]] + group.get("sub_question_pairs", [])
                full_reference_text = _compose_group_context_text(
                    main_id_for_filter,
                    all_pairs,
                    id_to_q,
                    parent_text_by_main,
                    parent_all_levels_by_main
                )

            # Generate **only for leaves/synthetic MCQ**
            for target_pair in all_pairs:
                qid = target_pair.get("question_id") or (target_pair.get("original_question", {}) or {}).get("id", "N/A")
                q_text = ((target_pair.get("original_question", {}) or {}).get("content") or "").strip()

                # Defensive: skip if this qid is a parent (shouldn't happen after leaf-only filtering)
                if _has_child_id(str(qid), set(id_to_q.keys())) and not target_pair.get("synthetic_mcq"):
                    logger.debug("Skipping parent/context id '%s' at generation step.", qid)
                    continue

                # Prefer worked solution; fall back to notes
                a_text = (
                    ((target_pair.get("original_answer", {}) or {}).get("content") or "") or
                    ((target_pair.get("original_answer", {}) or {}).get("pedagogical_notes") or "")
                ).strip()

                if not q_text:
                    logger.info(f"Skipping '{qid}': no source question text.")
                    continue

                job_summary["parts_processed"] += 1
                run_report["totals"]["parts_processed"] += 1

                new_question_object = None
                feedback_object = None
                correction_feedback = None
                cas_last_report = None

                for attempt in range(2):  # 1 initial + 1 retry on feedback (CAS or checker)
                    logger.info(f"{base_name} | {qid} | Attempt {attempt + 1}/2")

                    generated_object = content_creator.create_question(
                        gemini_content_model,
                        full_reference_text,              # full group context (includes stem/options if MCQ)
                        target_pair,                      # the specific Q/A pair for this part
                        correction_feedback=correction_feedback,
                        keep_structure=keep_effective,
                    )

                    if not generated_object:
                        logger.error(f"{base_name} | {qid} | Generation failed on attempt {attempt + 1}.")
                        continue

                    # --- NEW: structural & relevance screening (cheap, before CAS/checker) ---
                    ok_sr, reason_sr = structure_guard.screen_structure_and_relevance(
                        gemini_checker_model,
                        generated_object,
                        full_reference_text
                    )
                    if not ok_sr:
                        correction_feedback = (
                            "Your previous question either drifted off-topic or combined multiple "
                            "independent tasks. Regenerate ONE coherent question that stays within "
                            "the same topic and tests the same skills."
                            f"Issue: {reason_sr}"
                        )
                        continue  # retry once with the correction feedback

                    # --- Build/attach a CAS answer_spec if possible (from final_answer etc.) ---
                    spec = checks_cas.build_answer_spec_from_generated(generated_object)
                    if spec:
                        generated_object["answer_spec"] = spec  # attach for downstream validation

                    # --- CAS validation (optional) BEFORE AI checker to avoid wasted calls ---
                    cas_ok = True
                    if cas_policy != "off" and spec:
                        try:
                            cas_ok, cas_last_report = cas_validator.validate(generated_object)
                        except Exception as e:
                            cas_ok, cas_last_report = True, {"kind": "internal", "reason": f"CAS error: {e}"}
                            logger.error("%s | %s | CAS internal error — %s", base_name, qid, e)

                        if not cas_ok:
                            reason = (cas_last_report or {}).get("details") or (cas_last_report or {}).get("reason") or "unknown"
                            short_reason = utils.truncate(str(reason), 160)
                            logger.debug(f"{base_name} | {qid} | CAS rejected — {short_reason}")
                            if cas_policy == "require":
                                correction_feedback = f"CAS validation failed: {reason}. Regenerate and fix while obeying all original rules."
                                # Retry once; skip checker this round
                                continue
                            # If 'prefer', proceed to checker but retain the CAS report for logging/audit.

                    # --- AI checker (existing) ---
                    feedback_object = content_checker.verify_and_mark_question(
                        gemini_checker_model,
                        generated_object
                    )

                    # Decide acceptance based on checker + CAS policy
                    if feedback_object and feedback_object.get("is_correct"):
                        if cas_policy == "require" and not cas_ok:
                            correction_feedback = f"CAS must pass; last failure: {(cas_last_report or {}).get('details')}"
                        else:
                            new_question_object = generated_object
                            # Attach compact validation notes for audit (not required by app)
                            if cas_policy != "off":
                                new_question_object.setdefault("validation", {})
                                new_question_object["validation"]["cas_ok"] = bool(cas_ok)
                                new_question_object["validation"]["cas"] = cas_last_report
                            logger.info(f"{base_name} | {qid} | ✅ Verified on attempt {attempt + 1} "
                                        f"(marks={feedback_object.get('marks', 0)}, cas_ok={cas_ok})")
                            break
                    elif feedback_object:
                        correction_feedback = feedback_object.get("feedback") or ""
                        # Demote attempt-level rejection to DEBUG to keep console concise
                        logger.debug(f"{base_name} | {qid} | Rejected (attempt {attempt + 1}) — {utils.truncate(correction_feedback, 120)}")
                        logger.debug(f"{base_name} | {qid} | Full reject reason: {correction_feedback}")
                    else:
                        logger.error(f"{base_name} | {qid} | Checker failed (attempt {attempt + 1}).")
                        correction_feedback = "Checker did not return feedback. Regenerate from scratch."

                # Finalize and upload if verified
                if new_question_object:
                    # Clean empty visual_data for your app model (as before)
                    if new_question_object.get("visual_data") == {}:
                        logger.debug(f"{base_name} | {qid} | Removing empty 'visual_data'.")
                        del new_question_object["visual_data"]

                    # ----------------------------
                    # FIX #3: assign NEXT numeric label under existing max
                    # ----------------------------
                    if next_question_number is not None:
                        new_question_id = str(int(next_question_number))
                        next_question_number += 1
                    else:
                        # Fallback (standalone) — old behavior
                        new_question_id = str(qid)

                    new_question_object["topic"] = base_name
                    new_question_object["question_number"] = new_question_id
                    new_question_object["total_marks"] = (feedback_object or {}).get("marks", 0)

                    # Add “new vs old” info
                    new_question_object["source_question_id"] = str(qid)
                    new_question_object["added_at"] = datetime.datetime.utcnow().isoformat() + "Z"

                    # Save locally for audit/debug
                    os.makedirs("processed_data", exist_ok=True)
                    utils.save_json_file(new_question_object, f"processed_data/{base_name}_Q{new_question_id}.json")

                    # Console summary for upload
                    stem_preview = (new_question_object.get("question_stem") or new_question_object.get("prompt") or "").replace("\n", " ")
                    logger.info(
                        f"{base_name} | {qid} | Uploading as Q{new_question_id} — Marks={new_question_object['total_marks']}, Stem='{stem_preview[:60]}...'"
                    )

                    # Upload via uploader
                    # --- USER UPLOAD TARGET PATH ---
                    if not uid or not upload_id:
                        raise RuntimeError("uid/upload_id missing: cannot upload to Users/.../Uploads/.../Questions")

                    collection_path = f"Users/{uid}/Uploads/{upload_id}/Questions"
                    ok = firebase_uploader.upload_content(
                        db_client,
                        collection_path,
                        new_question_id,
                        new_question_object
                    )
                    if ok:
                        job_summary["uploaded_ok"] += 1
                        run_report["totals"]["uploaded_ok"] += 1
                    else:
                        job_summary["upload_failed"] += 1
                        run_report["totals"]["upload_failed"] += 1

                    job_summary["verified"] += 1
                    run_report["totals"]["verified"] += 1
                else:
                    job_summary["rejected"] += 1
                    run_report["totals"]["rejected"] += 1
                    # Record last known reason
                    if correction_feedback:
                        utils.append_failure(job_summary, str(qid), correction_feedback)
                    elif cas_policy != "off" and cas_last_report:
                        utils.append_failure(job_summary, str(qid), f"CAS failure: {cas_last_report}")
                    else:
                        utils.append_failure(job_summary, str(qid), "verification failed")

        run_report["jobs"].append(job_summary)

    logger.info("--- Full Content Pipeline Finished ---")
    utils.save_run_report(run_report)


if __name__ == '__main__':
    run_full_pipeline()