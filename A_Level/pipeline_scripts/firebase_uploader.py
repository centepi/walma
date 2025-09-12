import re
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
    Initializes the Firebase Admin SDK using the service account key.
    Returns a Firestore client object if successful, otherwise None.
    """
    # This check prevents initializing the app more than once
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_KEY_PATH)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase: Admin SDK initialized.")
        except Exception as e:
            logger.error("Firebase: init failed — %s", e)
            logger.error("Firebase: check key at '%s'", settings.FIREBASE_SERVICE_ACCOUNT_KEY_PATH)
            return None

    return firestore.client()


def upload_content(db_client, collection_path, document_id, data):
    """
    Upserts a dictionary of data to a specified Firestore collection/subcollection.
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

        # Shallow copy so we don't mutate the caller's dict
        payload = dict(data)

        # ---- normalize numeric fields that we rely on downstream ----
        def _as_int(v, default=0):
            try:
                return int(v)
            except Exception:
                return default

        if "total_marks" in payload:
            payload["total_marks"] = _as_int(payload.get("total_marks"), 0)

        # ✅ Ensure 'difficulty' exists (respect pre-set value if present)
        if "difficulty" not in payload or not isinstance(payload["difficulty"], int):
            payload["difficulty"] = marks_to_difficulty(payload.get("total_marks", 0))

        # ✅ Ensure 'xp_base' exists (respect pre-set value if present)
        if "xp_base" not in payload or not isinstance(payload["xp_base"], int):
            diff = _as_int(payload.get("difficulty"), 1)
            payload["xp_base"] = XP_TABLE.get(diff, XP_TABLE[1])

        # Optional but useful for future tuning/versioning
        if "xp_curve_version" not in payload:
            payload["xp_curve_version"] = 1

        # Audit field (server timestamp)
        payload["updated_at"] = firestore.SERVER_TIMESTAMP

        # Upsert with merge so re-runs don’t wipe unrelated fields
        doc_ref.set(payload, merge=True)

        # Keep success message quiet to avoid per-item spam; main pipeline logs uploads at INFO.
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
        doc_ref.set(metadata, merge=True)  # merge prevents overwriting existing fields/subcollections
        logger.info("Firebase: topic ensured '%s'.", topic_id)
        return True
    except Exception as e:
        logger.error("Firebase: failed to ensure topic '%s' — %s", topic_id, e)
        return False
