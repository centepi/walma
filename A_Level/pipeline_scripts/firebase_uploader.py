import os
import re
import json
import ast
from typing import Optional, Dict, Any, List, Tuple

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from config import settings
from . import utils
from . import firestore_sanitizer  # NEW: ensure nested arrays are Firestore-safe

logger = utils.setup_logger(__name__)

XP_TABLE = {
    1: 35, 2: 45, 3: 60, 4: 75, 5: 95, 6: 115, 7: 140, 8: 165,
}

_NUM_PREFIX_RE = re.compile(r"^(\d+)")
_DOCID_MAIN_RE = re.compile(r"^(\d+)")


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


# ✅ NEW: accept both int difficulties and string labels from iOS ("easy"/"medium"/"hard")
def _normalize_difficulty(value: Any, marks_fallback: Any) -> int:
    """
    Normalize difficulty to an int 1..8.

    Accepts:
    - int: clamped to 1..8
    - str: "easy"/"medium"/"hard" (and a few common variants), or "1".."8"
    Fallback:
    - derived from marks via marks_to_difficulty(...)
    """
    try:
        if isinstance(value, int):
            return max(1, min(8, int(value)))

        if isinstance(value, str):
            s = value.strip().lower()

            mapping = {
                "very easy": 1,
                "easy": 2,
                "medium": 4,
                "hard": 6,
                "very hard": 8,

                # allow numeric strings too
                "1": 1, "2": 2, "3": 3, "4": 4,
                "5": 5, "6": 6, "7": 7, "8": 8,
            }
            if s in mapping:
                return mapping[s]
    except Exception:
        pass

    return marks_to_difficulty(marks_fallback)


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
                        # ------------------------------------------------------------------
                        # FIX: Repair Firestore-mangled rows like {"0": "['a','b']"}
                        # so the iOS client can map headers -> values reliably.
                        # ------------------------------------------------------------------
                        if (
                            isinstance(r, dict)
                            and headers
                            and len(r) == 1
                            and ("0" in r)
                            and isinstance(r.get("0"), str)
                        ):
                            try:
                                parsed = ast.literal_eval(r["0"].strip())
                                if isinstance(parsed, (list, tuple)) and len(parsed) == len(headers):
                                    row_map = {str(headers[i]): str(parsed[i]) for i in range(len(headers))}
                                    new_rows.append(row_map)
                                    continue
                            except Exception:
                                pass

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


def _sanitize_svg_images_for_firestore(svg_images: Any) -> List[Dict[str, Any]]:
    """
    Ensure svg_images is a Firestore-safe list[dict] with string keys.
    This matches Option A schema:
        svg_images: [{id, label, svg_base64, kind}]
    """
    if not isinstance(svg_images, list):
        return []

    cleaned: List[Dict[str, Any]] = []
    for item in svg_images:
        if not isinstance(item, dict):
            continue

        # Stringify keys + keep values simple (Firestore-safe)
        out: Dict[str, Any] = {}
        for k, v in item.items():
            key = str(k)

            # svg_base64 should always be a string (large, but Firestore accepts it)
            if key == "svg_base64":
                out[key] = "" if v is None else str(v)
            # Common scalar fields
            elif key in {"id", "label", "kind"}:
                out[key] = "" if v is None else str(v)
            else:
                # Allow extras, but keep them JSON-safe
                if v is None:
                    out[key] = None
                elif isinstance(v, (str, int, float, bool)):
                    out[key] = v
                else:
                    out[key] = str(v)

        # Only keep if it actually has content
        if out.get("svg_base64"):
            cleaned.append(out)

    return cleaned


def _parse_user_upload_questions_path(collection_path: str) -> Optional[Tuple[str, str]]:
    """
    If collection_path is Users/{uid}/Uploads/{uploadId}/Questions, return (uid, uploadId).
    Else return None.
    """
    seg = collection_path.split("/")
    if (
        len(seg) >= 5
        and seg[0] == "Users"
        and seg[2] == "Uploads"
        and seg[-1] == "Questions"
    ):
        uid = seg[1]
        upload_id = seg[3]
        if uid and upload_id:
            return uid, upload_id
    return None


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


