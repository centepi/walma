# pipeline_scripts/questions_only_jobs.py
"""
Utilities + runner for 'questions-only' uploads (no answers PDF present).

Main public APIs:
- make_main_question_structs(profile) -> List[dict]
- build_questions_only_job(profile)   -> dict
- run_questions_only_batch(keep_structure=False, cas_policy="off") -> None
"""

from __future__ import annotations

import os
os.environ['MPLBACKEND'] = 'Agg'
import re
from glob import glob
from typing import Dict, List, Tuple, Optional
import concurrent.futures

from config import settings
from . import utils
from . import content_creator
from . import content_checker
from . import firebase_uploader
from . import checks_cas
from . import cas_validator

# Optional analyzer; we’ll try to use it if present
try:
    from . import document_analyzer
except Exception:
    document_analyzer = None

logger = utils.setup_logger(__name__)

# ---------------------------
# ID / label helpers
# ---------------------------

_ID_RE = re.compile(r"^\s*(?P<num>\d{1,3})\s*(?P<sub>[a-z]+|i{1,4}|v?i{0,3}|x)?\s*$", re.IGNORECASE)
_LABEL_PATS = getattr(settings, "LABEL_PATTERNS", [])


def _coerce_str(v) -> str:
    return (v or "").strip()


def _split_id(id_str: str) -> Tuple[str, str]:
    """'1a' -> ('1','a'), '7ii' -> ('7','ii'), '14' -> ('14',''), else ('','')."""
    s = _coerce_str(id_str)
    m = _ID_RE.match(s)
    if not m:
        return "", ""
    return m.group("num") or "", (m.group("sub") or "").lower()


def _extract_label_from_text(text: str) -> Tuple[str, str, str]:
    """
    Try to infer a leading label from the text line itself using LABEL_PATTERNS.
    Returns (full_label, main_num, sublabel). On failure: ("", "", "").
    """
    t0 = _coerce_str(text)
    for pat, kind, key in _LABEL_PATS:
        m = pat.search(t0)
        if m and m.groupdict().get("label_match"):
            label = _coerce_str(m.group("label_match"))
            value = _coerce_str(m.group(key))
            if kind == "num":
                return label, value, ""
            if kind == "alpha":
                return label, "", value.lower()
            if kind == "roman":
                return label, "", value.lower()
    return "", "", ""


def _normalize_item(item: dict) -> dict:
    """Ensure minimal fields exist."""
    return {
        "id": _coerce_str(item.get("id")),
        "content": _coerce_str(item.get("content")),
        "page": item.get("page"),
        "raw": item,
    }


def _group_by_main(items: List[dict]) -> Dict[str, List[dict]]:
    """
    Group items by main question number (as a string).
    - If an item id is "1a" -> main='1', sub='a'
    - If "2" -> main='2', sub=''
    - If no id, try to infer from leading content label; otherwise, bucket under "??"
    """
    groups: Dict[str, List[dict]] = {}

    for it in items or []:
        ni = _normalize_item(it)
        iid = ni["id"]
        content = ni["content"]

        main, sub = _split_id(iid)
        if not main:
            _full_lbl, inferred_main, inferred_sub = _extract_label_from_text(content)
            if inferred_main:
                main, sub = inferred_main, sub or inferred_sub
            else:
                main = "??"

        ni["__main_id"] = main
        ni["__sub_label"] = sub
        groups.setdefault(main, []).append(ni)

    for main in groups:
        groups[main].sort(key=lambda x: (x["__sub_label"], x.get("page") or 0, x["content"]))
    return groups


# ---------------------------
# Builder APIs
# ---------------------------

