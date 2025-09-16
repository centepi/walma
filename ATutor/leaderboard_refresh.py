# ATutor/leaderboard_refresh.py
# Periodic reshuffle + tier rotation script aligned to the 5-tier scheme.
# Uses the shared constants and FirebaseManager so it stays in sync with the app.

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List

from utils import FirebaseManager
from constants import TIERS, GROUP_SIZE

# Firestore client (requires project_id, client_email, private_key env vars)
db = FirebaseManager().get_db_client()


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _to_datetime(value: Any) -> datetime:
    """Coerce Firestore Timestamp/ISO string/datetime to datetime for comparisons."""
    if value is None:
        return datetime.min
    if isinstance(value, datetime):
        return value
    try:
        # Firestore Timestamp compatibility (has .isoformat / .timestamp via datetime)
        return value.to_datetime()  # type: ignore[attr-defined]
    except Exception:
        pass
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return datetime.min
    return datetime.min


def get_promotion_demotion_counts(tier_id: int) -> (int, int):
    """
    Promotion/demotion counts per group for the 5-tier model (0..4).

    Simple policy:
      - Bottom tier (0): promote 10, demote 0
      - Top tier (4):    promote 0,  demote 10
      - Middle tiers:    promote decreases as you go up; demote increases
        (mirrors the previous intent but bounded to 5 tiers)
    """
    top_index = len(TIERS) - 1
    if tier_id <= 0:
        return 10, 0
    if tier_id >= top_index:
        return 0, 10
    # Middle tiers (1..3)
    promote = max(1, 10 - tier_id - 1)  # 1:8, 2:7, 3:6
    demote = max(1, 3 + (tier_id - 1) + 1)  # 1:4, 2:5, 3:6
    return promote, demote


def get_all_users_grouped() -> Dict[int, List[Dict[str, Any]]]:
    """Get all users grouped by tier with lastLoginDate normalized to datetime."""
    all_users = db.collection("users").get()
    tier_users: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

    for user_doc in all_users:
        user_data = user_doc.to_dict() or {}
        tier_id = _safe_int(user_data.get("tierID"), 0)
        user_data["lastLoginDateTime"] = _to_datetime(user_data.get("lastLoginDate"))
        user_data["userID"] = user_data.get("userID") or user_doc.id
        user_data["username"] = user_data.get("username") or "Player"
        user_data["totalXP"] = _safe_int(user_data.get("totalXP"), 0)
        tier_users[tier_id].append(user_data)

    return tier_users


def shuffle_users_by_activity(users: List[Dict[str, Any]], group_size: int = GROUP_SIZE) -> List[List[Dict[str, Any]]]:
    """
    Shuffle users into groups while keeping recently active users together.
    Recent = last 7 days. Within recent/inactive, sort by XP desc then by last seen (recent first).
    """
    now = datetime.now()
    recent_threshold = now - timedelta(days=7)

    recent_users = [u for u in users if _to_datetime(u["lastLoginDateTime"]) >= recent_threshold]
    inactive_users = [u for u in users if _to_datetime(u["lastLoginDateTime"]) < recent_threshold]

    # Sort: XP desc, then recent first
    recent_users.sort(key=lambda u: (-_safe_int(u["totalXP"], 0), -_to_datetime(u["lastLoginDateTime"]).timestamp()))
    inactive_users.sort(key=lambda u: (-_safe_int(u["totalXP"], 0), -_to_datetime(u["lastLoginDateTime"]).timestamp()))

    groups: List[List[Dict[str, Any]]] = []
    r_idx = 0
    i_idx = 0

    while r_idx < len(recent_users) or i_idx < len(inactive_users):
        group: List[Dict[str, Any]] = []

        # Up to 70% recent users
        recent_slots = min(int(group_size * 0.7), len(recent_users) - r_idx)
        for _ in range(recent_slots):
            if r_idx < len(recent_users):
                group.append(recent_users[r_idx])
                r_idx += 1

        # Fill remaining with inactive
        remaining = group_size - len(group)
        for _ in range(remaining):
            if i_idx < len(inactive_users):
                group.append(inactive_users[i_idx])
                i_idx += 1

        if group:
            groups.append(group)

    return groups


