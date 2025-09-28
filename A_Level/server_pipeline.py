# A_Level/server_pipeline.py
import os
import io
import re
import tempfile
from typing import List, Tuple, Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from PIL import Image

# Firebase admin (for ID token verification)
from firebase_admin import auth as firebase_auth
from firebase_admin import firestore as admin_fs  # for SERVER_TIMESTAMP, Increment

# Local imports (A_Level project)
from pipeline_scripts import document_analyzer, content_creator, content_checker, firebase_uploader, utils
from pipeline_scripts.main_pipeline import group_paired_items  # reuse grouping
from config import settings

app = FastAPI(title="Alma Pipeline Server", version="1.4")

# ---- tunables / limits ----
MAX_FILES = int(os.getenv("UPLOAD_MAX_FILES", "12"))
MAX_TOTAL_BYTES = int(os.getenv("UPLOAD_MAX_TOTAL_BYTES", str(25 * 1024 * 1024)))  # 25 MB default


# ---- helpers ----

def _ensure_firebase_initialized():
    _ = firebase_uploader.initialize_firebase()

def _bearer_token_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    x = request.headers.get("X-ID-Token")
    return x.strip() if x else None

def _require_uid_from_request(request: Request) -> str:
    _ensure_firebase_initialized()
    token = _bearer_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer token.")
    try:
        decoded = firebase_auth.verify_id_token(token)
        uid = decoded.get("uid")
        if not uid:
            raise ValueError("token_has_no_uid")
        return uid
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid ID token: {e}")

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
            tmp.write(data); tmp.flush(); tmp.close()
            pdf_paths.append(tmp.name)
        else:
            try:
                pil = Image.open(io.BytesIO(data)).convert("RGB")
                pil_images.append(pil)
            except Exception:
                pass
    return pdf_paths, pil_images, total_bytes

