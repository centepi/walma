# pipeline_scripts/entitlements.py
from __future__ import annotations

import hashlib
import os
from typing import Dict, Any, Tuple, Optional

from firebase_admin import auth as firebase_auth
from firebase_admin import firestore


# ============================
#  Stable entitlement identity
# ============================
#
# Goal: free quota must NOT reset when a user deletes/recreates their Firebase account.
# Fix: key quota to a stable provider identity (Apple "user" id), hashed + salted,
# stored in a global ledger collection outside Users/{uid}.
#
# IMPORTANT UPDATE:
# - Callers may now pass either:
#     a) a Firebase uid (legacy), OR
#     b) a pre-resolved provider key string like:
#        "apple:<id>", "google:<id>", "email:<id>", "uid:<id>"
#   In case (b), we DO NOT call firebase_auth.get_user() and we hash the provided
#   stable key directly.
#
# NOTE: set ENTITLEMENTS_SALT in your env for consistent hashing across deploys.
# If it's missing, we still work, but hashing becomes weaker and could change if you change code.
# Keep the salt stable once set.


LEDGER_COLLECTION = os.getenv("ENTITLEMENTS_LEDGER_COLLECTION", "EntitlementLedger")
ENTITLEMENTS_SALT = os.getenv("ENTITLEMENTS_SALT", "")


def _hash_key(raw: str) -> str:
    raw = raw or ""
    material = f"{ENTITLEMENTS_SALT}|{raw}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _get_apple_provider_uid(uid: str) -> Optional[str]:
    """
    Returns the stable Apple provider user id for this Firebase user if available.
    Otherwise None.

    NOTE: This expects `uid` to be a Firebase Auth uid.
    """
    try:
        u = firebase_auth.get_user(uid)
        for p in (u.provider_data or []):
            # provider_id is "apple.com" for Sign in with Apple users
            if getattr(p, "provider_id", None) == "apple.com":
                # uid on provider record is the stable Apple identifier
                return getattr(p, "uid", None)
    except Exception:
        # If auth lookup fails, we'll fall back to uid below.
        pass
    return None


def _ledger_ref(db_client, stable_key: str):
    return db_client.collection(LEDGER_COLLECTION).document(stable_key)


def _legacy_user_ref(db_client, uid: str):
    """
    Old per-uid location (resets on account deletion). Kept for:
    - back-compat reads
    - optional one-time migration into the global ledger

    NOTE: This path expects a Firebase Auth uid.
    """
    return (
        db_client.collection("Users")
        .document(uid)
        .collection("Entitlements")
        .document("main")
    )


def _normalize_key_type(prefix: str) -> str:
    p = (prefix or "").strip().lower()
    if p in {"apple", "google", "email", "uid"}:
        return p
    return "uid"


def _resolve_stable_key(uid: str) -> Tuple[str, str]:
    """
    Returns (stable_key, key_type).

    Accepts either:
      - Firebase uid (legacy), OR
      - pre-resolved stable key string: "apple:<id>", "google:<id>", "email:<id>", "uid:<id>"

    key_type = "apple" | "google" | "email" | "uid"
    """
    raw = (uid or "").strip()

    # ✅ NEW: if caller already provides a stable identity key, use it directly
    # (avoid firebase_auth.get_user(), which expects a Firebase uid).
    m = raw.split(":", 1)
    if len(m) == 2 and m[0].strip().lower() in {"apple", "google", "email", "uid"} and m[1].strip():
        key_type = _normalize_key_type(m[0])
        return _hash_key(f"{key_type}:{m[1].strip()}"), key_type

    # Legacy path: treat input as Firebase uid and try to resolve Apple provider uid
    apple_uid = _get_apple_provider_uid(raw)
    if apple_uid:
        return _hash_key(f"apple:{apple_uid}"), "apple"

    return _hash_key(f"uid:{raw}"), "uid"


