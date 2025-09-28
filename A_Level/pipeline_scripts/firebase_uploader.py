import os
import re
import json
from typing import Optional, Dict, Any

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from config import settings
from . import utils

# Unified logger (inherits global levels from utils/setup)
logger = utils.setup_logger(__name__)

# ---- XP mapping helpers (ensure XP fields on upload) ----

# Flatter XP curve (difficulty 1 → 8)
XP_TABLE = {
    1: 35,
    2: 45,
    3: 60,
    4: 75,
    5: 95,
    6: 115,
    7: 140,
    8: 165,
}

def marks_to_difficulty(marks) -> int:
    """Map total_marks → difficulty band (1..8)."""
    try:
        m = int(marks or 0)
    except Exception:
        m = 0
    if m <= 2:  # 0..2 marks
        return 1
    if m == 3:
        return 2
    if m == 4:
        return 3
    if m == 5:
        return 4
    if m == 6:
        return 5
    if m == 7:
        return 6
    if m == 8:
        return 7
    return 8  # 9+ marks


def initialize_firebase():
    """
    Initializes the Firebase Admin SDK.

    Priority:
      1) FIREBASE_SERVICE_ACCOUNT_JSON (env var with full JSON)
      2) settings.FIREBASE_SERVICE_ACCOUNT_KEY_PATH (file on disk)

    Returns a Firestore client object if successful, otherwise None.
    """
    if not firebase_admin._apps:
        try:
            json_str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
            if json_str:
                try:
                    sa_dict = json.loads(json_str)
                except Exception as e:
                    logger.error("Firebase: FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON — %s", e)
                    return None
                cred = credentials.Certificate(sa_dict)
                logger.info("Firebase: initializing with service account from ENV.")
            else:
                cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_KEY_PATH)
                logger.info("Firebase: initializing with service account file at '%s'.",
                            settings.FIREBASE_SERVICE_ACCOUNT_KEY_PATH)

            firebase_admin.initialize_app(cred)
            logger.info("Firebase: Admin SDK initialized.")
        except Exception as e:
            logger.error("Firebase: init failed — %s", e)
            logger.error(
                "Firebase: set FIREBASE_SERVICE_ACCOUNT_JSON or check key at '%s'",
                settings.FIREBASE_SERVICE_ACCOUNT_KEY_PATH,
            )
            return None

    try:
        return firestore.client()
    except Exception as e:
        logger.error("Firebase: could not create Firestore client — %s", e)
        return None


def _db_or_raise():
    db = initialize_firebase()
    if not db:
        raise RuntimeError("Firestore client not available (initialize_firebase failed).")
    return db


