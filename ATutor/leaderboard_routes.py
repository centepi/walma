# ATutor/leaderboard_routes.py
# FastAPI routes for leaderboard features (tiered + friends).
# Verifies the caller's Firebase ID token and forwards to the existing
# business logic functions in ATutor/leaderboard.py.

from typing import Any, Dict, List, Union

from fastapi import APIRouter, Depends, HTTPException, status

from auth_utils import require_user_id
from constants import TIERS, GROUP_SIZE
from leaderboard import tiered_leaderboard_desc, get_friend_leaderboard_desc
from utils import FirebaseManager

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])

# Use the existing Firebase singleton to get a Firestore client on demand.
_firebase_manager = FirebaseManager()


def _normalize_result(result: Union[List[Dict[str, Any]], Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Your leaderboard.py functions usually return a list on success,
    but may return {"status": "error", "message": "..."} on failure.
    Normalize to a list or raise an HTTP error.
    """
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and result.get("status") == "error":
        msg = result.get("message", "Unknown error")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)
    # Unexpected shape
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected leaderboard response")


@router.post("/tiered")
async def tiered_leaderboard(user_id: str = Depends(require_user_id)) -> Dict[str, Any]:
    """
    Return the caller's tier+group leaderboard:
    {
      "items": [
        {"rank": 1, "username": "...", "totalXP": 1234, "tierName": "Banana", "isCurrentUser": false},
        ...
      ]
    }
    """
    class _Req:
        def __init__(self, uid: str) -> None:
            self.user_id = uid

    result = tiered_leaderboard_desc(_Req(user_id), TIERS, GROUP_SIZE, _firebase_manager)
    items = _normalize_result(result)
    return {"items": items}


@router.post("/friends")
async def friends_leaderboard(user_id: str = Depends(require_user_id)) -> Dict[str, Any]:
    """
    Return the caller's friends leaderboard (plus self), ranked by XP:
    {
      "items": [
        {"rank": 1, "username": "...", "totalXP": 987, "tierName": "Cabbage", "isCurrentUser": true},
        ...
      ]
    }
    """
    class _Req:
        def __init__(self, uid: str) -> None:
            self.user_id = uid

    result = get_friend_leaderboard_desc(_Req(user_id), TIERS, GROUP_SIZE, _firebase_manager)
    items = _normalize_result(result)
    return {"items": items}
