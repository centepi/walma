# server_pipeline.py
import os
import io
import re
import tempfile
from typing import List, Tuple, Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from PIL import Image

# Firebase admin (for ID token verification)
from firebase_admin import auth as firebase_auth

# Local imports (A_Level project)
from pipeline_scripts import document_analyzer, content_creator, content_checker, firebase_uploader, utils
from pipeline_scripts.main_pipeline import group_paired_items  # reuse grouping
from config import settings

app = FastAPI(title="Alma Pipeline Server", version="1.1")

# ---- tunables / limits ----
MAX_FILES = int(os.getenv("UPLOAD_MAX_FILES", "12"))
MAX_TOTAL_BYTES = int(os.getenv("UPLOAD_MAX_TOTAL_BYTES", str(25 * 1024 * 1024)))  # 25 MB default


# ---- helpers ----

def _ensure_firebase_initialized():
    """Initialize Firebase Admin once (via uploader helper)."""
    _ = firebase_uploader.initialize_firebase()


def _bearer_token_from_request(request: Request) -> Optional[str]:
    """Extract Bearer token from Authorization or X-ID-Token header."""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    # Fallback for easier client testing
    x = request.headers.get("X-ID-Token")
    return x.strip() if x else None


def _require_uid_from_request(request: Request) -> str:
    """Verify Firebase ID token and return uid (401 on failure)."""
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


def _read_images_from_uploads(files: List[UploadFile]) -> Tuple[List[str], List[Image.Image], int]:
    """
    Split uploads into PDF filepaths and PIL images (opened in-memory).
    Returns (pdf_paths, pil_images, total_bytes).
    """
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
            # pdf2image needs a filesystem path — write to a temp file
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp.write(data)
            tmp.flush()
            tmp.close()
            pdf_paths.append(tmp.name)
        else:
            # Attempt to open as an image (PNG/JPG/HEIC, etc.)
            try:
                pil = Image.open(io.BytesIO(data)).convert("RGB")
                pil_images.append(pil)
            except Exception:
                # Ignore non-image non-pdf files silently
                pass
    return pdf_paths, pil_images, total_bytes


