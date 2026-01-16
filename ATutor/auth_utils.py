# ATutor/auth_utils.py
# Minimal helper for verifying Firebase ID tokens from HTTP requests.

from typing import Optional
import logging

import firebase_admin
from firebase_admin import auth
from fastapi import Header, HTTPException, status

# We rely on your existing FirebaseManager to initialize the Admin SDK once.
# (utils.FirebaseManager sets up firebase_admin.initialize_app with env creds.)
from utils import FirebaseManager


def _ensure_firebase_initialized() -> None:
    """
    Ensure firebase_admin is initialized before using auth.verify_id_token.
    Safe to call multiple times.
    """
    try:
        firebase_admin.get_app()
    except ValueError:
        # Not initialized yet — do it via your singleton manager.
        FirebaseManager().initialize()


def _extract_bearer_token(authorization_header: Optional[str]) -> Optional[str]:
    """
    Extract the JWT from an Authorization header of the form: "Bearer <token>".
    Returns None if the header is missing or malformed.
    """
    if not authorization_header:
        return None
    parts = authorization_header.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def verify_request_and_get_uid(authorization_header: Optional[str]) -> str:
    """
    Verify the Firebase ID token from the Authorization header and return the caller's uid.
    Raises HTTP 401 if missing/invalid.
    """
    _ensure_firebase_initialized()

    token = _extract_bearer_token(authorization_header)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Expected: 'Authorization: Bearer <ID_TOKEN>'",
        )

    try:
        decoded = auth.verify_id_token(token)
        uid = decoded.get("uid")
        if not uid:
            raise ValueError("Token decoded but missing 'uid'")
        return uid
    except Exception as e:
        logging.warning(f"ID token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired ID token.",
        )


def verify_request_and_get_user(authorization_header: Optional[str]) -> dict:
    """
    Verify the Firebase ID token from the Authorization header and return basic user info.

    Returns:
        {"uid": <uid>, "email": <email or None>, "name": <name or None>}

    Raises HTTP 401 if missing/invalid.
    """
    _ensure_firebase_initialized()

    token = _extract_bearer_token(authorization_header)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Expected: 'Authorization: Bearer <ID_TOKEN>'",
        )

    try:
        decoded = auth.verify_id_token(token)
        uid = decoded.get("uid")
        if not uid:
            raise ValueError("Token decoded but missing 'uid'")

        # These may or may not be present depending on provider and token contents.
        email = decoded.get("email")
        name = decoded.get("name")

        return {"uid": uid, "email": email, "name": name}
    except Exception as e:
        logging.warning(f"ID token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired ID token.",
        )


# Optional FastAPI-friendly dependency you can use directly in route params:
async def require_user_id(authorization: Optional[str] = Header(None)) -> str:
    """
    FastAPI dependency that returns the verified uid, or 401s if invalid.
    Usage in a route:
        @router.post("/something")
        def handler(user_id: str = Depends(require_user_id)):
            ...
    """
    return verify_request_and_get_uid(authorization)