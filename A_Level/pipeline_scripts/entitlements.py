# pipeline_scripts/entitlements.py
from __future__ import annotations

import hashlib
import os
from typing import Dict, Any, Tuple, Optional

from firebase_admin import auth as firebase_auth
from firebase_admin import firestore

# ✅ Proper fix pieces (server-side verification)
# We verify StoreKit 2 JWS proof (Transaction.jwsRepresentation) when provided.
from pipeline_scripts.storekit_verifier import (
    verify_storekit2_transaction,
    extract_subscription_active_from_transaction_payload,
    StoreKitVerificationError,
)


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
# Keep the salt stable once set.
#
# NEW (authoritative subscription, proper fix):
# - If the client includes StoreKit 2 proof (signed transaction JWS),
#   the server verifies it and *then* updates entitlement ledger canonically.
#
# Env config for verification:
#   - STOREKIT_TRUSTED_ROOTS_PEM (optional): Apple root(s) PEM string(s) for chain validation.
#       * If absent, we still verify signature with x5c leaf but skip trust anchoring (weaker).
#   - APPLE_BUNDLE_ID (recommended): expected bundle id
#   - STOREKIT_ENVIRONMENT (optional): "Sandbox" or "Production" (case-insensitive)
#   - STOREKIT_PRODUCT_IDS (recommended): comma-separated allowed product IDs
#
# IMPORTANT: This module never grants subscription unless cryptographic verification succeeds.


LEDGER_COLLECTION = os.getenv("ENTITLEMENTS_LEDGER_COLLECTION", "EntitlementLedger")
ENTITLEMENTS_SALT = os.getenv("ENTITLEMENTS_SALT", "")

# StoreKit verification config
APPLE_BUNDLE_ID = (os.getenv("APPLE_BUNDLE_ID") or "").strip() or None
STOREKIT_ENVIRONMENT = (os.getenv("STOREKIT_ENVIRONMENT") or "").strip() or None  # "Sandbox" | "Production"
STOREKIT_PRODUCT_IDS = [
    s.strip()
    for s in (os.getenv("STOREKIT_PRODUCT_IDS") or "").split(",")
    if s.strip()
]
STOREKIT_TRUSTED_ROOTS_PEM = os.getenv("STOREKIT_TRUSTED_ROOTS_PEM") or None


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
            if getattr(p, "provider_id", None) == "apple.com":
                return getattr(p, "uid", None)
    except Exception:
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

    # If caller already provides a stable identity key, use it directly.
    m = raw.split(":", 1)
    if len(m) == 2 and m[0].strip().lower() in {"apple", "google", "email", "uid"} and m[1].strip():
        key_type = _normalize_key_type(m[0])
        return _hash_key(f"{key_type}:{m[1].strip()}"), key_type

    # Legacy path: treat input as Firebase uid and try to resolve Apple provider uid
    apple_uid = _get_apple_provider_uid(raw)
    if apple_uid:
        return _hash_key(f"apple:{apple_uid}"), "apple"

    return _hash_key(f"uid:{raw}"), "uid"


def _looks_like_prefixed_key(s: str) -> bool:
    raw = (s or "").strip()
    if ":" not in raw:
        return False
    prefix = raw.split(":", 1)[0].strip().lower()
    return prefix in {"apple", "google", "email", "uid"}


def _read_bool_with_aliases(d: Dict[str, Any], snake: str, camel: str, default: bool = False) -> bool:
    """
    Firestore docs may contain either snake_case or camelCase fields depending on
    which writer wrote them. Read both safely.
    """
    if not isinstance(d, dict):
        return default
    v = d.get(snake)
    if isinstance(v, bool):
        return v
    v2 = d.get(camel)
    if isinstance(v2, bool):
        return v2
    return default


def _read_int_with_aliases(d: Dict[str, Any], snake: str, camel: str, default: Optional[int] = None) -> Optional[int]:
    if not isinstance(d, dict):
        return default
    v = d.get(snake)
    if isinstance(v, int):
        return v
    v2 = d.get(camel)
    if isinstance(v2, int):
        return v2
    return default


def _info_payload(
    *,
    is_sub: bool,
    cap: int,
    used: int,
    key_type: str,
    stable_key: str,
    storekit_verified: bool = False,
) -> Dict[str, Any]:
    # IMPORTANT: keep these keys snake_case so iOS can decode using convertFromSnakeCase.
    return {
        "is_subscribed": bool(is_sub),
        "cap": int(cap),
        "used": int(used),
        "remaining": max(0, int(cap) - int(used)),
        "key_type": key_type,
        "key": stable_key,  # hashed ledger doc id (safe to log)
        "storekit_verified": bool(storekit_verified),
    }


