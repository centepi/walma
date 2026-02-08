# A_Level/routers/entitlements_router.py
import os
from typing import Any, Dict, Tuple, Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from pipeline_scripts import firebase_uploader, entitlements, utils

router = APIRouter()

logger = utils.setup_logger(__name__)


def _bearer_token_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    x = request.headers.get("X-ID-Token")
    return x.strip() if x else ""


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
    # Import firebase_auth lazily so this file doesn't force init at import time
    from firebase_admin import auth as firebase_auth

    _ = firebase_uploader.initialize_firebase()
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
    """
    StoreKit 2 proof (signed transaction JWS) sent from iOS.
    We accept it via header so it can be attached to ANY request easily.
    """
    v = request.headers.get("X-StoreKit-Transaction", "") or request.headers.get("X-StoreKit-JWS", "")
    return v.strip()


@router.get("/api/entitlements")
def get_entitlements(request: Request):
    """
    Read stable entitlements.

    ✅ New (proper) model:
      - Client may include a StoreKit 2 signed transaction JWS via:
          X-StoreKit-Transaction: <JWS>
      - Server verifies it (in entitlements module) and computes is_subscribed
        from verifiable data (not from a client "sync").

    Notes:
      - Still uses provider_key to keep the free quota ledger stable.
      - This endpoint does not consume credits.
    """
    _uid, provider_key = _require_auth_context_from_request(request)

    storekit_jws = _storekit_jws_from_request(request)

    logger.info(
        "[entitlements] provider_key=%s has_storekit_jws=%s jws_len=%d ENTITLEMENTS_SALT_len=%d LEDGER_COLLECTION=%s",
        provider_key,
        bool(storekit_jws),
        len(storekit_jws),
        len(os.getenv("ENTITLEMENTS_SALT", "")),
        os.getenv("ENTITLEMENTS_LEDGER_COLLECTION", "EntitlementLedger"),
    )

    db_client = firebase_uploader.initialize_firebase()
    if not db_client:
        raise HTTPException(status_code=500, detail="Firestore client not available.")

    # ✅ Prefer the new authoritative path (StoreKit proof -> server-verified subscription)
    # while keeping a safe fallback during rollout.
    if hasattr(entitlements, "get_effective_entitlements_snapshot"):
        try:
            info = entitlements.get_effective_entitlements_snapshot(
                db_client,
                uid=provider_key,
                storekit_jws=storekit_jws or None,
                default_free_cap=6,   # ✅ was 30
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to resolve entitlements: {e}")
    else:
        # Fallback (legacy): ledger-only, no StoreKit verification (temporary)
        ok, info = entitlements.try_consume_question_credit(
            db_client,
            uid=provider_key,
            n=0,  # read-only
            default_free_cap=6,    # ✅ was 30
        )
        _ = ok

    logger.info(
        "[entitlements] key_type=%s key=%s cap=%s used=%s remaining=%s is_subscribed=%s storekit_verified=%s",
        info.get("key_type"),
        (info.get("key") or "")[:12],
        info.get("cap"),
        info.get("used"),
        info.get("remaining"),
        info.get("is_subscribed"),
        info.get("storekit_verified"),
    )

    return JSONResponse(info, status_code=200)