def make_main_question_structs(profile: dict) -> List[dict]:
    """
    Convert a 'questions' profile into a list of main-question structures with parts.
    """
    topic_id = _coerce_str(profile.get("topic_id"))
    topic_display = _coerce_str(profile.get("display_name") or topic_id.title())
    src = _coerce_str(profile.get("source_filename"))
    items = profile.get("items") or []

    if not items:
        logger.info("Questions-only: no items in profile '%s' — nothing to do.", topic_id)
        return []

    groups = _group_by_main(items)
    if not groups:
        logger.info("Questions-only: grouping produced no main questions for '%s'.", topic_id)
        return []

    main_structs: List[dict] = []
    for main_id, parts in groups.items():
        part_objs = []
        text_lines_for_ref = [f"Question {main_id}"]

        for p in parts:
            pid = p["id"] or f"{main_id}{p['__sub_label']}"
            label = p["__sub_label"] or ""

            label_prefix = f"({label}) " if label else ""
            text_lines_for_ref.append(f"{label_prefix}{p['content']}")

            part_objs.append({
                "id": pid,
                "label": label or None,
                "original_question": {
                    "id": pid,
                    "content": p["content"],
                    "source": {"filename": src, "page": p.get("page")},
                },
                "original_answer": {},  # no answers in questions-only flow
            })

        full_reference_text = "\n".join([t for t in text_lines_for_ref if t.strip()])
        main_structs.append({
            "topic_id": topic_id,
            "topic_display": topic_display,
            "question_number": main_id,
            "full_reference_text": full_reference_text,
            "parts": part_objs,
            "source_filename": src,
            "mode": "questions_only",
        })

    # Sort by numeric question_number when possible
    def _qkey(ms):
        qn = _coerce_str(ms.get("question_number"))
        try:
            return (0, int(qn))
        except Exception:
            return (1, qn)

    main_structs.sort(key=_qkey)
    logger.info("Questions-only: built %d main question structures for '%s'.", len(main_structs), topic_id)
    return main_structs


def build_questions_only_job(profile: dict) -> dict:
    """
    Wrap the per-main structures in a job dict.
    """
    topic_id = _coerce_str(profile.get("topic_id"))
    topic_display = _coerce_str(profile.get("display_name") or topic_id.title())
    main_structs = make_main_question_structs(profile)

    job = {
        "type": "questions_only",
        "topic_id": topic_id,
        "topic_display": topic_display,
        "questions_profile": {
            "source_filename": _coerce_str(profile.get("source_filename")),
            "doc_kind": _coerce_str(profile.get("doc_kind") or "questions"),
            "num_items": len(profile.get("items") or []),
        },
        "main_structs": main_structs,
        "stats": {"num_main": len(main_structs), "num_parts": sum(len(m["parts"]) for m in main_structs)},
    }
    logger.info(
        "Questions-only job built for '%s' — mains=%d, parts=%d",
        topic_id, job["stats"]["num_main"], job["stats"]["num_parts"]
    )
    return job


# ---------------------------
# Cache + Analyzer helpers
# ---------------------------