def _read_or_seed_ledger_fields(
    *,
    ledger: Dict[str, Any],
    legacy: Dict[str, Any],
    default_free_cap: int,
) -> Tuple[int, int, bool]:
    """
    Returns (cap, used, is_subscribed_ledger_based).
    Does NOT do StoreKit verification; it only reads persisted ledger state.
    """
    cap = _read_int_with_aliases(ledger, "free_question_cap", "freeQuestionCap", None)
    used = _read_int_with_aliases(ledger, "questions_created_total", "questionsCreatedTotal", None)
    is_sub = _read_bool_with_aliases(ledger, "is_subscribed", "isSubscribed", False)

    if not isinstance(cap, int):
        legacy_cap = _read_int_with_aliases(legacy, "free_question_cap", "freeQuestionCap", None)
        cap = int(legacy_cap) if isinstance(legacy_cap, int) else int(default_free_cap)

    if not isinstance(used, int):
        legacy_used = _read_int_with_aliases(legacy, "questions_created_total", "questionsCreatedTotal", None)
        used = int(legacy_used) if isinstance(legacy_used, int) else 0

    # Respect legacy subscribed (only if ledger isn't already subscribed)
    if not is_sub and _read_bool_with_aliases(legacy, "is_subscribed", "isSubscribed", False):
        is_sub = True

    return int(cap), int(used), bool(is_sub)


def _allowed_product_ids() -> Optional[list[str]]:
    return STOREKIT_PRODUCT_IDS or None


def _maybe_storekit_active_from_jws(storekit_jws: Optional[str]) -> Tuple[bool, bool, Dict[str, Any]]:
    """
    Authoritative StoreKit check.

    Returns (is_subscribed, verified, meta)

    - verified=True means: cryptographic verification succeeded AND payload checks passed
      (bundleId/env/productIds as configured).
    - is_subscribed is computed from verified payload (expiry/revocation).
    - meta contains small safe fields you may want to persist (product/environment/exp_ms).
    """
    raw = (storekit_jws or "").strip()
    if not raw:
        return False, False, {}

    try:
        payload = verify_storekit2_transaction(
            raw,
            trusted_roots_pem=STOREKIT_TRUSTED_ROOTS_PEM,
            bundle_id=APPLE_BUNDLE_ID,
            environment=STOREKIT_ENVIRONMENT,
            product_ids=_allowed_product_ids(),
            require_active=False,  # we compute active below (and can still write verified+inactive)
        )

        is_active = bool(extract_subscription_active_from_transaction_payload(payload))

        meta: Dict[str, Any] = {}
        # Store minimal useful fields (no full payload, no JWS)
        pid = payload.get("productId") or payload.get("productID") or payload.get("product_id")
        env = payload.get("environment") or payload.get("env")
        exp = (
            payload.get("expiresDate")
            or payload.get("expires_date")
            or payload.get("expirationDate")
            or payload.get("expiration_date")
        )
        rev = payload.get("revocationDate") or payload.get("revocation_date")

        if isinstance(pid, str) and pid.strip():
            meta["storekit_product_id"] = pid.strip()
        if isinstance(env, str) and env.strip():
            meta["storekit_environment"] = env.strip()
        if isinstance(exp, int) and exp > 0:
            meta["storekit_expires_date_ms"] = int(exp)
        if isinstance(rev, int) and rev > 0:
            meta["storekit_revocation_date_ms"] = int(rev)

        return is_active, True, meta

    except StoreKitVerificationError:
        # Verification failed => do NOT grant anything.
        return False, False, {}
    except Exception:
        # Any other unexpected error => safe default
        return False, False, {}