def _build_pseudo_pairs_from_questions(q_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pseudo = []
    for q in q_items or []:
        qid = (q.get("id") or "").strip()
        if not qid:
            continue
        pseudo.append({
            "question_id": qid,
            "original_question": q,
            "original_answer": {}
        })
    return pseudo

def _update_parent_status(db_client, uid: str, upload_id: str,
                          status: Optional[str] = None,
                          message: Optional[str] = None,
                          inc_count: int = 0,
                          set_count: Optional[int] = None,
                          done: bool = False) -> None:
    """
    Merge-update the parent Upload doc with status/progress. Safe to call frequently.
    """
    payload: Dict[str, Any] = {"updated_at": admin_fs.SERVER_TIMESTAMP}
    if status is not None:
        payload["status"] = status
    if message is not None:
        payload["statusMessage"] = message
    if set_count is not None:
        payload["questionCount"] = int(set_count)
    elif inc_count:
        payload["questionCount"] = admin_fs.Increment(int(inc_count))
    if done:
        payload["completed_at"] = admin_fs.SERVER_TIMESTAMP
    firebase_uploader.upload_content(
        db_client, f"Users/{uid}/Uploads", upload_id, payload
    )


def _process_questions_only_job(
    *,
    uid: str,
    upload_id: str,
    items: List[Dict[str, Any]],
    keep_structure: bool = False,
    cas_policy: str = "off",
) -> Dict[str, Any]:
    """
    Generate and upload questions for a single questions-only 'job'.
    Writes to: Users/{uid}/Uploads/{upload_id}/Questions/{questionId}
    Also streams progress to the parent Upload doc.
    """
    db_client = firebase_uploader.initialize_firebase()
    gemini_content_model = content_creator.initialize_gemini_client()
    gemini_checker_model = content_checker.initialize_gemini_client()
    if not db_client or not gemini_content_model or not gemini_checker_model:
        raise HTTPException(status_code=500, detail="Initialization failed (db/model).")

    paired_refs = _build_pseudo_pairs_from_questions(items)
    hierarchical_groups = group_paired_items(paired_refs)

    run = utils.start_run_report()
    run["totals"]["jobs"] = 1
    job_summary = utils.new_job_summary(upload_id, "questions_only")
    run["jobs"].append(job_summary)
    job_summary["groups"] = len(hierarchical_groups)
    run["totals"]["groups"] += len(hierarchical_groups)

    # parent collection path
    collection_base = f"Users/{uid}/Uploads/{upload_id}/Questions"

    created_docs: List[Dict[str, Any]] = []
    total_parts = sum(
        1 + len(g.get("sub_question_pairs") or [])
        for g in hierarchical_groups
    )

    # Announce start
    _update_parent_status(db_client, uid, upload_id,
                          status="processing",
                          message=f"Creating {total_parts} questions…",
                          set_count=0)

    processed_parts = 0

    for group in hierarchical_groups:
        all_pairs = [group.get("main_pair", {})] + (group.get("sub_question_pairs") or [])
        full_reference_text = "\n".join(
            f"Part ({p.get('question_id') or (p.get('original_question', {}) or {}).get('id', '')}): "
            f"{((p.get('original_question', {}) or {}).get('content') or '').strip()}"
            for p in all_pairs if p
        )

        for target_pair in all_pairs:
            qid = target_pair.get("question_id") or (target_pair.get("original_question", {}) or {}).get("id", "N/A")
            q_text = ((target_pair.get("original_question", {}) or {}).get("content") or "").strip()
            if not q_text:
                continue

            job_summary["parts_processed"] += 1
            run["totals"]["parts_processed"] += 1

            new_question_object = None
            feedback_object = None
            correction_feedback = None

            # Generate + verify (up to 2 tries)
            for attempt in range(2):
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
                    gemini_checker_model, generated_object
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
                processed_parts += 1
                _update_parent_status(db_client, uid, upload_id,
                                      message=f"Q{qid} rejected; continuing…")
                continue

            # Prepare payload fields
            if new_question_object.get("visual_data") == {}:
                new_question_object.pop("visual_data", None)
            new_question_id = str(qid)
            new_question_object["topic"] = upload_id
            new_question_object["question_number"] = new_question_id
            new_question_object["total_marks"] = (feedback_object or {}).get("marks", 0)

            # Save locally for audit
            os.makedirs(settings.PROCESSED_DATA_DIR, exist_ok=True)
            utils.save_json_file(new_question_object,
                                 os.path.join(settings.PROCESSED_DATA_DIR, f"{upload_id}_Q{new_question_id}.json"))

            # Upload to Firestore (subcollection)
            path = f"{collection_base}"
            ok = firebase_uploader.upload_content(db_client, path, new_question_id, new_question_object)
            if ok:
                job_summary["uploaded_ok"] += 1
                run["totals"]["uploaded_ok"] += 1
                job_summary["verified"] += 1
                run["totals"]["verified"] += 1
                created_docs.append({"id": new_question_id, "path": f"{path}/{new_question_id}"})
                # progress ping to parent
                _update_parent_status(db_client, uid, upload_id,
                                      message=f"Q{new_question_id} created",
                                      inc_count=1)
            else:
                job_summary["upload_failed"] += 1
                run["totals"]["upload_failed"] += 1
                _update_parent_status(db_client, uid, upload_id,
                                      message=f"Q{new_question_id} upload failed")

            processed_parts += 1

    utils.save_run_report(run)
    # Finalize parent doc with exact count and completed_at
    _update_parent_status(db_client, uid, upload_id,
                          status="complete",
                          message="Done",
                          set_count=len(created_docs),
                          done=True)

    return {"summary": run, "created": created_docs}


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

    try:
        items: List[Dict[str, Any]] = []
        for p in pdf_paths:
            items.extend(document_analyzer.process_pdf_with_ai_analyzer(p))

        pil_images: List[Image.Image] = []
        for p in image_paths:
            try:
                pil_images.append(Image.open(p).convert("RGB"))
            except Exception:
                pass

        if not items and pil_images:
            items.extend(document_analyzer.process_images_with_ai_analyzer(pil_images))

        if not items:
            firebase_uploader.upload_content(db_client, f"Users/{uid}/Uploads", upload_id, {
                "status": "error",
                "statusMessage": "No items detected",
                "questionCount": 0,
            })
            return

        # Stream questions and progress
        result = _process_questions_only_job(
            uid=uid,
            upload_id=upload_id,
            items=items,
            keep_structure=False,
            cas_policy="off",
        )

        # Ensure parent finalized (redundant but safe)
        created_count = len(result.get("created") or [])
        firebase_uploader.upload_content(db_client, f"Users/{uid}/Uploads", upload_id, {
            "status": "complete",
            "statusMessage": "Done",
            "questionCount": created_count,
            "completed_at": admin_fs.SERVER_TIMESTAMP,
        })

    except Exception as e:
        firebase_uploader.upload_content(db_client, f"Users/{uid}/Uploads", upload_id, {
            "status": "error",
            "statusMessage": f"Server error: {str(e)[:120]}",
        })
        raise e
    finally:
        for p in pdf_paths + image_paths:
            try:
                os.unlink(p)
            except Exception:
                pass


# ---- API ----

@app.get("/health")
def health():
    try:
        _ensure_firebase_initialized()
        return {"ok": True, "service": "pipeline", "version": app.version}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/user-uploads/process")
def process_user_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    upload_id: Optional[str] = Form(None),
    unit_name: Optional[str] = Form(None),
    section: Optional[str] = Form(None),
    folder_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"Too many files (>{MAX_FILES}).")

    uid = _require_uid_from_request(request)

    pdf_paths, pil_images, total_bytes = _read_images_from_uploads(files)
    if total_bytes == 0:
        raise HTTPException(status_code=400, detail="Uploaded files are empty or unsupported.")
    if total_bytes > MAX_TOTAL_BYTES:
        for p in pdf_paths:
            try: os.unlink(p)
            except Exception: pass
        raise HTTPException(status_code=413, detail=f"Total upload too large (> {MAX_TOTAL_BYTES // (1024*1024)} MB).")

    # Persist in-memory images to temp files for background task
    image_paths: List[str] = []
    for idx, pil in enumerate(pil_images):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        pil.save(tmp.name, "JPEG", quality=90)
        tmp.flush(); tmp.close()
        image_paths.append(tmp.name)

    raw_upload_id = upload_id or utils.make_timestamp()
    upload_id = _sanitize_doc_id(raw_upload_id)

    # Create/ensure parent Upload with 'processing'
    db_client = firebase_uploader.initialize_firebase()
    parent_path = f"Users/{uid}/Uploads"
    parent_doc = {
        "unitName": (unit_name or "My Upload").strip(),
        "section": (section or "General").strip(),
        "folderId": (folder_id or "").strip(),
        "status": "processing",
        "statusMessage": "Starting…",
        "questionCount": 0,
        "created_at": admin_fs.SERVER_TIMESTAMP,
        "updated_at": admin_fs.SERVER_TIMESTAMP,
    }
    _ = firebase_uploader.upload_content(db_client, parent_path, upload_id, parent_doc)

    background_tasks.add_task(
        _run_pipeline_background,
        uid=uid,
        upload_id=upload_id,
        unit_name=parent_doc["unitName"],
        section=parent_doc["section"],
        folder_id=parent_doc["folderId"],
        pdf_paths=pdf_paths,
        image_paths=image_paths,
    )

    return JSONResponse({"created": []}, status_code=202)