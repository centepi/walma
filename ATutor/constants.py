# ATutor/constants.py
# Single source of truth for leaderboard tiers and group size.

from typing import Dict, List

# Five playful tiers, low → high
TIERS: List[Dict[str, object]] = [
    {"id": 0, "name": "Broccoli"},
    {"id": 1, "name": "Cabbage"},
    {"id": 2, "name": "Banana"},
    {"id": 3, "name": "Strawberry"},
    {"id": 4, "name": "Apple"},
]

# How many users per group within a tier
GROUP_SIZE: int = 20

# Convenience lookups (optional but handy)
TIER_ID_TO_NAME = {t["id"]: t["name"] for t in TIERS}
VALID_TIER_IDS = set(TIER_ID_TO_NAME.keys())

def clamp_tier_id(tier_id: int) -> int:
    """Clamp any incoming tier_id to the valid 0–4 range."""
    if tier_id < 0:
        return 0
    max_id = max(VALID_TIER_IDS)
    if tier_id > max_id:
        return max_id
    return tier_id

def tier_name_for(tier_id: int) -> str:
    """Safe tier name lookup (auto-clamps out-of-range ids)."""
    return TIER_ID_TO_NAME.get(clamp_tier_id(tier_id), "Broccoli")