def get_effective_entitlements_snapshot(
    db_client,
    *,
    uid: str,
    storekit_jws: Optional[str] = None,
    default_free_cap: int = 30,
) -> Dict[str, Any]:
    """
    Read entitlements snapshot WITHOUT consuming credits.

    Priority rules:
      1) If StoreKit JWS is provided AND verifies successfully:
           is_subscribed = derived from verified StoreKit payload (authoritative)
      2) Else fall back to ledger's persisted is_subscribed
      3) Always return quota counters (cap/used/remaining) from the global ledger seed logic.
    """
    stable_key, key_type = _resolve_stable_key(uid)
    ledger_ref = _ledger_ref(db_client, stable_key)
    legacy_ref = None if _looks_like_prefixed_key(uid) else _legacy_user_ref(db_client, uid)

    ledger_snap = ledger_ref.get()
    ledger = ledger_snap.to_dict() if getattr(ledger_snap, "exists", False) else {}

    legacy = {}
    if legacy_ref is not None:
        legacy_snap = legacy_ref.get()
        legacy = legacy_snap.to_dict() if getattr(legacy_snap, "exists", False) else {}

    cap, used, ledger_is_sub = _read_or_seed_ledger_fields(
        ledger=ledger,
        legacy=legacy,
        default_free_cap=default_free_cap,
    )

    # ✅ Proper fix: verify StoreKit proof if provided
    storekit_is_sub, storekit_verified, storekit_meta = _maybe_storekit_active_from_jws(storekit_jws)

    # Authoritative only if verified
    effective_is_subscribed = bool(storekit_is_sub) if storekit_verified else bool(ledger_is_sub)

    # Best-effort: ensure ledger doc exists & is updated with canonical fields.
    # IMPORTANT: If StoreKit verified, we also update ledger is_subscribed to match
    # the server-derived truth.
    try:
        patch: Dict[str, Any] = {
            "free_question_cap": int(cap),
            "questions_created_total": int(used),
            "key_type": key_type,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }

        # canonical subscription state to persist:
        canonical_is_sub = bool(storekit_is_sub) if storekit_verified else bool(ledger_is_sub)
        patch["is_subscribed"] = canonical_is_sub
        patch["isSubscribed"] = canonical_is_sub  # alias safety

        if storekit_verified:
            patch["storekit_verified"] = True
            patch["storekit_last_verified_at"] = firestore.SERVER_TIMESTAMP
            for k, v in (storekit_meta or {}).items():
                patch[k] = v
        else:
            # Don't overwrite a previously-true storekit_verified flag unless you want to.
            # We just leave it as-is if present.
            pass

        if not getattr(ledger_snap, "exists", False):
            patch["created_at"] = firestore.SERVER_TIMESTAMP

        ledger_ref.set(patch, merge=True)
    except Exception:
        pass

    return _info_payload(
        is_sub=bool(effective_is_subscribed),
        cap=int(cap),
        used=int(used),
        key_type=key_type,
        stable_key=stable_key,
        storekit_verified=bool(storekit_verified),
    )