# -----------------------------
# Upload progress/event tracker
# -----------------------------
class UploadTracker:
    """
    Centralizes all Firestore writes for a single upload.
    Document path: Users/{uid}/Uploads/{upload_id}
    Subcollection for live events: .../events/{autoId}
    """

    def __init__(self, uid: str, upload_id: str, *, db_client: Optional[firestore.Client] = None):
        self.uid = uid
        self.upload_id = upload_id
        self.db: firestore.Client = db_client or _db_or_raise()
        self.ref = self.db.collection("Users").document(uid).collection("Uploads").document(upload_id)

    # ----- Lifecycle writes -----

    def start(
        self,
        *,
        folder_id: Optional[str] = None,
        unit_name: Optional[str] = None,
        section: Optional[str] = None
    ) -> None:
        try:
            self.ref.set(
                {
                    "status": "processing",
                    "folderId": folder_id or None,
                    "unitName": unit_name or "Upload",
                    "section": section or "General",
                    "questionCount": 0,
                    "last_message": "Starting…",
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                    "pipeline_ver": 1,
                },
                merge=True,
            )
            logger.info("UploadTracker[%s/%s]: start", self.uid, self.upload_id)
        except Exception as e:
            logger.error("UploadTracker start failed: %s", e)

    def complete(self, result_unit_id: str) -> None:
        try:
            self.ref.set(
                {
                    "status": "complete",
                    "resultUnitId": result_unit_id,
                    "last_message": "Done",
                    "completed_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            logger.info("UploadTracker[%s/%s]: complete (unit %s)", self.uid, self.upload_id, result_unit_id)
        except Exception as e:
            logger.error("UploadTracker complete failed: %s", e)

    def error(self, message: str) -> None:
        try:
            self.ref.set(
                {
                    "status": "error",
                    "error_message": message[:500],
                    "last_message": message[:120],
                    "completed_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            logger.warning("UploadTracker[%s/%s]: error: %s", self.uid, self.upload_id, message)
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
        """
        Adds a row to /events and updates the parent doc's last_message
        (+questionCount if requested).
        """
        try:
            batch = self.db.batch()

            ev = {
                "type": type,
                "message": message,
                "ts": firestore.SERVER_TIMESTAMP,
            }
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

            logger.debug("UploadTracker[%s/%s]: event %s — %s", self.uid, self.upload_id, type, message)
        except Exception as e:
            logger.error("UploadTracker event failed: %s", e)

    # Convenience helpers
    def event_question_created(
        self, *, label: str, index: Optional[int] = None, question_id: Optional[str] = None
    ) -> None:
        extra: Dict[str, Any] = {}
        if index is not None:
            extra["index"] = index
        if question_id is not None:
            extra["questionId"] = question_id
        self.event(type="questionCreated", message=f"Created Q {label}", inc_question=True, extra=extra)

    def event_note(self, msg: str) -> None:
        self.event(type="note", message=msg)


# -----------------------------
# Existing helpers (as before)
# -----------------------------

def upload_content(db_client, collection_path, document_id, data):
    """
    Upserts a dictionary of data to a specified Firestore collection/subcollection.

    WRITE POLICY:
      - settings.WRITE_MODE == "preserve": skip write if the document already exists.
      - settings.WRITE_MODE == "refresh": current behavior (merge=True).

    Ensures XP-related fields exist:
      - difficulty (1..8) derived from total_marks if missing
      - xp_base from difficulty if missing
      - xp_curve_version (default 1)

    Normalizes numeric fields and writes with merge=True so existing fields aren't wiped.
    """
    if not db_client:
        logger.error("Firebase: client not available; cannot upload '%s/%s'.", collection_path, document_id)
        return False

    try:
        doc_ref = db_client.collection(collection_path).document(document_id)

        # Respect write policy
        mode = getattr(settings, "WRITE_MODE", "preserve").strip().lower()
        exists_snapshot = None
        if mode == "preserve":
            try:
                exists_snapshot = doc_ref.get()
                if exists_snapshot.exists:
                    logger.info("Firebase: preserve mode; skipping existing '%s/%s'.", collection_path, document_id)
                    return True
            except Exception as e:
                logger.warning(
                    "Firebase: existence check failed for '%s/%s' — proceeding to write. (%s)",
                    collection_path, document_id, e
                )

        # Shallow copy so we don't mutate the caller's dict
        payload = dict(data)

        # ---- normalize numeric fields that we rely on downstream ----
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

        # ✅ Ensure 'difficulty' exists (respect pre-set value if present) and clamp to 1..8
        if "difficulty" not in payload or not isinstance(payload["difficulty"], int):
            payload["difficulty"] = marks_to_difficulty(payload.get("total_marks", 0))
        else:
            payload["difficulty"] = _clamp(payload["difficulty"], 1, 8)

        # ✅ Ensure 'xp_base' exists (respect pre-set value if present)
        if "xp_base" not in payload or not isinstance(payload["xp_base"], int):
            diff = _as_int(payload.get("difficulty"), 1)
            payload["xp_base"] = XP_TABLE.get(diff, XP_TABLE[1])

        # Optional but useful for future tuning/versioning
        if "xp_curve_version" not in payload:
            payload["xp_curve_version"] = 1

        # Timestamps
        if exists_snapshot is not None and not exists_snapshot.exists:
            payload.setdefault("created_at", firestore.SERVER_TIMESTAMP)
        payload["updated_at"] = firestore.SERVER_TIMESTAMP

        # Upsert with merge so re-runs don’t wipe unrelated fields
        doc_ref.set(payload, merge=True)

        logger.debug("Firebase: uploaded '%s' to '%s'.", document_id, collection_path)
        return True

    except Exception as e:
        logger.error("Firebase: upload failed for '%s/%s' — %s", collection_path, document_id, e)
        return False


def create_or_update_topic(db_client, topic_id):
    """
    Ensure a Topic doc exists. If no metadata is defined in settings.TOPIC_METADATA,
    create it with sensible defaults so the doc isn't empty.

    Defaults when metadata is missing:
      - topicName: a title-cased version of the topic_id (underscores/dashes to spaces)
      - section: "A" (placeholder that you can edit later in the console)

    Uses merge=True so existing fields/subcollections (e.g., Questions) are never wiped.
    """
    if not db_client:
        logger.error("Firebase: client not available; cannot ensure topic '%s'.", topic_id)
        return False

    # Prefer explicit metadata from settings when available
    metadata = settings.TOPIC_METADATA.get(topic_id)

    if not metadata:
        # Create readable title from the ID/slug
        base = re.sub(r'[_\-]+', ' ', topic_id).strip()
        base = re.sub(r'\s+', ' ', base)
        default_title = base.title()  # e.g., "Surds And Incdeces Questions"

        metadata = {
            "topicName": default_title,
            "section": "A",
        }
        logger.debug("Firebase: no metadata for '%s'. Using defaults %s", topic_id, metadata)

    try:
        doc_ref = db_client.collection("Topics").document(topic_id)
        metadata["updated_at"] = firestore.SERVER_TIMESTAMP
        # Set created_at if this is a brand-new topic
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
    