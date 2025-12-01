import os
import re
import json
from typing import Optional, Dict, Any

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from config import settings
from . import utils

logger = utils.setup_logger(__name__)

XP_TABLE = {
    1: 35, 2: 45, 3: 60, 4: 75, 5: 95, 6: 115, 7: 140, 8: 165,
}

def marks_to_difficulty(marks) -> int:
    try:
        m = int(marks or 0)
    except Exception:
        m = 0
    if m <= 2: return 1
    if m == 3: return 2
    if m == 4: return 3
    if m == 5: return 4
    if m == 6: return 5
    if m == 7: return 6
    if m == 8: return 7
    return 8

def initialize_firebase():
    if not firebase_admin._apps:
        try:
            json_str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
            if json_str:
                try:
                    sa_dict = json.loads(json_str)
                except Exception as e:
                    logger.error("Firebase: FIREBASE_SERVICE_ACCOUNT_JSON invalid — %s", e)
                    return None
                cred = credentials.Certificate(sa_dict)
                logger.info("Firebase: initialized from ENV JSON.")
            else:
                cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_KEY_PATH)
                logger.info("Firebase: initialized from file '%s'.", settings.FIREBASE_SERVICE_ACCOUNT_KEY_PATH)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            logger.error("Firebase init failed — %s", e)
            return None
    try:
        return firestore.client()
    except Exception as e:
        logger.error("Firebase client error — %s", e)
        return None

def _db_or_raise():
    db = initialize_firebase()
    if not db:
        raise RuntimeError("Firestore client not available.")
    return db


