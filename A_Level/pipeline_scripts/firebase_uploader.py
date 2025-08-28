import re
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from config import settings
from . import utils

# Unified logger (inherits global levels from utils/setup)
logger = utils.setup_logger(__name__)


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
    Uploads a dictionary of data to a specified Firestore collection/subcollection.
    The document will have the given document_id.
    """
    if not db_client:
        logger.error("Firebase: client not available; cannot upload '%s/%s'.", collection_path, document_id)
        return False
    try:
        doc_ref = db_client.collection(collection_path).document(document_id)
        doc_ref.set(data)
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
        doc_ref.set(metadata, merge=True)  # merge prevents overwriting existing fields/subcollections
        logger.info("Firebase: topic ensured '%s'.", topic_id)
        return True
    except Exception as e:
        logger.error("Firebase: failed to ensure topic '%s' — %s", topic_id, e)
        return False
