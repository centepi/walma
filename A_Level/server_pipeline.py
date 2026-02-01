# A_Level/server_pipeline.py
import os
import io
import re
import tempfile
import time
import uuid
import threading
import traceback
from typing import List, Tuple, Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from PIL import Image

from firebase_admin import auth as firebase_auth
from firebase_admin import firestore

from pipeline_scripts import document_analyzer, content_creator, content_checker, firebase_uploader, utils
from pipeline_scripts import entitlements
from pipeline_scripts.main_pipeline import (
    group_paired_items,
    _build_parent_context_lookup,
    _compose_group_context_text,
    _main_numeric_id,
    _has_child_id
)
from pipeline_scripts.firebase_uploader import UploadTracker
from config import settings

from pipeline_scripts.text_gen_pipeline import drill_runner
from pipeline_scripts.routers.entitlements_router import router as entitlements_router

logger = utils.setup_logger(__name__)

app = FastAPI(title="Alma Pipeline Server", version="1.5.0")
app.include_router(entitlements_router)

MAX_FILES = int(os.getenv("UPLOAD_MAX_FILES", "12"))
MAX_TOTAL_BYTES = int(os.getenv("UPLOAD_MAX_TOTAL_BYTES", str(25 * 1024 * 1024)))

ALMA_ROLE = (os.getenv("ALMA_ROLE", "both") or "both").strip().lower()
ALMA_QUEUE_ENABLED = (os.getenv("ALMA_QUEUE_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"})

JOB_POLL_SECONDS = float(os.getenv("ALMA_JOB_POLL_SECONDS", "1.5"))
JOB_CLAIM_BATCH = int(os.getenv("ALMA_JOB_CLAIM_BATCH", "1"))

JOB_COLLECTION = os.getenv("ALMA_JOB_COLLECTION", "PipelineJobs")
WORKER_ID = os.getenv("ALMA_WORKER_ID", f"worker-{uuid.uuid4().hex[:8]}")


def _ensure_firebase_initialized():
    _ = firebase_uploader.initialize_firebase()


def _bearer_token_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    x = request.headers.get("X-ID-Token")
    return x.strip() if x else None


def _provider_key_from_decoded(decoded: Dict[str, Any], uid: str) -> str:
    try:
        fb = decoded.get("firebase") or {}
        identities = fb.get("identities") or {}

        apple_ids = identities.get("apple.com") or identities.get("apple") or []
        if isinstance(apple_ids, list) and apple_ids:
            return f"apple:{str(apple_ids[0])}"

        google_ids = identities.get("google.com") or identities.get("google") or []
        if isinstance(google_ids, list) and google_ids:
            return f"google:{str(google_ids[0])}"

        email = decoded.get("email")
        if isinstance(email, str) and email.strip():
            return f"email:{email.strip().lower()}"
    except Exception:
        pass

    return f"uid:{uid}"


def _require_auth_context_from_request(request: Request) -> Tuple[str, str]:
    _ensure_firebase_initialized()
    token = _bearer_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer token.")
    try:
        decoded = firebase_auth.verify_id_token(token)
        uid = decoded.get("uid")
        if not uid:
            raise ValueError("token_has_no_uid")
        provider_key = _provider_key_from_decoded(decoded, str(uid))
        return str(uid), provider_key
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid ID token: {e}")


def _storekit_jws_from_request(request: Request) -> str:
    v = request.headers.get("X-StoreKit-Transaction", "") or request.headers.get("X-StoreKit-JWS", "")
    return v.strip()


