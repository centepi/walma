# ATutor/leaderboard.py
# Business logic for leaderboards (tier/group and friends).
# This module intentionally contains NO FastAPI routing — routes live in leaderboard_routes.py.
# It expects a FirebaseManager instance to be passed in, and a TIERS list/GROUP_SIZE from constants.

import logging
from typing import Any, Dict, List

from firebase_admin import firestore


def _safe_str(v: Any, default: str = "") -> str:
    return str(v).strip() if isinstance(v, str) else default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _tier_name_for(tiers: List[Dict[str, Any]], raw_tier_id: Any) -> str:
    """Map a raw tierID to a safe tier name using the provided TIERS list."""
    tier_id = _safe_int(raw_tier_id, 0)
    # Build lookup once (small list; cost negligible)
    id_to_name = {t.get("id"): t.get("name") for t in tiers}
    if tier_id in id_to_name:
        return id_to_name[tier_id]
    if not id_to_name:
        return "Broccoli"  # ultra-safe fallback
    # Clamp to nearest valid by id range
    min_id = min(id_to_name.keys())
    max_id = max(id_to_name.keys())
    clamped = min_id if tier_id < min_id else max_id
    return id_to_name.get(clamped, "Broccoli")


def tiered_leaderboard_desc(request, TIERS, GROUP_SIZE, firebase_manager):
    """
    Get leaderboard for the caller's current tier and group.

    Returns a list of dict items:
      {
        'rank': int,
        'username': str,
        'totalXP': int,
        'tierName': str,
        'isCurrentUser': bool
      }
    On error, returns {"status": "error", "message": "..."}.
    """
    try:
        db = firebase_manager.get_db_client()
        user_doc = db.collection("users").document(request.user_id).get()
        if not user_doc.exists:
            return []

        me = user_doc.to_dict() or {}
        tier_id = _safe_int(me.get("tierID"), 0)
        group_id = _safe_int(me.get("groupID"), 0)
        tier_name = _tier_name_for(TIERS, tier_id)

        # Fetch peers in same tier+group, sorted by XP desc
        users = (
            db.collection("users")
            .where("tierID", "==", tier_id)
            .where("groupID", "==", group_id)
            .order_by("totalXP", direction=firestore.Query.DESCENDING)
            .get()
        )

        leaderboard: List[Dict[str, Any]] = []
        for i, doc in enumerate(users):
            row = doc.to_dict() or {}
            leaderboard.append(
                {
                    "rank": i + 1,
                    "username": _safe_str(row.get("username"), "Player"),
                    "totalXP": _safe_int(row.get("totalXP"), 0),
                    "tierName": tier_name,  # all in the same tier/group by query
                    "isCurrentUser": _safe_str(row.get("userID")) == _safe_str(request.user_id),
                }
            )

        return leaderboard
    except Exception as e:
        logging.error(f"Leaderboard (tiered) query failed: {e}")
        return {"status": "error", "message": "Database operation failed"}


def get_friend_leaderboard_desc(request, TIERS, GROUP_SIZE, firebase_manager):
    """
    Get leaderboard among the caller's friends (plus self), ranked by XP desc.

    Returns a list of dict items:
      {
        'rank': int,
        'username': str,
        'totalXP': int,
        'tierName': str,
        'isCurrentUser': bool
      }
    On error, returns {"status": "error", "message": "..."}.
    """
    try:
        db = firebase_manager.get_db_client()
        me_doc = db.collection("users").document(request.user_id).get()
        if not me_doc.exists:
            return []

        me = me_doc.to_dict() or {}
        # Start with friends from the doc, then add self, and deduplicate
        friend_ids = set((me.get("friends") or []))
        friend_ids.add(_safe_str(request.user_id))

        leaderboard: List[Dict[str, Any]] = []
        for fid in friend_ids:
            if not fid:
                continue
            fdoc = db.collection("users").document(fid).get()
            if not fdoc.exists:
                continue
            f = fdoc.to_dict() or {}
            tier_name = _tier_name_for(TIERS, f.get("tierID"))
            leaderboard.append(
                {
                    "username": _safe_str(f.get("username"), "Player"),
                    "totalXP": _safe_int(f.get("totalXP"), 0),
                    "tierName": tier_name,
                    "isCurrentUser": _safe_str(fid) == _safe_str(request.user_id),
                }
            )

        # Sort by XP desc
        leaderboard.sort(key=lambda x: x["totalXP"], reverse=True)

        # Assign ranks
        for i, item in enumerate(leaderboard):
            item["rank"] = i + 1

        return leaderboard
    except Exception as e:
        logging.error(f"Leaderboard (friends) query failed: {e}")
        return {"status": "error", "message": "Database operation failed"}