def _build_pseudo_pairs_from_questions(q_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Local, minimal version of main_pipeline's pseudo-pairs."""
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


def _extract_main_id(qid: str) -> str:
    m = re.match(r"(\d+)", str(qid or ""))
    return m.group(1) if m else str(qid or "")


def _process_questions_only_job(
    *,
    uid: str,
    upload_id: str,
    items: List[Dict[str, Any]],
    keep_structure: bool = False,
    cas_policy: str = "off",
) -> Dict[str, Any]:
    """
    Generate and upload questions for a single questions-only 'job', returning a run summary.
    Writes to: Users/{uid}/Uploads/{upload_id}/Questions/{questionId}
    """
    # Init clients/models
    db_client = firebase_uploader.initialize_firebase()
    gemini_content_model = content_creator.initialize_gemini_client()
    gemini_checker_model = content_checker.initialize_gemini_client()
    if not db_client or not gemini_content_model or not gemini_checker_model:
        raise HTTPException(status_code=500, detail="Initialization failed (db/model).")

    # Build pairs and groups (context = by main question number)
    paired_refs = _build_pseudo_pairs_from_questions(items)
    hierarchical_groups = group_paired_items(paired_refs)

    # Prepare run summary
    run = utils.start_run_report()
    run["totals"]["jobs"] = 1
    job_summary = utils.new_job_summary(upload_id, "questions_only")
    run["jobs"].append(job_summary)
    job_summary["groups"] = len(hierarchical_groups)
    run["totals"]["groups"] += len(hierarchical_groups)

    # Collection path for this user's upload
    collection_base = f"Users/{uid}/Uploads/{upload_id}/Questions"

    created_docs: List[Dict[str, Any]] = []

    # Process each part in each group
    for group in hierarchical_groups:
        all_pairs = [group.get("main_pair", {})] + group.get("sub_question_pairs", [])
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

            for attempt in range(2):
                generated_object = content_creator.create_question(
                    gemini_content_model,
                    full_reference_text,
                    target_pair,
                    correction_feedback=correction_feedback,
                    keep_structure=keep_structure,  # always False for MVP
                )
                if not generated_object:
                    correction_feedback = "Generation failed, try again."
                    continue

                # Run checker (CAS off for MVP)
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
                continue

            # Clean and prepare payload fields consistent with app
            if new_question_object.get("visual_data") == {}:
                new_question_object.pop("visual_data", None)

            new_question_id = str(qid)
            new_question_object["topic"] = upload_id                   # user-scoped logical topic = upload id
            new_question_object["question_number"] = new_question_id
            new_question_object["total_marks"] = (feedback_object or {}).get("marks", 0)

            # Save locally for audit
            os.makedirs(settings.PROCESSED_DATA_DIR, exist_ok=True)
            utils.save_json_file(new_question_object, os.path.join(settings.PROCESSED_DATA_DIR, f"{upload_id}_Q{new_question_id}.json"))

            # Upload to user-scoped collection
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
            else:
                job_summary["upload_failed"] += 1
                run["totals"]["upload_failed"] += 1

    utils.save_run_report(run)
    return {
        "summary": run,
        "created": created_docs
    }


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
    upload_id: Optional[str] = Form(None, description="Client-side upload id; defaults to timestamp"),
    unit_name: Optional[str] = Form(None, description="User-friendly unit name"),
    section: Optional[str] = Form(None, description="Section/folder name"),
    files: List[UploadFile] = File(..., description="One or more PDFs/images of the user's homework"),
):
    """
    Accept PDFs/images, extract items, generate practice questions,
    and upload into Users/{uid}/Uploads/{uploadId}/Questions.
    Parent doc: Users/{uid}/Uploads/{uploadId} with status tracking.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"Too many files (>{MAX_FILES}).")

    # ---- Auth: require valid Firebase ID token
    uid = _require_uid_from_request(request)

    # ---- Read uploads + size guard
    pdf_paths, pil_images, total_bytes = _read_images_from_uploads(files)
    if total_bytes == 0:
        raise HTTPException(status_code=400, detail="Uploaded files are empty or unsupported.")
    if total_bytes > MAX_TOTAL_BYTES:
        # Cleanup tmp PDFs
        for p in pdf_paths:
            try:
                os.unlink(p)
            except Exception:
                pass
        raise HTTPException(status_code=413, detail=f"Total upload too large (> {MAX_TOTAL_BYTES // (1024*1024)} MB).")

    # ---- Default upload_id if not provided
    upload_id = upload_id or utils.make_timestamp()

    # ---- Ensure parent Upload doc exists with 'processing' status
    db_client = firebase_uploader.initialize_firebase()
    parent_path = f"Users/{uid}/Uploads"
    parent_doc = {
        "unitName": (unit_name or "My Upload").strip(),
        "section": (section or "General").strip(),
        "status": "processing",
        "questionCount": 0,
    }
    _ = firebase_uploader.upload_content(db_client, parent_path, upload_id, parent_doc)

    try:
        # ---- Extract items (prefer PDFs if present; otherwise images)
        items: List[Dict[str, Any]] = []
        for p in pdf_paths:
            items.extend(document_analyzer.process_pdf_with_ai_analyzer(p))
        if not items and pil_images:
            items.extend(document_analyzer.process_images_with_ai_analyzer(pil_images))

        # Cleanup tmp PDFs ASAP
        for p in pdf_paths:
            try:
                os.unlink(p)
            except Exception:
                pass

        if not items:
            raise HTTPException(status_code=422, detail="Could not extract any items from uploaded files.")

        # ---- Run streamlined questions-only job
        result = _process_questions_only_job(
            uid=uid,
            upload_id=upload_id,
            items=items,
            keep_structure=False,   # MVP
            cas_policy="off",       # MVP
        )

        # ---- Finalize parent doc
        created_count = len(result.get("created") or [])
        finalize = {
            "status": "complete",
            "questionCount": created_count,
        }
        _ = firebase_uploader.upload_content(db_client, parent_path, upload_id, finalize)
        return JSONResponse(result)

    except HTTPException:
        # Propagate after marking error
        _ = firebase_uploader.upload_content(db_client, parent_path, upload_id, {"status": "error"})
        raise
    except Exception as e:
        _ = firebase_uploader.upload_content(db_client, parent_path, upload_id, {"status": "error"})
        raise HTTPException(status_code=500, detail=f"Pipeline error: {e}")