def _sanitize_visual_data_for_firestore(vd: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize visual_data so that any table-like structures are stored as
    simple dicts/lists with string keys, which Firestore is happy with.
    """
    try:
        vd = json.loads(json.dumps(vd))
    except Exception:
        vd = dict(vd)

    charts = vd.get("charts") or vd.get("graphs")
    if isinstance(charts, list):
        for ch in charts:
            if isinstance(ch, dict) and ch.get("type") == "table":
                vf = ch.get("visual_features") or {}
                headers = vf.get("headers") or []
                rows = vf.get("rows") or []
                new_rows = []
                if isinstance(rows, list):
                    for r in rows:
                        if isinstance(r, dict):
                            new_rows.append({str(k): str(v) for k, v in r.items()})
                        elif isinstance(r, (list, tuple)) and headers and len(r) == len(headers):
                            row_map = {str(headers[i]): str(r[i]) for i in range(len(headers))}
                            new_rows.append(row_map)
                        else:
                            vals = r if isinstance(r, (list, tuple)) else [r]
                            row_map = {str(i): str(v) for i, v in enumerate(vals)}
                            new_rows.append(row_map)
                vf["rows"] = new_rows
                ch["visual_features"] = vf
    return vd


# -----------------------------
# Upload progress/event tracker
# -----------------------------
class UploadTracker:
    """
    Centralizes all Firestore writes for a single upload.

    Parent doc:  Users/{uid}/Uploads/{upload_id}
      status:        "processing" | "complete" | "error"
      startedAt:     timestamp
      created_at:    timestamp (alias)
      updated_at:    timestamp
      completed_at:  timestamp (when complete/error)
      last_message:  short human text (e.g. "Created Q 3c")
      questionCount: int (live, incremented as questions are written)
      resultUnitId:  string (id of the resulting Unit; synonyms also written)
      unitId/unit_id: synonyms set on completion for legacy clients

    Subcollection:  .../events/{autoId}
      type, message, ts, and any extras (e.g. questionId)
    """

    def __init__(self, uid: str, upload_id: str, *, db_client: Optional[firestore.Client] = None):
        self.uid = uid
        self.upload_id = upload_id
        self.db: firestore.Client = db_client or _db_or_raise()
        self.ref = (
            self.db.collection("Users")
                   .document(uid)
                   .collection("Uploads")
                   .document(upload_id)
        )

    # ----- Lifecycle writes -----

    def start(
        self,
        *,
        folder_id: Optional[str] = None,
        unit_name: Optional[str] = None,
        section: Optional[str] = None
    ) -> None:
        """
        Create/merge the parent doc in a consistent 'processing' shape.

        IMPORTANT:
        - If this upload already exists, we DO NOT reset questionCount to 0.
          That way appending new questions keeps the old count and can
          increment from there.
        """
        try:
            try:
                snap = self.ref.get()
                existing = snap.to_dict() if snap.exists else {}
            except Exception as e:
                logger.warning(
                    "UploadTracker[%s/%s] start: could not read existing doc — %s",
                    self.uid, self.upload_id, e
                )
                snap = None
                existing = {}

            existing_qc = None
            if isinstance(existing, dict):
                qc = existing.get("questionCount")
                if isinstance(qc, int):
                    existing_qc = qc

            data: Dict[str, Any] = {
                "status": "processing",
                "folderId": folder_id or existing.get("folderId") or None,
                "unitName": unit_name or existing.get("unitName") or "Upload",
                "section": section or existing.get("section") or "General",
                "last_message": "Starting…",
                "updated_at": firestore.SERVER_TIMESTAMP,
                "pipeline_ver": 1,
            }

            # Only initialise questionCount for brand-new uploads
            if existing_qc is None:
                data["questionCount"] = 0

            # Initialise timestamps only if missing (for existing uploads we keep them)
            if not existing.get("created_at"):
                data["created_at"] = firestore.SERVER_TIMESTAMP
            if not existing.get("startedAt"):
                data["startedAt"] = firestore.SERVER_TIMESTAMP

            self.ref.set(data, merge=True)
            logger.info(
                "UploadTracker[%s/%s] start (exists=%s, existing_qc=%s)",
                self.uid,
                self.upload_id,
                bool(existing),
                existing_qc,
            )
        except Exception as e:
            logger.error("UploadTracker start failed: %s", e)

    def heartbeat(self, *, message: Optional[str] = None) -> None:
        """Optional: keep 'updated_at' fresh with a short message."""
        try:
            patch: Dict[str, Any] = {"updated_at": firestore.SERVER_TIMESTAMP}
            if message:
                patch["last_message"] = message
            self.ref.set(patch, merge=True)
        except Exception as e:
            logger.debug("UploadTracker heartbeat failed: %s", e)

    def complete(self, *, result_unit_id: str, question_count: Optional[int] = None) -> None:
        """Mark as complete. Write redundant fields for robust UI filtering."""
        try:
            patch: Dict[str, Any] = {
                "status": "complete",
                "resultUnitId": result_unit_id,
                "unitId": result_unit_id,    # legacy/synonym
                "unit_id": result_unit_id,   # legacy/synonym
                "last_message": "Done",
                "completed_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
            if isinstance(question_count, int):
                patch["questionCount"] = question_count
            self.ref.set(patch, merge=True)
            logger.info(
                "UploadTracker[%s/%s] complete (unit %s, question_count=%s)",
                self.uid, self.upload_id, result_unit_id, question_count
            )
        except Exception as e:
            logger.error("UploadTracker complete failed: %s", e)

    def error(self, message: str) -> None:
        """Mark as error. UI should hide or show as error depending on view."""
        try:
            self.ref.set(
                {
                    "status": "error",
                    "error_message": message[:500],
                    "last_message": message[:120] or "Error",
                    "completed_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            logger.warning(
                "UploadTracker[%s/%s] error: %s",
                self.uid, self.upload_id, message
            )
        except Exception as e:
            logger.error("UploadTracker error write failed: %s", e)

    # ----- Progress events -----

    def event(
        self,
        *,
        type: str,
        message: str,
        inc_question: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append an event and update parent last_message / questionCount."""
        try:
            batch = self.db.batch()

            ev = {"type": type, "message": message, "ts": firestore.SERVER_TIMESTAMP}
            if extra:
                ev.update(extra)

            ev_ref = self.ref.collection("events").document()
            batch.set(ev_ref, ev)

            updates: Dict[str, Any] = {
                "last_message": message,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
            if inc_question:
                updates["questionCount"] = firestore.Increment(1)

            batch.update(self.ref, updates)
            batch.commit()
        except Exception as e:
            logger.error("UploadTracker event failed: %s", e)

    # Convenience wrappers

    def event_question_created(
        self, *, label: str, index: Optional[int] = None, question_id: Optional[str] = None
    ) -> None:
        extra: Dict[str, Any] = {}
        if index is not None:
            extra["index"] = index
        if question_id is not None:
            extra["questionId"] = question_id
        self.event(
            type="questionCreated",
            message=f"Created Q {label}",
            inc_question=True,
            extra=extra
        )

    def event_note(self, msg: str) -> None:
        self.event(type="note", message=msg)


# -----------------------------
# Existing content helpers
# -----------------------------

def upload_content(db_client, collection_path, document_id, data):
    """
    Write a question/lesson doc to Firestore.

    FIXED (Dec 1 2025):
    - For user uploads (`Users/{uid}/Uploads/{uploadId}/Questions`),
      we now ALWAYS use the PROVIDED `document_id`
      instead of generating auto-IDs.

      This ensures questionId == Firestore docId,
      which the iOS app requires.
    """
    if not db_client:
        logger.error("Firebase: client not available; cannot upload '%s/%s'.", collection_path, document_id)
        return False

    try:
        is_user_upload = collection_path.startswith("Users/")

        # -------------------------------
        # FIXED BEHAVIOUR FOR USER UPLOADS
        # -------------------------------
        if is_user_upload:
            # Use EXACT document_id passed in: e.g. "2", "1a", "3c", "2mcq"
            doc_ref = db_client.collection(collection_path).document(document_id)
            exists_snapshot = None
            logger.debug(
                "Firebase: user-upload path '%s' — using FIXED doc id '%s'.",
                collection_path,
                document_id,
            )

        else:
            # Non-user uploads keep the existing behaviour
            doc_ref = db_client.collection(collection_path).document(document_id)
            mode = getattr(settings, "WRITE_MODE", "preserve").strip().lower()
            exists_snapshot = None

            if mode == "preserve":
                try:
                    exists_snapshot = doc_ref.get()
                    if exists_snapshot.exists:
                        logger.info(
                            "Firebase: preserve mode; skip '%s/%s'.",
                            collection_path,
                            document_id,
                        )
                        return True
                except Exception as e:
                    logger.warning(
                        "Firebase: existence check failed for '%s/%s' (%s) — continuing.",
                        collection_path,
                        document_id,
                        e,
                    )

        payload = dict(data)

        def _as_int(v, default=0):
            try:
                return int(v)
            except Exception:
                return default

        def _clamp(v, lo, hi):
            try:
                vi = int(v)
            except Exception:
                vi = lo
            return max(lo, min(hi, vi))

        if "total_marks" in payload:
            payload["total_marks"] = _as_int(payload.get("total_marks"), 0)

        if "difficulty" not in payload or not isinstance(payload["difficulty"], int):
            payload["difficulty"] = marks_to_difficulty(payload.get("total_marks", 0))
        else:
            payload["difficulty"] = _clamp(payload["difficulty"], 1, 8)

        if "xp_base" not in payload or not isinstance(payload["xp_base"], int):
            diff = _as_int(payload.get("difficulty"), 1)
            payload["xp_base"] = XP_TABLE.get(diff, XP_TABLE[1])

        if "xp_curve_version" not in payload:
            payload["xp_curve_version"] = 1

        if exists_snapshot is not None and not exists_snapshot.exists:
            payload.setdefault("created_at", firestore.SERVER_TIMESTAMP)
            payload.setdefault("startedAt", firestore.SERVER_TIMESTAMP)

        payload["updated_at"] = firestore.SERVER_TIMESTAMP

        if "visual_data" in payload and isinstance(payload["visual_data"], dict):
            payload["visual_data"] = _sanitize_visual_data_for_firestore(payload["visual_data"])

        doc_ref.set(payload, merge=True)

        logger.debug(
            "Firebase: uploaded '%s' → '%s' (doc_id=%s, is_user_upload=%s).",
            document_id,
            collection_path,
            doc_ref.id,
            is_user_upload,
        )

        return True

    except Exception as e:
        logger.error("Firebase: upload failed for '%s/%s' — %s", collection_path, document_id, e)
        return False

def create_or_update_topic(db_client, topic_id):
    if not db_client:
        logger.error("Firebase: client not available; cannot ensure topic '%s'.", topic_id)
        return False

    metadata = settings.TOPIC_METADATA.get(topic_id)
    if not metadata:
        base = re.sub(r'[_\-]+', ' ', topic_id).strip()
        base = re.sub(r'\s+', ' ', base)
        default_title = base.title()
        metadata = {"topicName": default_title, "section": "A"}
        logger.debug("Firebase: no metadata for '%s'. Defaults %s", topic_id, metadata)

    try:
        doc_ref = db_client.collection("Topics").document(topic_id)
        metadata["updated_at"] = firestore.SERVER_TIMESTAMP
        try:
            snap = doc_ref.get()
            if not snap.exists:
                metadata.setdefault("created_at", firestore.SERVER_TIMESTAMP)
        except Exception:
            pass
        doc_ref.set(metadata, merge=True)
        logger.info("Firebase: topic ensured '%s'.", topic_id)
        return True
    except Exception as e:
        logger.error("Firebase: failed to ensure topic '%s' — %s", topic_id, e)
        return False