def upsert_subscription_state(
    db_client,
    *,
    uid: str,
    is_subscribed: bool,
    default_free_cap: int = 30,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Persist subscription state into the *global* entitlement ledger doc.

    NOTE: Kept for back-compat / admin tooling.
          The "proper fix" path is StoreKit proof verification at request time.
    """
    stable_key, key_type = _resolve_stable_key(uid)
    ledger_ref = _ledger_ref(db_client, stable_key)

    legacy_ref = None if _looks_like_prefixed_key(uid) else _legacy_user_ref(db_client, uid)

    @firestore.transactional
    def txn_fn(txn):
        snap = ledger_ref.get(transaction=txn)
        ledger = snap.to_dict() if snap.exists else {}

        legacy = {}
        if legacy_ref is not None:
            legacy_snap = legacy_ref.get(transaction=txn)
            legacy = legacy_snap.to_dict() if legacy_snap.exists else {}

        cap = _read_int_with_aliases(ledger, "free_question_cap", "freeQuestionCap", None)
        if not isinstance(cap, int):
            legacy_cap = _read_int_with_aliases(legacy, "free_question_cap", "freeQuestionCap", None)
            cap = int(legacy_cap) if isinstance(legacy_cap, int) else int(default_free_cap)

        used = _read_int_with_aliases(ledger, "questions_created_total", "questionsCreatedTotal", None)
        if not isinstance(used, int):
            legacy_used = _read_int_with_aliases(legacy, "questions_created_total", "questionsCreatedTotal", None)
            used = int(legacy_used) if isinstance(legacy_used, int) else 0

        patch: Dict[str, Any] = {
            "free_question_cap": int(cap),
            "questions_created_total": int(used),
            "is_subscribed": bool(is_subscribed),
            "isSubscribed": bool(is_subscribed),  # alias safety
            "key_type": key_type,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        if source:
            patch["subscription_source"] = str(source)
            patch["subscriptionSource"] = str(source)  # alias
        if not snap.exists:
            patch["created_at"] = firestore.SERVER_TIMESTAMP

        txn.set(ledger_ref, patch, merge=True)

        if legacy_ref is not None:
            legacy_patch: Dict[str, Any] = {
                "free_question_cap": int(cap),
                "questions_created_total": int(used),
                "is_subscribed": bool(is_subscribed),
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
            if not legacy:
                legacy_patch["created_at"] = firestore.SERVER_TIMESTAMP
            txn.set(legacy_ref, legacy_patch, merge=True)

        return _info_payload(
            is_sub=bool(is_subscribed),
            cap=int(cap),
            used=int(used),
            key_type=key_type,
            stable_key=stable_key,
            storekit_verified=False,
        )

    txn = db_client.transaction()
    return txn_fn(txn)


def try_consume_question_credit(
    db_client,
    *,
    uid: str,
    n: int = 1,
    default_free_cap: int = 30,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Atomically consume n credits (question creations) for a user.

    IMPORTANT:
    - This function enforces quota based on the global ledger.
    - Subscription state comes from ledger fields.
      (Option A "best": the quota-enforced endpoints should first call
       get_effective_entitlements_snapshot(..., storekit_jws=...) so ledger is updated
       from verified proof *before* this consume function runs.)
    """
    n = max(0, int(n))
    stable_key, key_type = _resolve_stable_key(uid)

    ledger_ref = _ledger_ref(db_client, stable_key)
    legacy_ref = None if _looks_like_prefixed_key(uid) else _legacy_user_ref(db_client, uid)

    @firestore.transactional
    def txn_fn(txn):
        ledger_snap = ledger_ref.get(transaction=txn)
        ledger = ledger_snap.to_dict() if ledger_snap.exists else {}

        legacy = {}
        if legacy_ref is not None:
            legacy_snap = legacy_ref.get(transaction=txn)
            legacy = legacy_snap.to_dict() if legacy_snap.exists else {}

        cap, used, is_sub = _read_or_seed_ledger_fields(
            ledger=ledger,
            legacy=legacy,
            default_free_cap=default_free_cap,
        )

        def _upsert_ledger(*, is_subscribed: bool, used_value: int, increment: bool = False):
            payload: Dict[str, Any] = {
                "free_question_cap": int(cap),
                "questions_created_total": firestore.Increment(n) if increment else int(used_value),
                "is_subscribed": bool(is_subscribed),
                "isSubscribed": bool(is_subscribed),  # alias safety
                "key_type": key_type,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
            if not ledger_snap.exists:
                payload["created_at"] = firestore.SERVER_TIMESTAMP
            txn.set(ledger_ref, payload, merge=True)

        def _upsert_legacy(*, is_subscribed: bool, used_value: int, increment: bool = False):
            if legacy_ref is None:
                return
            payload: Dict[str, Any] = {
                "free_question_cap": int(cap),
                "questions_created_total": firestore.Increment(n) if increment else int(used_value),
                "is_subscribed": bool(is_subscribed),
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
            if not legacy:
                payload["created_at"] = firestore.SERVER_TIMESTAMP
            txn.set(legacy_ref, payload, merge=True)

        # Subscribed: allow without consuming
        if is_sub:
            _upsert_ledger(is_subscribed=True, used_value=int(used), increment=False)
            _upsert_legacy(is_subscribed=True, used_value=int(used), increment=False)
            return True, _info_payload(
                is_sub=True,
                cap=int(cap),
                used=int(used),
                key_type=key_type,
                stable_key=stable_key,
                storekit_verified=bool(_read_bool_with_aliases(ledger, "storekit_verified", "storekitVerified", False)),
            )

        # Not subscribed: enforce cap
        if int(used) + int(n) > int(cap):
            _upsert_ledger(is_subscribed=False, used_value=int(used), increment=False)
            _upsert_legacy(is_subscribed=False, used_value=int(used), increment=False)
            return False, _info_payload(
                is_sub=False,
                cap=int(cap),
                used=int(used),
                key_type=key_type,
                stable_key=stable_key,
                storekit_verified=bool(_read_bool_with_aliases(ledger, "storekit_verified", "storekitVerified", False)),
            )

        # Allowed: increment
        _upsert_ledger(is_subscribed=False, used_value=int(used), increment=True)
        _upsert_legacy(is_subscribed=False, used_value=int(used), increment=True)

        new_used = int(used) + int(n)
        return True, _info_payload(
            is_sub=False,
            cap=int(cap),
            used=int(new_used),
            key_type=key_type,
            stable_key=stable_key,
            storekit_verified=bool(_read_bool_with_aliases(ledger, "storekit_verified", "storekitVerified", False)),
        )

    txn = db_client.transaction()
    ok, info = txn_fn(txn)
    return ok, info