def batch_update_users(updates: List[Dict[str, Any]]) -> None:
    """Batch update users to avoid Firestore limits (500 ops per batch)."""
    if not updates:
        return

    batch = db.batch()
    count = 0

    for upd in updates:
        user_ref = db.collection("users").document(upd["user_id"])
        batch.update(user_ref, {"tierID": upd["tier_id"], "groupID": upd["group_id"]})
        count += 1
        if count >= 500:
            batch.commit()
            batch = db.batch()
            count = 0

    if count > 0:
        batch.commit()


def rotate_tiers() -> None:
    """Promote/demote and reshuffle groups across all 5 tiers."""
    print("Starting tier rotation with shuffling...")

    tier_users = get_all_users_grouped()
    all_updates: List[Dict[str, Any]] = []

    top_index = len(TIERS) - 1

    for tier_id in range(len(TIERS)):
        tier_name = TIERS[tier_id]["name"]
        users = tier_users.get(tier_id, [])

        if not users:
            print(f"No users in {tier_name} tier")
            continue

        print(f"Processing {tier_name} tier with {len(users)} users")

        # Shuffle users into new groups based on activity
        new_groups = shuffle_users_by_activity(users, GROUP_SIZE)

        promote_count, demote_count = get_promotion_demotion_counts(tier_id)

        promoted_users: List[Dict[str, Any]] = []
        demoted_users: List[Dict[str, Any]] = []
        staying_users: List[Dict[str, Any]] = []

        for group in new_groups:
            # Sort group by totalXP descending
            sorted_group = sorted(group, key=lambda u: _safe_int(u["totalXP"], 0), reverse=True)

            # Promotions (skip if top tier)
            group_promoted = 0
            if tier_id < top_index and promote_count > 0:
                to_promote = min(promote_count, len(sorted_group))
                promoted_users.extend(sorted_group[:to_promote])
                group_promoted = to_promote

            # Demotions (skip if bottom tier)
            group_demoted = 0
            if tier_id > 0 and demote_count > 0:
                # Demote from the bottom of the group, but don't collide with promoted slice
                available_for_demote = len(sorted_group) - group_promoted
                to_demote = min(demote_count, max(0, available_for_demote))
                if to_demote > 0:
                    demoted_users.extend(sorted_group[-to_demote:])
                    group_demoted = to_demote

            # Those who stay in current tier
            end_idx = len(sorted_group) - group_demoted if group_demoted > 0 else len(sorted_group)
            staying_segment = sorted_group[group_promoted:end_idx]
            staying_users.extend(staying_segment)

        # Repack staying users within current tier
        staying_groups = shuffle_users_by_activity(staying_users, GROUP_SIZE)
        for g_idx, group in enumerate(staying_groups):
            for user in group:
                all_updates.append({"user_id": user["userID"], "tier_id": tier_id, "group_id": g_idx})

        # Handle promotions → next tier
        if promoted_users and tier_id < top_index:
            target_tier_users = tier_users.get(tier_id + 1, [])
            combined = target_tier_users + promoted_users
            target_groups = shuffle_users_by_activity(combined, GROUP_SIZE)
            promoted_ids = {u["userID"] for u in promoted_users}
            for g_idx, group in enumerate(target_groups):
                for user in group:
                    if user["userID"] in promoted_ids:
                        all_updates.append({"user_id": user["userID"], "tier_id": tier_id + 1, "group_id": g_idx})
                        print(f"Promoting {user.get('username','Player')} to {TIERS[tier_id + 1]['name']}")

        # Handle demotions → previous tier
        if demoted_users and tier_id > 0:
            target_tier_users = tier_users.get(tier_id - 1, [])
            combined = target_tier_users + demoted_users
            target_groups = shuffle_users_by_activity(combined, GROUP_SIZE)
            demoted_ids = {u["userID"] for u in demoted_users}
            for g_idx, group in enumerate(target_groups):
                for user in group:
                    if user["userID"] in demoted_ids:
                        all_updates.append({"user_id": user["userID"], "tier_id": tier_id - 1, "group_id": g_idx})
                        print(f"Demoting {user.get('username','Player')} to {TIERS[tier_id - 1]['name']}")

    # Apply all updates
    if all_updates:
        print(f"Applying {len(all_updates)} updates...")
        batch_update_users(all_updates)
        print("Tier rotation and shuffling completed successfully!")
    else:
        print("No updates needed.")


if __name__ == "__main__":
    rotate_tiers()