def _compute_max_main_from_questions(col_ref) -> int:
    """
    Best-effort scan of existing question docs to infer the maximum main number.
    Uses:
      - doc id prefix (preferred)
      - 'question_number'
      - 'logical_question_id'
    """
    max_n = 0
    try:
        for d in col_ref.stream():
            # 1) doc id
            try:
                m = _DOCID_MAIN_RE.match(getattr(d, "id", "") or "")
                if m:
                    max_n = max(max_n, int(m.group(1)))
            except Exception:
                pass

            # 2) fields
            try:
                data = d.to_dict() or {}
            except Exception:
                data = {}

            for key in ("question_number", "logical_question_id"):
                v = _extract_int_prefix(data.get(key))
                if isinstance(v, int):
                    max_n = max(max_n, v)

    except Exception as e:
        logger.warning("Firebase: failed scanning existing questions for max main (%s)", e)
    return max_n


def _allocate_next_main_number(db_client, *, uid: str, upload_id: str) -> int:
    """
    Atomically allocate the next main question number for this upload using a parent-doc counter.

    Parent: Users/{uid}/Uploads/{upload_id}
      - nextQuestionNumber: int (next value to allocate, 1-based)
    """
    parent_ref = (
        db_client.collection("Users")
                 .document(uid)
                 .collection("Uploads")
                 .document(upload_id)
    )
    questions_col = parent_ref.collection("Questions")

    def txn_fn(txn):
        snap = parent_ref.get(transaction=txn)
        data = snap.to_dict() if snap.exists else {}

        nxt = data.get("nextQuestionNumber")
        if isinstance(nxt, int) and nxt >= 1:
            allocated = int(nxt)
            txn.set(parent_ref, {"nextQuestionNumber": allocated + 1}, merge=True)
            return allocated

        # Counter missing/uninitialized: infer max once, then seed counter.
        max_existing = _compute_max_main_from_questions(questions_col)
        allocated = int(max_existing) + 1
        txn.set(parent_ref, {"nextQuestionNumber": allocated + 1}, merge=True)
        return allocated

    try:
        txn = db_client.transaction()
        return txn.call(txn_fn)
    except Exception as e:
        # Fallback (non-atomic): still try to avoid total failure.
        logger.error("Firebase: allocation transaction failed for %s/%s — %s", uid, upload_id, e)
        max_existing = _compute_max_main_from_questions(
            db_client.collection("Users").document(uid).collection("Uploads").document(upload_id).collection("Questions")
        )
        return int(max_existing) + 1


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
        """
        Mark as complete.

        ✅ FIX (prevents "+3" etc):
        - We NEVER Increment here.
        - `questionCount` is already being maintained live by `event(... inc_question=True)`.
        - If the caller supplies a number, we treat it as an absolute total and only
          write it if it is >= the current stored value (monotonic, no double-count).
        """
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
                qc = max(0, int(question_count))

                # Read current server value so we don't accidentally double-add.
                try:
                    snap = self.ref.get()
                    existing = snap.to_dict() if snap.exists else {}
                    existing_qc = existing.get("questionCount")
                except Exception:
                    existing_qc = None

                if isinstance(existing_qc, int):
                    # Only move forward (never reduce, never inflate by adding)
                    patch["questionCount"] = max(int(existing_qc), qc)
                else:
                    patch["questionCount"] = qc

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

    Behaviour:
    - For *user-upload questions* (paths like
      `Users/{uid}/Uploads/{uploadId}/Questions`), we:
          • treat `document_id` as the *logical* source id (e.g. "1", "1a", "2mcq"),
          • allocate the NEXT sequential main number atomically from the parent upload doc,
            so concurrent runs cannot collide,
          • preserve any suffix from the logical id (e.g. "a", "aii") and write:
              logical_question_id = "<next><suffix>"
              question_number      = "<next><suffix>"
          • write the Firestore doc id as "<next><suffix>" (so it sorts/stays unique).
    - For other `Users/...` docs (e.g. `Users/{uid}/Uploads/{uploadId}`),
      we always use the PROVIDED `document_id` and ignore WRITE_MODE.
    - For non-`Users/...` collections (e.g. `Topics`), we keep the
      original `WRITE_MODE` / "preserve" behaviour.
    """
    if not db_client:
        logger.error("Firebase: client not available; cannot upload '%s/%s'.", collection_path, document_id)
        return False

    try:
        segments = collection_path.split("/")

        is_user_upload_question = (
            len(segments) >= 5
            and segments[0] == "Users"
            and segments[2] == "Uploads"
            and segments[-1] == "Questions"
        )
        is_users_collection = segments[0] == "Users"

        doc_ref = None
        exists_snapshot = None
        logical_id = document_id  # what the caller *thinks* this question is (used only for suffix)
        chosen_doc_id = None

        if is_user_upload_question:
            # ------------------------------------------------------------
            # ✅ ATOMIC ALLOCATION: next sequential main number per upload
            # ------------------------------------------------------------
            parsed = _parse_user_upload_questions_path(collection_path)
            if not parsed:
                raise RuntimeError(f"Could not parse uid/upload_id from collection_path='{collection_path}'")
            uid, upload_id = parsed

            main_n = _allocate_next_main_number(db_client, uid=uid, upload_id=upload_id)

            # Preserve suffixes like "a", "aii", "-1a" if caller passes them (rare in your new flow)
            suffix_str = ""
            try:
                m = re.match(r"^\d+(.*)$", str(logical_id or "").strip())
                if m:
                    suffix_str = m.group(1) or ""
            except Exception:
                suffix_str = ""

            display_id = f"{int(main_n)}{suffix_str}".strip()
            chosen_doc_id = display_id

            col_ref = db_client.collection(collection_path)
            doc_ref = col_ref.document(chosen_doc_id)

            logger.debug(
                "Firebase: user-upload QUESTION path '%s' — allocated main=%s, logical_id='%s', doc_id='%s'.",
                collection_path,
                main_n,
                logical_id,
                chosen_doc_id,
            )

        elif is_users_collection:
            doc_ref = db_client.collection(collection_path).document(document_id)
            exists_snapshot = None
            logger.debug(
                "Firebase: Users path '%s' — using fixed doc id '%s'.",
                collection_path,
                document_id,
            )
        else:
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

        if "total_marks" in payload:
            payload["total_marks"] = _as_int(payload.get("total_marks"), 0)

        # ✅ FIX: accept string difficulty labels (easy/medium/hard) and numeric strings too
        payload["difficulty"] = _normalize_difficulty(
            payload.get("difficulty"),
            payload.get("total_marks", 0)
        )

        if "xp_base" not in payload or not isinstance(payload["xp_base"], int):
            diff = _as_int(payload.get("difficulty"), 1)
            payload["xp_base"] = XP_TABLE.get(diff, XP_TABLE[1])

        if "xp_curve_version" not in payload:
            payload["xp_curve_version"] = 1

        if exists_snapshot is not None and not exists_snapshot.exists:
            payload.setdefault("created_at", firestore.SERVER_TIMESTAMP)
            payload.setdefault("startedAt", firestore.SERVER_TIMESTAMP)

        payload["updated_at"] = firestore.SERVER_TIMESTAMP

        if is_user_upload_question:
            # Ensure the UI label matches what we actually wrote.
            payload["logical_question_id"] = chosen_doc_id or str(logical_id or "").strip() or ""
            payload["question_number"] = chosen_doc_id or str(logical_id or "").strip() or ""

            # Per-question timestamp (helps you show “added today” in UI)
            payload.setdefault("added_at", firestore.SERVER_TIMESTAMP)

        # --------------------------------------------------------------------
        # Visual data: ALWAYS make it Firestore-safe (nested arrays etc.)
        #
        # Preferred pattern:
        # - If upstream produced an explicit Firestore-safe copy, prefer it.
        #   (We accept either `visual_data_firestore` or `visual_data_sanitized`.)
        # - Otherwise sanitize `visual_data` here.
        #
        # This prevents silent breaks where one pipeline path sanitizes and
        # another doesn't (e.g. histogram bins [[0,5],[5,10]] are nested arrays).
        # --------------------------------------------------------------------
        if isinstance(payload.get("visual_data_firestore"), dict):
            payload["visual_data"] = payload.pop("visual_data_firestore")
        elif isinstance(payload.get("visual_data_sanitized"), dict):
            payload["visual_data"] = payload.pop("visual_data_sanitized")
        elif "visual_data" in payload and isinstance(payload["visual_data"], dict):
            payload["visual_data"] = firestore_sanitizer.sanitize_for_firestore(payload["visual_data"])

        # Keep the existing table-row normalization on top (safe idempotent cleanup)
        if "visual_data" in payload and isinstance(payload["visual_data"], dict):
            payload["visual_data"] = _sanitize_visual_data_for_firestore(payload["visual_data"])

        # -------------------------
        # NEW: Sanitize svg_images (Option A schema) if present
        # -------------------------
        if "svg_images" in payload:
            payload["svg_images"] = _sanitize_svg_images_for_firestore(payload.get("svg_images"))

        doc_ref.set(payload, merge=True)
        logger.info(
            "Firebase upload_content: path='%s', is_user_upload_question=%s, doc_id='%s', logical_id='%s'",
            collection_path,
            is_user_upload_question,
            doc_ref.id,
            logical_id,
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