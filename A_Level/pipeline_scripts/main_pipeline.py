import os
import re
import json
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

logger = utils.setup_logger(__name__)


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
        match = re.match(r'(\d+)', question_id)
        if not match:
            logger.warning(f"Could not determine main question number from id: '{question_id}'. Skipping.")
            continue

        main_id = match.group(1)

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
    Build 'paired' structures from questions only (no answers).
    This keeps parent stems in the flow and allows grouping/context to work.
    """
    pseudo = []
    for q in q_items or []:
        qid = (q.get("id") or "").strip()
        if not qid:
            continue
        pseudo.append({
            "question_id": qid,
            "original_question": q,
            "original_answer": {}  # none available
        })
    logger.info("Pipeline: built %d pseudo-pairs from questions-only batch.", len(pseudo))
    return pseudo


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

        # Create/merge Topic doc metadata only for the Topics root (keeps existing behavior)
        if collection_root == "Topics":
            firebase_uploader.create_or_update_topic(db_client, base_name)

        # 3a) Match items OR build pseudo-pairs
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
            # Filter by main id if needed
            main_q_pair = group.get("main_pair", {}) or {}
            main_qid = main_q_pair.get("question_id") or (main_q_pair.get("original_question", {}) or {}).get("id", "N/A")
            m = re.match(r"(\d+)", str(main_qid))
            main_id_for_filter = m.group(1) if m else str(main_qid)

            if questions_to_process and main_id_for_filter not in questions_to_process:
                logger.info(f"Skipping group {main_id_for_filter} due to QUESTIONS_TO_PROCESS filter.")
                continue

            all_pairs = [group["main_pair"]] + group.get("sub_question_pairs", [])
            full_reference_text = "\n".join(
                f"Part ({p.get('question_id') or (p.get('original_question', {}) or {}).get('id', '')}): "
                f"{((p.get('original_question', {}) or {}).get('content') or '').strip()}"
                for p in all_pairs
            )

            for target_pair in all_pairs:
                qid = target_pair.get("question_id") or (target_pair.get("original_question", {}) or {}).get("id", "N/A")
                q_text = ((target_pair.get("original_question", {}) or {}).get("content") or "").strip()

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
                        full_reference_text,              # full group context
                        target_pair,                      # the specific Q/A pair for this part
                        correction_feedback=correction_feedback,
                        keep_structure=keep_effective,
                    )

                    if not generated_object:
                        logger.error(f"{base_name} | {qid} | Generation failed on attempt {attempt + 1}.")
                        continue

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

                    new_question_id = str(qid)  # use the hierarchical id like '1a', '3', etc.
                    new_question_object["topic"] = base_name
                    new_question_object["question_number"] = new_question_id
                    new_question_object["total_marks"] = (feedback_object or {}).get("marks", 0)

                    # Save locally for audit/debug
                    os.makedirs("processed_data", exist_ok=True)
                    utils.save_json_file(new_question_object, f"processed_data/{base_name}_Q{new_question_id}.json")

                    # Console summary for upload
                    stem_preview = (new_question_object.get("question_stem") or new_question_object.get("prompt") or "").replace("\n", " ")
                    logger.info(
                        f"{base_name} | {qid} | Uploading — Marks={new_question_object['total_marks']}, Stem='{stem_preview[:60]}...'"
                    )

                    # Upload via uploader
                    collection_path = f"{collection_root}/{base_name}/Questions"
                    ok = firebase_uploader.upload_content(db_client, collection_path, new_question_id, new_question_object)
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