def try_consume_question_credit(
    db_client,
    *,
    uid: str,
    n: int = 1,
    default_free_cap: int = 30,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Atomically consume n credits (question creations) for a user.

    ✅ Fix: consumption is tracked in a global ledger keyed by a stable identity
            (Apple provider uid when available, or a caller-provided stable key),
            so deleting/recreating the Firebase account does NOT reset free quota.

    IMPORTANT:
    - `uid` may be a Firebase uid (legacy), OR a stable provider key string
      like "apple:<id>", "google:<id>", "email:<id>", "uid:<id>".

    Returns (ok, info) where info includes:
      - is_subscribed: bool
      - cap: int
      - used: int
      - remaining: int
      - key_type: "apple" | "google" | "email" | "uid"
      - key: hashed ledger doc id (safe to log)
    """
    n = max(0, int(n))
    stable_key, key_type = _resolve_stable_key(uid)

    ledger_ref = _ledger_ref(db_client, stable_key)

    # Legacy doc only makes sense if input looks like a Firebase uid (no "<type>:<id>" prefix)
    looks_like_prefixed_key = ":" in (uid or "").strip() and (uid or "").split(":", 1)[0].strip().lower() in {
        "apple", "google", "email", "uid"
    }
    legacy_ref = None if looks_like_prefixed_key else _legacy_user_ref(db_client, uid)

    @firestore.transactional
    def txn_fn(txn):
        # --- Read global ledger (source of truth)
        ledger_snap = ledger_ref.get(transaction=txn)
        ledger = ledger_snap.to_dict() if ledger_snap.exists else {}

        # --- Optional: read legacy per-uid entitlements for a one-time migration
        legacy = {}
        if legacy_ref is not None:
            legacy_snap = legacy_ref.get(transaction=txn)
            legacy = legacy_snap.to_dict() if legacy_snap.exists else {}

        # Decide current values (prefer ledger; if missing, seed from legacy)
        cap = ledger.get("free_question_cap")
        used = ledger.get("questions_created_total")
        is_sub = bool(ledger.get("is_subscribed", False))

        # If ledger missing core fields, seed from legacy (one-time)
        if not isinstance(cap, int):
            legacy_cap = legacy.get("free_question_cap")
            cap = int(legacy_cap) if isinstance(legacy_cap, int) else int(default_free_cap)

        if not isinstance(used, int):
            legacy_used = legacy.get("questions_created_total")
            used = int(legacy_used) if isinstance(legacy_used, int) else 0

        # If legacy says subscribed, respect it (but ledger is authoritative once set)
        if not is_sub and bool(legacy.get("is_subscribed", False)):
            is_sub = True

        def _upsert_ledger(is_subscribed: bool, used_value, increment: bool = False):
            payload = {
                "free_question_cap": cap,
                "questions_created_total": firestore.Increment(n) if increment else used_value,
                "is_subscribed": bool(is_subscribed),
                "key_type": key_type,
                "updated_at": firestore.SERVER_TIMESTAMP,
                "created_at": ledger.get("created_at") or firestore.SERVER_TIMESTAMP,
            }
            txn.set(ledger_ref, payload, merge=True)

        def _upsert_legacy(is_subscribed: bool, used_value, increment: bool = False):
            if legacy_ref is None:
                return
            payload = {
                "free_question_cap": cap,
                "questions_created_total": firestore.Increment(n) if increment else used_value,
                "is_subscribed": bool(is_subscribed),
                "updated_at": firestore.SERVER_TIMESTAMP,
                "created_at": legacy.get("created_at") or firestore.SERVER_TIMESTAMP,
            }
            txn.set(legacy_ref, payload, merge=True)

        # If subscribed, allow without consuming (but ensure ledger exists)
        if is_sub:
            _upsert_ledger(True, used, increment=False)
            _upsert_legacy(True, used, increment=False)
            return True, {
                "is_subscribed": True,
                "cap": cap,
                "used": used,
                "remaining": max(0, cap - used),
                "key_type": key_type,
                "key": stable_key,
            }

        # Not subscribed: enforce cap
        if used + n > cap:
            # Ensure ledger exists + timestamps even on reject
            _upsert_ledger(False, used, increment=False)
            _upsert_legacy(False, used, increment=False)
            return False, {
                "is_subscribed": False,
                "cap": cap,
                "used": used,
                "remaining": max(0, cap - used),
                "key_type": key_type,
                "key": stable_key,
            }

        # Allowed: increment in the ledger
        _upsert_ledger(False, used, increment=True)
        _upsert_legacy(False, used, increment=True)

        new_used = used + n
        return True, {
            "is_subscribed": False,
            "cap": cap,
            "used": new_used,
            "remaining": max(0, cap - new_used),
            "key_type": key_type,
            "key": stable_key,
        }

    txn = db_client.transaction()
    ok, info = txn_fn(txn)
    return ok, info