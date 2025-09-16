# ATutor/profile_routes.py
# Minimal profile API for the app:
# - GET  /users/me     → fetch my profile (name, XP, tier+name, group, friends count, devices if any)
# - PATCH /users/me     → update my displayName/username (only these fields)
#
# Notes:
# • Requires Firebase ID token in "Authorization: Bearer <ID_TOKEN>".
# • Reads/writes the user doc at:   users/{uid}
# • Devices (if your app records them) are read from: users/{uid}/devices/*

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from firebase_admin import firestore

from auth_utils import require_user_id
from utils import FirebaseManager
from constants import clamp_tier_id, TIER_ID_TO_NAME

router = APIRouter(prefix="/users", tags=["users"])

_firebase = FirebaseManager()


# ======= Request / Response Models =======

class ProfileUpdateRequest(BaseModel):
    # Either/both may be provided
    displayName: Optional[str] = Field(default=None, max_length=64)
    username: Optional[str] = Field(default=None, max_length=32)


# ======= Helpers =======

def _safe_str(v: Any, default: str = "") -> str:
    return str(v).strip() if isinstance(v, str) else default

def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default

def _serialize_ts(ts: Any) -> Optional[str]:
    # Convert Firestore timestamp/datetime to ISO8601 string if present, else None
    try:
        return ts.isoformat() if ts else None
    except Exception:
        return None

def _build_profile_payload(uid: str, user_doc: Dict[str, Any], devices: List[Dict[str, Any]]) -> Dict[str, Any]:
    tier_id_raw = user_doc.get("tierID", 0)
    tier_id = clamp_tier_id(_safe_int(tier_id_raw, 0))
    tier_name = TIER_ID_TO_NAME.get(tier_id, "Broccoli")

    payload = {
        "userID": uid,
        "displayName": _safe_str(user_doc.get("displayName"), _safe_str(user_doc.get("username"), "Player")),
        "username": _safe_str(user_doc.get("username"), ""),
        "totalXP": _safe_int(user_doc.get("totalXP"), 0),
        "tierID": tier_id,
        "tierName": tier_name,
        "groupID": _safe_int(user_doc.get("groupID"), 0),
        "currentStreak": _safe_int(user_doc.get("currentStreak"), 0),
        "timeSpentInSeconds": _safe_int(user_doc.get("timeSpentInSeconds"), 0),
        "friendsCount": len(user_doc.get("friends", []) or []),
        "lastLoginDate": _serialize_ts(user_doc.get("lastLoginDate")),
        "devices": devices,  # [{'id': '...', 'name': '...', 'model': '...', 'lastSeenAt': '...'}]
    }
    return payload


def _read_devices_for(uid: str, db) -> List[Dict[str, Any]]:
    try:
        # Optional subcollection; ok if it doesn't exist
        docs = db.collection("users").document(uid).collection("devices").limit(20).get()
    except Exception:
        return []
    items: List[Dict[str, Any]] = []
    for d in docs:
        data = d.to_dict() or {}
        items.append({
            "id": d.id,
            "name": _safe_str(data.get("name"), ""),
            "model": _safe_str(data.get("model"), ""),
            "lastSeenAt": _serialize_ts(data.get("lastSeenAt")),
        })
    return items


# ======= Routes =======

@router.get("/me")
async def get_me(user_id: str = Depends(require_user_id)) -> Dict[str, Any]:
    """
    Return the caller's profile.
    Shape:
    {
      "user": {
        "userID": "...",
        "displayName": "...",
        "username": "...",
        "totalXP": 0,
        "tierID": 2,
        "tierName": "Banana",
        "groupID": 3,
        "currentStreak": 0,
        "timeSpentInSeconds": 0,
        "friendsCount": 2,
        "lastLoginDate": "2025-09-12T10:15:00Z",
        "devices": [{"id":"...", "name":"iPad", "model":"iPad Pro 12.9", "lastSeenAt":"..."}]
      }
    }
    """
    db = _firebase.get_db_client()
    doc = db.collection("users").document(user_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")

    user_data = doc.to_dict() or {}
    devices = _read_devices_for(user_id, db)
    return {"user": _build_profile_payload(user_id, user_data, devices)}


@router.patch("/me")
async def update_me(body: ProfileUpdateRequest, user_id: str = Depends(require_user_id)) -> Dict[str, Any]:
    """
    Update the caller's profile (ONLY displayName/username).
    Returns the updated profile in the same shape as GET /users/me.
    """
    updates: Dict[str, Any] = {}
    # Normalize inputs (trim whitespace)
    if body.displayName is not None:
        name = _safe_str(body.displayName)
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="displayName cannot be empty")
        updates["displayName"] = name

    if body.username is not None:
        uname = _safe_str(body.username)
        if not uname:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="username cannot be empty")
        # (Optional) Very light sanity check; leave true uniqueness policy to later
        if len(uname) > 32:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="username too long")
        updates["username"] = uname

    if not updates:
        # Nothing to change; return current profile
        return await get_me(user_id)  # type: ignore

    db = _firebase.get_db_client()
    user_ref = db.collection("users").document(user_id)

    # Ensure the doc exists before update
    doc = user_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")

    try:
        # Add a lightweight updatedAt; Firestore server timestamp if available
        updates["updatedAt"] = firestore.SERVER_TIMESTAMP
        user_ref.update(updates)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update profile: {e}")

    # Return the fresh profile
    return await get_me(user_id)  # type: ignore
