# A_Level/routers/entitlements_router.py
from typing import Any, Dict, Tuple
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from pipeline_scripts import firebase_uploader, entitlements

router = APIRouter()

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

@router.get("/api/entitlements")
def get_entitlements(request: Request):
    """
    Read stable entitlements from the global ledger (NO consumption).
    Uses the same provider_key logic as /process-text.
    """
    _uid, provider_key = _require_auth_context_from_request(request)

    db_client = firebase_uploader.initialize_firebase()
    if not db_client:
        raise HTTPException(status_code=500, detail="Firestore client not available.")

    ok, info = entitlements.try_consume_question_credit(
        db_client,
        uid=provider_key,
        n=0,  # ✅ read-only
        default_free_cap=30,
    )
    # ok will be True for n=0; but we return info regardless.
    return JSONResponse(info, status_code=200)