def _sanitize_doc_id(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("/", "-")
    s = re.sub(r"[^\w\-.]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "upload"


def _read_images_from_uploads(files: List[UploadFile]) -> Tuple[List[str], List[Image.Image], int]:
    pdf_paths: List[str] = []
    pil_images: List[Image.Image] = []
    total_bytes = 0

    for f in files:
        fname = (f.filename or "").lower()
        data = f.file.read()
        if not data:
            continue
        total_bytes += len(data)

        if fname.endswith(".pdf"):
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp.write(data)
            tmp.flush()
            tmp.close()
            pdf_paths.append(tmp.name)
        else:
            try:
                pil = Image.open(io.BytesIO(data)).convert("RGB")
                pil_images.append(pil)
            except Exception as e:
                logger.warning("Skipping non-image file '%s': %s", fname, e)
                pass

    return pdf_paths, pil_images, total_bytes


def _db():
    db_client = firebase_uploader.initialize_firebase()
    if not db_client:
        raise RuntimeError("Firestore client not available.")
    return db_client


def _jobs_col(db_client):
    return db_client.collection(JOB_COLLECTION)


def _enqueue_job(
    *,
    uid: str,
    upload_id: str,
    job_type: str,
    payload: Dict[str, Any],
) -> str:
    db_client = _db()
    job_id = uuid.uuid4().hex
    doc = {
        "type": job_type,
        "uid": uid,
        "upload_id": upload_id,
        "status": "queued",
        "worker_id": None,
        "error": None,
        "payload": payload or {},
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    _jobs_col(db_client).document(job_id).set(doc, merge=True)
    logger.info("Enqueued job %s (type=%s, uid=%s, upload=%s)", job_id, job_type, uid, upload_id)
    return job_id


def _claim_one_job(db_client) -> Optional[Tuple[str, Dict[str, Any]]]:
    try:
        q = (
            _jobs_col(db_client)
            .where("status", "==", "queued")
            .limit(max(1, int(JOB_CLAIM_BATCH)))
        )
        docs = list(q.stream())
        if not docs:
            return None

        for d in docs:
            job_id = d.id
            ref = _jobs_col(db_client).document(job_id)

            @firestore.transactional
            def txn_fn(txn):
                snap = ref.get(transaction=txn)
                data = snap.to_dict() if snap.exists else {}
                if (data or {}).get("status") != "queued":
                    return None
                txn.update(ref, {
                    "status": "processing",
                    "worker_id": WORKER_ID,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                })
                return data

            txn = db_client.transaction()
            claimed = txn_fn(txn)
            if claimed:
                return job_id, claimed

        return None
    except Exception as e:
        logger.error("Job claim failed: %s", e)
        return None


def _finish_job(db_client, job_id: str, *, ok: bool, error: Optional[str] = None) -> None:
    try:
        patch = {
            "status": "done" if ok else "error",
            "error": (error or None),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        _jobs_col(db_client).document(job_id).set(patch, merge=True)
    except Exception as e:
        logger.error("Failed to finish job %s: %s", job_id, e)


def _run_job_payload(job_id: str, job_doc: Dict[str, Any]) -> None:
    db_client = _db()
    job_type = (job_doc.get("type") or "").strip().lower()
    uid = (job_doc.get("uid") or "").strip()
    upload_id = (job_doc.get("upload_id") or "").strip()
    payload = job_doc.get("payload") or {}

    if not uid or not upload_id or job_type not in {"files", "text"}:
        _finish_job(db_client, job_id, ok=False, error="invalid_job_doc")
        return

    try:
        if job_type == "text":
            drill_runner.run_text_drill_background(
                uid=uid,
                upload_id=upload_id,
                topic=str(payload.get("topic") or ""),
                course=str(payload.get("course") or ""),
                difficulty=str(payload.get("difficulty") or ""),
                quantity=int(payload.get("quantity") or 3),
                additional_details=str(payload.get("additional_details") or ""),
                folder_id=str(payload.get("folder_id") or ""),
                unit_name=str(payload.get("unit_name") or ""),
            )
            _finish_job(db_client, job_id, ok=True)
            return

        pdf_paths = list(payload.get("pdf_paths") or [])
        image_paths = list(payload.get("image_paths") or [])
        unit_name = str(payload.get("unit_name") or "My Upload")
        section = str(payload.get("section") or "General")
        folder_id = str(payload.get("folder_id") or "")

        _run_pipeline_background(
            uid=uid,
            upload_id=upload_id,
            unit_name=unit_name,
            section=section,
            folder_id=folder_id,
            pdf_paths=pdf_paths,
            image_paths=image_paths,
        )
        _finish_job(db_client, job_id, ok=True)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Job %s failed: %s\n%s", job_id, e, tb)
        _finish_job(db_client, job_id, ok=False, error=str(e)[:400])


def _worker_loop_forever() -> None:
    logger.info("Worker loop starting (id=%s, collection=%s, poll=%.2fs)", WORKER_ID, JOB_COLLECTION, JOB_POLL_SECONDS)
    db_client = _db()

    while True:
        try:
            claimed = _claim_one_job(db_client)
            if not claimed:
                time.sleep(JOB_POLL_SECONDS)
                continue

            job_id, job_doc = claimed
            logger.info("Worker claimed job %s (type=%s)", job_id, job_doc.get("type"))
            _run_job_payload(job_id, job_doc)
        except Exception as e:
            logger.error("Worker loop error: %s", e)
            time.sleep(max(0.5, JOB_POLL_SECONDS))


def _start_worker_if_needed() -> None:
    if not ALMA_QUEUE_ENABLED:
        logger.info("Queue disabled (ALMA_QUEUE_ENABLED=0); worker will not start.")
        return
    if ALMA_ROLE not in {"worker", "both"}:
        logger.info("Role=%s; worker will not start.", ALMA_ROLE)
        return
    t = threading.Thread(target=_worker_loop_forever, name="alma-worker", daemon=True)
    t.start()


t = None


@app.on_event("startup")
def _on_startup():
    try:
        _ensure_firebase_initialized()
    except Exception:
        pass
    try:
        if ALMA_QUEUE_ENABLED and ALMA_ROLE in {"worker", "both"}:
            th = threading.Thread(target=_worker_loop_forever, name="alma-worker", daemon=True)
            th.start()
            logger.info("Worker thread started (id=%s).", WORKER_ID)
    except Exception as e:
        logger.error("Failed to start worker thread: %s", e)


def _build_pseudo_pairs_from_questions(q_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ids = {(q.get("id") or "").strip() for q in (q_items or []) if (q.get("id") or "").strip()}
    pseudo: List[Dict[str, Any]] = []
    skipped = 0
    for q in q_items or []:
        qid = (q.get("id") or "").strip()
        if not qid:
            continue
        if _has_child_id(qid, ids):
            skipped += 1
            continue
        pseudo.append({
            "question_id": qid,
            "original_question": q,
            "original_answer": {}
        })
    if skipped:
        logger.info("Server: leaf-only pseudo-pairs built: kept=%d, skipped_parents=%d", len(pseudo), skipped)
    return pseudo


def _collapse_group_to_mcq(
    group: Dict[str, Any],
    id_to_q: Dict[str, Dict[str, Any]],
    parent_text_by_main: Dict[str, str]
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    main_qid = (group.get("main_pair") or {}).get("question_id") or ""
    main_id = _main_numeric_id(main_qid)
    if not main_id:
        return False, None, None

    leaves: List[Dict[str, Any]] = [group.get("main_pair", {})] + (group.get("sub_question_pairs") or [])
    candidates: List[Tuple[str, Dict[str, Any]]] = []
    for p in leaves:
        pid = (p.get("question_id") or (p.get("original_question", {}) or {}).get("id", "")).strip()
        if not pid.startswith(main_id):
            continue
        suffix = pid[len(main_id):]
        if re.fullmatch(r"[a-zA-Z]$", suffix or ""):
            candidates.append((suffix.lower(), p))

    if not (3 <= len(candidates) <= 6):
        return False, None, None

    candidates.sort(key=lambda t: t[0])

    options_lines: List[str] = []
    for idx, (_letter, p) in enumerate(candidates):
        text = ((p.get("original_question", {}) or {}).get("content") or "").strip()
        if not text:
            return False, None, None
        label = chr(ord('A') + idx)
        options_lines.append(f"{label}) {text}")

    stem_text = (parent_text_by_main.get(main_id) or "").strip()
    header = "Multiple-choice item. Choose the single best answer."
    if stem_text:
        mcq_ref = f"Stem ({main_id}): {stem_text}\nOptions:\n" + "\n".join(options_lines)
        combined_content = f"{header}\n\n{stem_text}\n\nOptions:\n" + "\n".join(options_lines)
    else:
        mcq_ref = "Options:\n" + "\n".join(options_lines)
        combined_content = f"{header}\n\nOptions:\n" + "\n".join(options_lines)

    synthetic_id = f"{main_id}mcq"
    synthetic_pair = {
        "question_id": synthetic_id,
        "synthetic_mcq": True,
        "original_question": {
            "id": synthetic_id,
            "content": combined_content
        },
        "original_answer": {}
    }
    return True, synthetic_pair, mcq_ref


def _process_questions_only_job(
    *,
    uid: str,
    upload_id: str,
    items: List[Dict[str, Any]],
    keep_structure: bool = False,
    cas_policy: str = "off",
    tracker: Optional[UploadTracker] = None,
) -> Dict[str, Any]:
    db_client = firebase_uploader.initialize_firebase()
    gemini_content_model = content_creator.initialize_gemini_client()
    gemini_checker_model = content_checker.initialize_gemini_client()
    if not db_client or not gemini_content_model or not gemini_checker_model:
        raise HTTPException(status_code=500, detail="Initialization failed (db/model).")

    id_to_q, parent_text_by_main, parent_all_levels_by_main = _build_parent_context_lookup(items or [])
    paired_refs = _build_pseudo_pairs_from_questions(items)
    hierarchical_groups = group_paired_items(paired_refs)

    run = utils.start_run_report()
    run["totals"]["jobs"] = 1
    job_summary = utils.new_job_summary(upload_id, "questions_only")
    run["jobs"].append(job_summary)
    job_summary["groups"] = len(hierarchical_groups)
    run["totals"]["groups"] += len(hierarchical_groups)

    collection_base = f"Users/{uid}/Uploads/{upload_id}/Questions"
    created_docs: List[Dict[str, Any]] = []

    for group in hierarchical_groups:
        main_qid = (group.get("main_pair") or {}).get("question_id") or \
                   ((group.get("main_pair") or {}).get("original_question") or {}).get("id", "")
        main_id = _main_numeric_id(main_qid)

        is_mcq, synthetic_pair, mcq_ref = _collapse_group_to_mcq(group, id_to_q, parent_text_by_main)
        if is_mcq and synthetic_pair:
            all_pairs = [synthetic_pair]
            full_reference_text = mcq_ref or ""
        else:
            all_pairs = [group.get("main_pair", {})] + (group.get("sub_question_pairs") or [])
            full_reference_text = _compose_group_context_text(
                main_id,
                all_pairs,
                id_to_q,
                parent_text_by_main,
                parent_all_levels_by_main
            )

        for target_pair in all_pairs:
            try:
                qid = target_pair.get("question_id") or (target_pair.get("original_question", {}) or {}).get("id", "N/A")
                q_text = ((target_pair.get("original_question", {}) or {}).get("content") or "").strip()
                if not q_text:
                    continue

                if _has_child_id(str(qid), set(id_to_q.keys())) and not target_pair.get("synthetic_mcq"):
                    logger.debug("Server: skipping parent/context id '%s' at generation step.", qid)
                    continue

                if tracker:
                    tracker.event_note(f"Generating Q {qid}")

                job_summary["parts_processed"] += 1
                run["totals"]["parts_processed"] += 1

                new_question_object = None
                feedback_object = None
                correction_feedback = None

                for _attempt in range(2):
                    generated_object = content_creator.create_question(
                        gemini_content_model,
                        full_reference_text,
                        target_pair,
                        correction_feedback=correction_feedback,
                        keep_structure=keep_structure,
                    )
                    if not generated_object:
                        correction_feedback = "Generation failed, try again."
                        continue

                    feedback_object = content_checker.verify_and_mark_question(
                        gemini_checker_model,
                        generated_object
                    )
                    if feedback_object and feedback_object.get("is_correct"):
                        new_question_object = generated_object
                        break
                    else:
                        correction_feedback = (feedback_object or {}).get("feedback") or "Invalid; regenerate."

                if not new_question_object:
                    job_summary["rejected"] += 1
                    run["totals"]["rejected"] += 1
                    if correction_feedback:
                        utils.append_failure(job_summary, str(qid), correction_feedback)
                    if tracker:
                        tracker.event(type="reject", message=f"Rejected Q {qid}")
                    continue

                if new_question_object.get("visual_data") == {}:
                    new_question_object.pop("visual_data", None)

                new_question_id = str(qid)
                new_question_object["topic"] = upload_id
                new_question_object["question_number"] = new_question_id
                new_question_object["total_marks"] = (feedback_object or {}).get("marks", 0)

                os.makedirs(settings.PROCESSED_DATA_DIR, exist_ok=True)
                utils.save_json_file(
                    new_question_object,
                    os.path.join(settings.PROCESSED_DATA_DIR, f"{upload_id}_Q{new_question_id}.json")
                )

                path = f"{collection_base}"
                ok = firebase_uploader.upload_content(
                    db_client, path, new_question_id, new_question_object
                )
                if ok:
                    job_summary["uploaded_ok"] += 1
                    run["totals"]["uploaded_ok"] += 1
                    job_summary["verified"] += 1
                    run["totals"]["verified"] += 1
                    created_docs.append({
                        "id": new_question_id,
                        "path": f"{path}/{new_question_id}"
                    })
                    if tracker:
                        tracker.event_question_created(label=new_question_id, index=None, question_id=new_question_id)
                else:
                    job_summary["upload_failed"] += 1
                    run["totals"]["upload_failed"] += 1
                    if tracker:
                        tracker.event(type="error", message=f"Upload failed for Q {new_question_id}")
            except Exception as e:
                logger.exception("Unexpected error in part loop (Q=%s): %s", target_pair.get("question_id"), e)
                if tracker:
                    tracker.event(type="error", message=f"Crash in Q {target_pair.get('question_id')}: {str(e)[:80]}")

    utils.save_run_report(run)
    return {
        "summary": run,
        "created": created_docs
    }


def _run_pipeline_background(
    *,
    uid: str,
    upload_id: str,
    unit_name: str,
    section: str,
    folder_id: str,
    pdf_paths: List[str],
    image_paths: List[str],
):
    db_client = firebase_uploader.initialize_firebase()
    tracker = UploadTracker(uid, upload_id)

    try:
        tracker.event_note("Analyzing input…")

        items: List[Dict[str, Any]] = []
        for p in pdf_paths:
            items.extend(document_analyzer.process_pdf_with_ai_analyzer(p))

        pil_images: List[Image.Image] = []
        for p in image_paths:
            try:
                pil_images.append(Image.open(p).convert("RGB"))
            except Exception as e:
                logger.warning("Skipping unreadable image '%s': %s", p, e)

        if not items and pil_images:
            items.extend(document_analyzer.process_images_with_ai_analyzer(pil_images))

        if not items:
            tracker.error("No questions detected.")
            firebase_uploader.upload_content(db_client, f"Users/{uid}/Uploads", upload_id, {
                "status": "error",
                "questionCount": 0,
            })
            return

        tracker.event(type="parse", message=f"Found {len(items)} items to process")

        result = _process_questions_only_job(
            uid=uid,
            upload_id=upload_id,
            items=items,
            keep_structure=False,
            cas_policy="off",
            tracker=tracker,
        )

        _created_count = len(result.get("created") or [])
        tracker.complete(result_unit_id=upload_id)

        firebase_uploader.upload_content(
            db_client,
            f"Users/{uid}/Uploads",
            upload_id,
            {
                "status": "complete",
            }
        )

        logger.info(
            "Background job complete for uid=%s upload=%s (created %d questions)",
            uid,
            upload_id,
            _created_count,
        )

    except Exception as e:
        logger.exception("Background job failed for uid=%s upload=%s: %s", uid, upload_id, e)
        try:
            tracker.error(str(e)[:120])
            firebase_uploader.upload_content(db_client, f"Users/{uid}/Uploads", upload_id, {
                "status": "error",
            })
        except Exception as inner:
            logger.exception("Failed to write error status for upload=%s: %s", upload_id, inner)
    finally:
        for p in pdf_paths + image_paths:
            try:
                os.unlink(p)
            except Exception:
                pass


@app.get("/health")
def health():
    try:
        _ensure_firebase_initialized()
        return {
            "ok": True,
            "service": "pipeline",
            "version": app.version,
            "role": ALMA_ROLE,
            "queue_enabled": bool(ALMA_QUEUE_ENABLED),
            "worker_id": WORKER_ID if ALMA_ROLE in {"worker", "both"} else None,
            "job_collection": JOB_COLLECTION if ALMA_QUEUE_ENABLED else None,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/user-uploads/process")
def process_user_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    upload_id: Optional[str] = Form(None, description="Client-side upload id; defaults to timestamp"),
    unit_name: Optional[str] = Form(None, description="User-friendly unit name"),
    section: Optional[str] = Form(None, description="Section label (UI divider)"),
    folder_id: Optional[str] = Form(None, description="Target folder/course id for this upload"),
    files: List[UploadFile] = File(..., description="One or more PDFs/images of the user's homework"),
):
    if ALMA_ROLE not in {"api", "both"}:
        raise HTTPException(status_code=503, detail="Service is running in WORKER-only mode.")

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"Too many files (>{MAX_FILES}).")

    uid, _provider_key = _require_auth_context_from_request(request)

    pdf_paths, pil_images, total_bytes = _read_images_from_uploads(files)
    if total_bytes == 0:
        raise HTTPException(status_code=400, detail="Uploaded files are empty or unsupported.")
    if total_bytes > MAX_TOTAL_BYTES:
        for p in pdf_paths:
            try:
                os.unlink(p)
            except Exception:
                pass
        raise HTTPException(status_code=413, detail=f"Total upload too large (> {MAX_TOTAL_BYTES // (1024*1024)} MB).")

    image_paths: List[str] = []
    for _, pil in enumerate(pil_images):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        pil.save(tmp.name, "JPEG", quality=90)
        tmp.flush()
        tmp.close()
        image_paths.append(tmp.name)

    raw_upload_id = upload_id or utils.make_timestamp()
    upload_id = _sanitize_doc_id(raw_upload_id)

    tracker = UploadTracker(uid, upload_id)
    tracker.start(
        folder_id=(folder_id or "").strip(),
        unit_name=(unit_name or "My Upload").strip(),
        section=(section or "General").strip()
    )
    tracker.event_note("Queued")

    if ALMA_QUEUE_ENABLED:
        _enqueue_job(
            uid=uid,
            upload_id=upload_id,
            job_type="files",
            payload={
                "pdf_paths": pdf_paths,
                "image_paths": image_paths,
                "unit_name": (unit_name or "My Upload").strip(),
                "section": (section or "General").strip(),
                "folder_id": (folder_id or "").strip(),
            },
        )
        return JSONResponse({"created": [], "status": "queued", "upload_id": upload_id}, status_code=202)

    background_tasks.add_task(
        _run_pipeline_background,
        uid=uid,
        upload_id=upload_id,
        unit_name=(unit_name or "My Upload").strip(),
        section=(section or "General").strip(),
        folder_id=(folder_id or "").strip(),
        pdf_paths=pdf_paths,
        image_paths=image_paths,
    )
    return JSONResponse({"created": []}, status_code=202)


@app.post("/api/user-uploads/process-text")
def process_text_drill(
    request: Request,
    background_tasks: BackgroundTasks,
    topic: str = Form(..., description="Topic of the questions"),
    course: str = Form(..., description="Target course (A-Level, GCSE, etc)"),
    difficulty: str = Form(..., description="Difficulty level description"),
    count: int = Form(3, description="Number of questions to generate"),
    additional_details: str = Form("", description="Extra instructions"),

    upload_id: Optional[str] = Form(None, description="Client-side upload id"),
    folder_id: Optional[str] = Form(None, description="Target folder id (snake_case)"),
    folderId: Optional[str] = Form(None, description="Target folder id (camelCase)"),
    unit_name: Optional[str] = Form(None, description="Unit name (snake_case)"),
    unitName: Optional[str] = Form(None, description="Unit name (camelCase)"),
    section: Optional[str] = Form(None, description="Section (snake_case)"),
    sectionName: Optional[str] = Form(None, description="Section (camelCase)"),
):
    if ALMA_ROLE not in {"api", "both"}:
        raise HTTPException(status_code=503, detail="Service is running in WORKER-only mode.")

    uid, provider_key = _require_auth_context_from_request(request)

    try:
        requested = int(count or 0)
    except Exception:
        requested = 0
    if requested < 1:
        raise HTTPException(status_code=400, detail="Count must be at least 1.")
    if requested > 10:
        raise HTTPException(status_code=400, detail="Max 10 questions per batch.")
    effective_count = requested

    effective_folder_id = (folder_id or folderId or "").strip()
    effective_unit_name = (unit_name or unitName or f"{topic} Drill").strip()
    effective_section = (section or sectionName or "General").strip()

    raw_upload_id = upload_id or utils.make_timestamp()
    upload_id = _sanitize_doc_id(raw_upload_id)

    db_client = firebase_uploader.initialize_firebase()
    if not db_client:
        raise HTTPException(status_code=500, detail="Firestore client not available.")

    storekit_jws = _storekit_jws_from_request(request)

    snapshot_info: Optional[Dict[str, Any]] = None
    if storekit_jws:
        try:
            snapshot_info = entitlements.get_effective_entitlements_snapshot(
                db_client,
                uid=provider_key,
                storekit_jws=storekit_jws,
                default_free_cap=30,
            )
        except Exception as e:
            logger.warning("[process-text] entitlements snapshot failed: %s", e)

    # If subscribed (either via verified StoreKit proof, or already persisted ledger state),
    # do NOT consume quota.
    if snapshot_info and bool(snapshot_info.get("is_subscribed")):
        ok, info = True, snapshot_info
    else:
        ok, info = entitlements.try_consume_question_credit(
            db_client,
            uid=provider_key,
            n=effective_count,
            default_free_cap=30,
        )

    logger.info(
        "[process-text] ok=%s is_subscribed=%s storekit_verified=%s key_type=%s key=%s cap=%s used=%s remaining=%s",
        ok,
        info.get("is_subscribed"),
        info.get("storekit_verified"),
        info.get("key_type"),
        (info.get("key") or "")[:12],
        info.get("cap"),
        info.get("used"),
        info.get("remaining"),
    )

    if not ok:
        return JSONResponse(
            {
                "status": "quota_exceeded",
                "message": f"You’ve used all free questions (cap {info.get('cap')}). Subscribe to continue.",
                "entitlements": info,
            },
            status_code=402,
        )

    tracker = UploadTracker(uid, upload_id)
    tracker.start(
        folder_id=effective_folder_id,
        unit_name=effective_unit_name,
        section=effective_section
    )
    tracker.event_note("Queued Drill...")

    if ALMA_QUEUE_ENABLED:
        _enqueue_job(
            uid=uid,
            upload_id=upload_id,
            job_type="text",
            payload={
                "topic": topic,
                "course": course,
                "difficulty": difficulty,
                "quantity": int(effective_count),
                "additional_details": additional_details or "",
                "folder_id": effective_folder_id,
                "unit_name": effective_unit_name,
                "section": effective_section,
            },
        )
        return JSONResponse({"status": "queued", "upload_id": upload_id}, status_code=202)

    background_tasks.add_task(
        drill_runner.run_text_drill_background,
        uid=uid,
        upload_id=upload_id,
        topic=topic,
        course=course,
        difficulty=difficulty,
        quantity=effective_count,
        additional_details=additional_details,
        folder_id=effective_folder_id,
        unit_name=effective_unit_name
    )
    return JSONResponse({"status": "queued", "upload_id": upload_id}, status_code=202)