def _topic_id_from_filename(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    return base.strip().lower()


def _display_name_from_filename(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    return base.strip()


def _read_items_from_json(data) -> List[dict]:
    """Normalize common shapes into a flat [ {id, content, page?} ]."""
    items = []
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            items = data["items"]
        elif isinstance(data.get("extracted_items"), list):
            items = data["extracted_items"]
        elif isinstance(data.get("content"), list):
            items = data["content"]
        elif isinstance(data.get("pages"), list):
            flat = []
            for p in data["pages"]:
                if isinstance(p, dict) and isinstance(p.get("items"), list):
                    flat.extend(p["items"])
            items = flat
    elif isinstance(data, list):
        items = data
    return items or []


def _load_extracted_items_from_cache(pdf_basename_no_ext: str) -> Optional[List[dict]]:
    """
    Try to load items from processed_data/01_extracted_items/.
    We accept a variety of file name patterns to be repo-compatible.
    """
    cache_dir = os.path.join(settings.PROCESSED_DATA_DIR, settings.EXTRACTED_ITEMS_SUBDIR)
    if not os.path.isdir(cache_dir):
        return None

    candidates = [
        os.path.join(cache_dir, f"{pdf_basename_no_ext}.json"),
        os.path.join(cache_dir, f"{pdf_basename_no_ext}_items.json"),
        os.path.join(cache_dir, f"{pdf_basename_no_ext}_questions.json"),
        os.path.join(cache_dir, f"{pdf_basename_no_ext}_extracted.json"),
        os.path.join(cache_dir, f"{pdf_basename_no_ext}_profile.json"),
    ]
    wildcards = glob(os.path.join(cache_dir, f"{pdf_basename_no_ext}*.json"))
    for path in candidates + wildcards:
        if os.path.isfile(path):
            try:
                data = utils.load_json_file(path)
                items = _read_items_from_json(data)
                if isinstance(items, list) and items:
                    logger.info("Loaded %d cached items from %s", len(items), os.path.basename(path))
                    return items
            except Exception as e:
                logger.warning("Failed to read cached items %s — %s", path, e)
    return None


def _extract_questions_from_pdf(pdf_path: str) -> List[dict]:
    """
    Prefer cached items; otherwise try your analyzer using the functions
    actually present in your codebase.
    """
    base_no_ext = os.path.splitext(os.path.basename(pdf_path))[0]
    items = _load_extracted_items_from_cache(base_no_ext)

    if items is None and document_analyzer is not None:
        # First, try the all-in-one PDF analyzer your repo exposes.
        fn = getattr(document_analyzer, "process_pdf_with_ai_analyzer", None)
        if fn:
            try:
                data = fn(pdf_path)
                cand = _read_items_from_json(data)
                if cand:
                    items = cand
                    logger.info("Analyzer process_pdf_with_ai_analyzer returned %d items for %s", len(items), base_no_ext)
            except Exception as e:
                logger.error("Analyzer process_pdf_with_ai_analyzer failed for '%s' — %s", base_no_ext, e)

        # Fallback: render pages -> images and pass to the image analyzer
        if items is None:
            img_fn = getattr(document_analyzer, "process_images_with_ai_analyzer", None)
            cf = getattr(document_analyzer, "convert_from_path", None)
            if img_fn and cf:
                try:
                    dpi = getattr(settings, "PDF_RENDER_DPI", 200)
                    images = cf(pdf_path, dpi=dpi)
                    data = img_fn(images)
                    cand = _read_items_from_json(data)
                    if cand:
                        items = cand
                        logger.info("Analyzer process_images_with_ai_analyzer returned %d items for %s", len(items), base_no_ext)
                except Exception as e:
                    logger.error("Analyzer process_images_with_ai_analyzer failed for '%s' — %s", base_no_ext, e)

        if items is None:
            logger.info("No items from analyzer for %s.", base_no_ext)

    q_items = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        it_type = (it.get("type") or it.get("role") or "").lower()
        looks_like_question = bool(_coerce_str(it.get("id"))) and bool(_coerce_str(it.get("content")))
        if it_type == "question" or looks_like_question:
            q_items.append(it)

    logger.info("Found %d question items in %s", len(q_items), base_no_ext)
    return q_items


def _profile_from_pdf(pdf_path: str) -> dict:
    """Build a 'questions' profile dict from a single PDF path."""
    items = _extract_questions_from_pdf(pdf_path)
    return {
        "topic_id": _topic_id_from_filename(pdf_path),
        "display_name": _display_name_from_filename(pdf_path),
        "doc_kind": "questions",
        "source_filename": os.path.basename(pdf_path),
        "items": items,
    }


# ---------------------------
# Public runner
# ---------------------------

# def run_questions_only_batch(keep_structure: bool = False, cas_policy: str = "off"):
#     """
#     End-to-end runner for QUESTIONS-ONLY PDFs in input_pdfs/.
#       - Generates a new question per detected part (if keep_structure=True, uses near_copy style)
#       - CAS validate using answer_spec when available (cas_policy: off|prefer|require)
#       - Verify via AI examiner and upload to Firestore
#     """
#     logger.info("--- Questions-only runner (keep_structure=%s, CAS=%s) ---", keep_structure, cas_policy)

#     # Nudge in-memory settings for this run (no .env edits needed)
#     settings.GENERATION_STYLE = "near_copy" if keep_structure else "inspired"
#     settings.CAS_POLICY = cas_policy if cas_policy in {"off", "prefer", "require"} else "off"

#     # Init services
#     db_client = firebase_uploader.initialize_firebase()
#     gemini_content_model = content_creator.initialize_gemini_client()
#     gemini_checker_model = content_checker.initialize_gemini_client()
#     if not db_client or not gemini_content_model or not gemini_checker_model:
#         logger.error("Initialization failed (db/model). Aborting.")
#         return

#     # Find candidate PDFs (prefer names containing 'question')
#     pdf_dir = settings.INPUT_PDF_DIR
#     all_pdfs = sorted(glob(os.path.join(pdf_dir, "*.pdf")))
#     question_pdfs = [p for p in all_pdfs if re.search(r"question", os.path.basename(p), re.IGNORECASE)] or all_pdfs
#     if not question_pdfs:
#         logger.warning("No PDFs found in %s. Nothing to do.", pdf_dir)
#         return

#     collection_root = getattr(settings, "DEFAULT_COLLECTION_ROOT", "Topics")
#     totals = {"mains": 0, "parts": 0, "verified": 0, "rejected": 0, "uploaded": 0, "upload_failed": 0}

#     for pdf_path in question_pdfs:
#         profile = _profile_from_pdf(pdf_path)
#         job = build_questions_only_job(profile)
#         base_name = job["topic_id"]
#         main_structs = job["main_structs"]
#         totals["mains"] += len(main_structs)
#         totals["parts"] += sum(len(m["parts"]) for m in main_structs)

#         # Create/merge Topic doc metadata if using Topics root (keeps existing behavior)
#         if collection_root == "Topics":
#             firebase_uploader.create_or_update_topic(db_client, base_name)

#         for m in main_structs:
#             full_reference_text = m["full_reference_text"]
#             for target_pair in m["parts"]:
#                 qid = target_pair.get("id") or (target_pair.get("original_question", {}) or {}).get("id", "N/A")
#                 logger.info("%s | %s | Attempt 1/2", base_name, qid)

#                 new_question_object = None
#                 feedback_object = None
#                 correction_feedback = None
#                 cas_last_report = None

#                 for attempt in range(2):  # 1 try + 1 retry on feedback/CAS
#                     generated_object = content_creator.create_question(
#                         gemini_content_model,
#                         full_reference_text=full_reference_text,
#                         target_part_ref=target_pair,
#                         correction_feedback=correction_feedback,
#                     )
#                     if not generated_object:
#                         logger.error("%s | %s | Generation failed (attempt %d).", base_name, qid, attempt + 1)
#                         continue

#                     # Build/attach a CAS answer_spec if possible (from final_answer etc.)
#                     spec = checks_cas.build_answer_spec_from_generated(generated_object)
#                     if spec:
#                         generated_object["answer_spec"] = spec

#                     # CAS first (to avoid wasted checker calls)
#                     cas_ok = True
#                     if settings.CAS_POLICY != "off" and spec:
#                         try:
#                             cas_ok, cas_last_report = cas_validator.validate(generated_object)
#                         except Exception as e:
#                             cas_ok, cas_last_report = True, {"kind": "internal", "reason": f"CAS error: {e}"}
#                             logger.error("%s | %s | CAS internal error — %s", base_name, qid, e)

#                         if not cas_ok:
#                             reason = (cas_last_report or {}).get("details") or (cas_last_report or {}).get("reason") or "unknown"
#                             logger.debug("%s | %s | CAS rejected — %s", base_name, qid, utils.truncate(str(reason), 160))
#                             if settings.CAS_POLICY == "require":
#                                 correction_feedback = f"CAS validation failed: {reason}. Regenerate and fix while obeying all original rules."
#                                 continue  # retry once

#                     # AI examiner
#                     feedback_object = content_checker.verify_and_mark_question(
#                         gemini_checker_model,
#                         generated_object
#                     )

#                     if feedback_object and feedback_object.get("is_correct"):
#                         if settings.CAS_POLICY == "require" and not cas_ok:
#                             correction_feedback = f"CAS must pass; last failure: {(cas_last_report or {}).get('details')}"
#                         else:
#                             new_question_object = generated_object
#                             if settings.CAS_POLICY != "off":
#                                 new_question_object.setdefault("validation", {})
#                                 new_question_object["validation"]["cas_ok"] = bool(cas_ok)
#                                 new_question_object["validation"]["cas"] = cas_last_report
#                             logger.info("%s | %s | ✅ Verified (marks=%s, cas_ok=%s)", base_name, qid, feedback_object.get("marks", 0), cas_ok)
#                             break
#                     elif feedback_object:
#                         correction_feedback = feedback_object.get("feedback") or ""
#                         logger.debug("%s | %s | Rejected (attempt %d) — %s", base_name, qid, attempt + 1, utils.truncate(correction_feedback, 140))
#                     else:
#                         logger.error("%s | %s | Checker failed (attempt %d).", base_name, qid, attempt + 1)
#                         correction_feedback = "Checker did not return feedback. Regenerate from scratch."

#                 # Finalize
#                 if new_question_object:
#                     if new_question_object.get("visual_data") == {}:
#                         new_question_object.pop("visual_data", None)

#                     new_question_id = str(qid)
#                     new_question_object["topic"] = base_name
#                     new_question_object["question_number"] = new_question_id
#                     new_question_object["total_marks"] = (feedback_object or {}).get("marks", 0)

#                     os.makedirs("processed_data", exist_ok=True)
#                     utils.save_json_file(new_question_object, f"processed_data/{base_name}_Q{new_question_id}.json")

#                     stem_preview = (new_question_object.get("question_stem") or new_question_object.get("prompt") or "").replace("\n", " ")
#                     logger.info("%s | %s | Uploading — Marks=%s, Stem='%s...'", base_name, qid, new_question_object["total_marks"], stem_preview[:60])

#                     # collection_path = f"{settings.DEFAULT_COLLECTION_ROOT}/{base_name}/Questions"
#                     # ok = True
#                     # if not getattr(settings, "SKIP_UPLOAD", False):
#                     #     ok = firebase_uploader.upload_content(db_client, collection_path, new_question_id, new_question_object)

#                     # if ok:
#                     #     totals["uploaded"] += 1
#                     # else:
#                     #     totals["upload_failed"] += 1
#                     # totals["verified"] += 1
#                 else:
#                     totals["rejected"] += 1

#     logger.info(
#         "Questions-only runner DONE — mains=%d, parts=%d, verified=%d, rejected=%d, uploaded=%d, upload_failed=%d",
#         totals["mains"], totals["parts"], totals["verified"], totals["rejected"], totals["uploaded"], totals["upload_failed"]
#     )

# def parallel_create_question(params):
#     gemini_content_model, full_reference_text, target_pair, correction_feedback, keep_structure = params
#     return content_creator.create_question(
#         gemini_content_model,
#         full_reference_text=full_reference_text,
#         target_part_ref=target_pair,
#         correction_feedback=correction_feedback,
#         keep_structure=keep_structure,
#     )

# def parallel_verify_and_mark(params):
#     gemini_checker_model, generated_object = params
#     return content_checker.verify_and_mark_question(gemini_checker_model, generated_object)


# gen_tasks = []
# for m in main_structs:
#     for target_pair in m["parts"]:
#         gen_tasks.append((gemini_content_model, m["full_reference_text"], target_pair, None, keep_structure))

# # 1. Generate all questions in parallel
# with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
#     generated_results = list(executor.map(parallel_create_question, gen_tasks))

# # 2. Verify all questions in parallel
# verify_tasks = [
#     (gemini_checker_model, obj) for obj in generated_results if obj
# ]
# with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
#     checked_results = list(executor.map(parallel_verify_and_mark, verify_tasks))

# # ...save/upload as before...


class QuestionGenerationTask:
    """Tracks a question generation task with retry state."""
    def __init__(self, base_name: str, qid: str, full_reference_text: str, 
                 target_pair: dict, m_index: int, part_index: int):
        self.base_name = base_name
        self.qid = qid
        self.full_reference_text = full_reference_text
        self.target_pair = target_pair
        self.m_index = m_index
        self.part_index = part_index
        self.attempt = 0
        self.correction_feedback = None
        self.generated_object = None
        self.cas_last_report = None
        self.cas_ok = True
        self.is_complete = False


def parallel_create_question_worker(params: Tuple[Any, QuestionGenerationTask]) -> Optional[QuestionGenerationTask]:
    """
    Worker function for parallel question generation.
    Returns the task object with generated_object populated.
    """
    gemini_content_model, task = params
    
    task.attempt += 1
    logger.info("%s | %s | Attempt %d/2", task.base_name, task.qid, task.attempt)
    
    generated_object = content_creator.create_question(
        gemini_content_model,
        full_reference_text=task.full_reference_text,
        target_part_ref=task.target_pair,
        correction_feedback=task.correction_feedback,
    )
    
    if not generated_object:
        logger.error("%s | %s | Generation failed (attempt %d).", task.base_name, task.qid, task.attempt)
        return task
    
    # Build/attach a CAS answer_spec if possible
    spec = checks_cas.build_answer_spec_from_generated(generated_object)
    if spec:
        generated_object["answer_spec"] = spec
    
    task.generated_object = generated_object
    return task


def parallel_cas_validate_worker(task: QuestionGenerationTask) -> QuestionGenerationTask:
    """
    Worker function for CAS validation (can be run in parallel on generated objects).
    Returns the task with cas_ok and cas_last_report populated.
    """
    if settings.CAS_POLICY == "off" or not task.generated_object or not task.generated_object.get("answer_spec"):
        task.cas_ok = True
        task.cas_last_report = None
        return task
    
    try:
        cas_ok, cas_last_report = cas_validator.validate(task.generated_object)
        task.cas_ok = cas_ok
        task.cas_last_report = cas_last_report
    except Exception as e:
        task.cas_ok = True
        task.cas_last_report = {"kind": "internal", "reason": f"CAS error: {e}"}
        logger.error("%s | %s | CAS internal error — %s", task.base_name, task.qid, e)
    
    if not task.cas_ok:
        reason = (task.cas_last_report or {}).get("details") or (task.cas_last_report or {}).get("reason") or "unknown"
        logger.debug("%s | %s | CAS rejected — %s", task.base_name, task.qid, utils.truncate(str(reason), 160))
        
        if settings.CAS_POLICY == "require":
            task.correction_feedback = f"CAS validation failed: {reason}. Regenerate and fix while obeying all original rules."
    
    return task


def parallel_verify_and_mark_worker(params: Tuple[Any, QuestionGenerationTask]) -> Optional[QuestionGenerationTask]:
    """
    Worker function for parallel verification and marking.
    Returns the task object with feedback populated.
    """
    gemini_checker_model, task = params
    
    if not task.generated_object:
        logger.error("%s | %s | Skipping verification; no generated object.", task.base_name, task.qid)
        return task
    
    feedback_object = content_checker.verify_and_mark_question(
        gemini_checker_model,
        task.generated_object
    )
    
    task.feedback_object = feedback_object
    return task


def process_verification_result(task: QuestionGenerationTask, totals: Dict[str, int]) -> Optional[dict]:
    """
    Processes verification feedback and determines if task is complete.
    Returns the new_question_object if verified, or sets correction_feedback for retry.
    """
    feedback_object = getattr(task, 'feedback_object', None)
    
    if feedback_object and feedback_object.get("is_correct"):
        if settings.CAS_POLICY == "require" and not task.cas_ok:
            task.correction_feedback = f"CAS must pass; last failure: {(task.cas_last_report or {}).get('details')}"
            return None  # Will retry
        else:
            new_question_object = task.generated_object
            if settings.CAS_POLICY != "off":
                new_question_object.setdefault("validation", {})
                new_question_object["validation"]["cas_ok"] = bool(task.cas_ok)
                new_question_object["validation"]["cas"] = task.cas_last_report
            
            logger.info("%s | %s | ✅ Verified (marks=%s, cas_ok=%s)", 
                       task.base_name, task.qid, feedback_object.get("marks", 0), task.cas_ok)
            task.is_complete = True
            totals["verified"] += 1
            return new_question_object
    
    elif feedback_object:
        task.correction_feedback = feedback_object.get("feedback") or ""
        logger.debug("%s | %s | Rejected (attempt %d) — %s", task.base_name, task.qid, 
                    task.attempt, utils.truncate(task.correction_feedback, 140))
    else:
        logger.error("%s | %s | Checker failed (attempt %d).", task.base_name, task.qid, task.attempt)
        task.correction_feedback = "Checker did not return feedback. Regenerate from scratch."
    
    return None


# ============================================================================
# Main Parallel Batch Runner
# ============================================================================

def run_questions_only_batch(keep_structure: bool = False, cas_policy: str = "off"):
    """
    End-to-end runner for QUESTIONS-ONLY PDFs in input_pdfs/.
      - Generates a new question per detected part (if keep_structure=True, uses near_copy style)
      - CAS validate using answer_spec when available (cas_policy: off|prefer|require)
      - Verify via AI examiner and upload to Firestore
    
    NOW PARALLELIZED: Question generation, CAS validation, and verification run in parallel
    with intelligent retry handling for failed attempts.
    """
    logger.info("--- Questions-only runner (keep_structure=%s, CAS=%s) [PARALLEL] ---", keep_structure, cas_policy)

    # Nudge in-memory settings for this run (no .env edits needed)
    settings.GENERATION_STYLE = "near_copy" if keep_structure else "inspired"
    settings.CAS_POLICY = cas_policy if cas_policy in {"off", "prefer", "require"} else "off"

    # Init services
    db_client = firebase_uploader.initialize_firebase()
    gemini_content_model = content_creator.initialize_gemini_client()
    gemini_checker_model = content_checker.initialize_gemini_client()
    if not db_client or not gemini_content_model or not gemini_checker_model:
        logger.error("Initialization failed (db/model). Aborting.")
        return

    # Find candidate PDFs (prefer names containing 'question')
    pdf_dir = settings.INPUT_PDF_DIR
    all_pdfs = sorted(glob(os.path.join(pdf_dir, "*.pdf")))
    question_pdfs = [p for p in all_pdfs if re.search(r"question", os.path.basename(p), re.IGNORECASE)] or all_pdfs
    if not question_pdfs:
        logger.warning("No PDFs found in %s. Nothing to do.", pdf_dir)
        return

    collection_root = getattr(settings, "DEFAULT_COLLECTION_ROOT", "Topics")
    totals = {"mains": 0, "parts": 0, "verified": 0, "rejected": 0, "uploaded": 0, "upload_failed": 0}

    for pdf_path in question_pdfs:
        profile = _profile_from_pdf(pdf_path)
        job = build_questions_only_job(profile)
        base_name = job["topic_id"]
        main_structs = job["main_structs"]
        totals["mains"] += len(main_structs)
        totals["parts"] += sum(len(m["parts"]) for m in main_structs)

        # Create/merge Topic doc metadata if using Topics root (keeps existing behavior)
        if collection_root == "Topics":
            firebase_uploader.create_or_update_topic(db_client, base_name)

        # ====================================================================
        # Phase 1: Build task queue for all question parts
        # ====================================================================
        initial_tasks = []
        m_part_mapping = {}  # Map task index to (m_index, part_index) for result tracking
        
        for m_index, m in enumerate(main_structs):
            full_reference_text = m["full_reference_text"]
            for part_index, target_pair in enumerate(m["parts"]):
                qid = target_pair.get("id") or (target_pair.get("original_question", {}) or {}).get("id", "N/A")
                task = QuestionGenerationTask(
                    base_name=base_name,
                    qid=qid,
                    full_reference_text=full_reference_text,
                    target_pair=target_pair,
                    m_index=m_index,
                    part_index=part_index,
                )
                task_idx = len(initial_tasks)
                m_part_mapping[task_idx] = (m_index, part_index)
                initial_tasks.append(task)

        # ====================================================================
        # Phase 2: Attempt 1 - Generate all questions in parallel
        # ====================================================================
        gen_tasks_attempt_1 = [(gemini_content_model, task) for task in initial_tasks]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            gen_results_1 = list(executor.map(parallel_create_question_worker, gen_tasks_attempt_1))
        
        # ====================================================================
        # Phase 3: CAS validation in parallel (only for tasks with generated_object)
        # ====================================================================
        if settings.CAS_POLICY != "off":
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                gen_results_1 = list(executor.map(parallel_cas_validate_worker, gen_results_1))
        
        # ====================================================================
        # Phase 4: Verify all generated questions in parallel
        # ====================================================================
        verify_tasks_1 = [(gemini_checker_model, task) for task in gen_results_1 if task.generated_object]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            verified_results_1 = list(executor.map(parallel_verify_and_mark_worker, verify_tasks_1))
        
        # Map verification results back to original tasks
        verify_idx = 0
        for i, task in enumerate(gen_results_1):
            if task.generated_object:
                task.feedback_object = verified_results_1[verify_idx].feedback_object if verify_idx < len(verified_results_1) else None
                verify_idx += 1
        
        # ====================================================================
        # Phase 5: Check results and identify tasks needing retry
        # ====================================================================
        retry_tasks = []
        
        for task in gen_results_1:
            if task.is_complete or task.attempt >= 2:
                # Already complete or max attempts reached
                continue
            
            # Check if needs retry (failed generation, failed CAS, or failed verification)
            if not task.generated_object or task.correction_feedback:
                if task.attempt < 2:
                    retry_tasks.append(task)
        
        # ====================================================================
        # Phase 6: Attempt 2 - Retry failed questions in parallel
        # ====================================================================
        if retry_tasks:
            logger.info("%s | Retrying %d failed tasks (attempt 2/2)...", base_name, len(retry_tasks))
            
            gen_tasks_attempt_2 = [(gemini_content_model, task) for task in retry_tasks]
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                gen_results_2 = list(executor.map(parallel_create_question_worker, gen_tasks_attempt_2))
            
            # CAS validation for retry results
            if settings.CAS_POLICY != "off":
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                    gen_results_2 = list(executor.map(parallel_cas_validate_worker, gen_results_2))
            
            # Verify retry results in parallel
            verify_tasks_2 = [(gemini_checker_model, task) for task in gen_results_2 if task.generated_object]
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                verified_results_2 = list(executor.map(parallel_verify_and_mark_worker, verify_tasks_2))
            
            # Map verification results back
            verify_idx = 0
            for task in gen_results_2:
                if task.generated_object:
                    task.feedback_object = verified_results_2[verify_idx].feedback_object if verify_idx < len(verified_results_2) else None
                    verify_idx += 1
        
        # ====================================================================
        # Phase 7: Process all results and finalize
        # ====================================================================
        all_final_tasks = gen_results_1 + (gen_results_2 if retry_tasks else [])
        
        for task in all_final_tasks:
            new_question_object = process_verification_result(task, totals)
            
            if new_question_object:
                # Finalize and save
                if new_question_object.get("visual_data") == {}:
                    new_question_object.pop("visual_data", None)

                new_question_id = str(task.qid)
                new_question_object["topic"] = base_name
                new_question_object["question_number"] = new_question_id
                
                feedback_object = getattr(task, 'feedback_object', {}) or {}
                new_question_object["total_marks"] = feedback_object.get("marks", 0)

                os.makedirs("processed_data", exist_ok=True)
                utils.save_json_file(new_question_object, f"processed_data/{base_name}_Q{new_question_id}.json")

                stem_preview = (new_question_object.get("question_stem") or new_question_object.get("prompt") or "").replace("\n", " ")
                logger.info("%s | %s | Uploading — Marks=%s, Stem='%s...'", base_name, task.qid, 
                           new_question_object["total_marks"], stem_preview[:60])

                # Uncomment when ready to upload:
                collection_path = f"{collection_root}/{base_name}/Questions"
                if not getattr(settings, "SKIP_UPLOAD", False):
                    ok = firebase_uploader.upload_content(db_client, collection_path, new_question_id, new_question_object)
                    if ok:
                        totals["uploaded"] += 1
                    else:
                        totals["upload_failed"] += 1
            else:
                totals["rejected"] += 1

    logger.info(
        "Questions-only runner DONE [PARALLEL] — mains=%d, parts=%d, verified=%d, rejected=%d, uploaded=%d, upload_failed=%d",
        totals["mains"], totals["parts"], totals["verified"], totals["rejected"], totals["uploaded"], totals["upload_failed"]
    )