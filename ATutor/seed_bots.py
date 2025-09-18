#!/usr/bin/env python3
import os
import sys
import argparse
import random
import string
from datetime import datetime
from typing import List

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name(".env"))

# Try to reuse your FirebaseManager if possible
DB = None
def init_db():
    global DB
    try:
        sys.path.append(os.path.join(os.path.dirname(__file__), "..", "ATutor"))
        from utils import FirebaseManager  # your singleton wrapper
        fm = FirebaseManager()
        fm.initialize()
        DB = fm.get_db_client()
        return
    except Exception as e:
        print("[seed_bots] Falling back to direct firebase_admin init:", e)

    # Fallback: init directly from env (same vars your app uses)
    import firebase_admin
    from firebase_admin import credentials, firestore

    project_id = os.getenv("project_id")
    client_email = os.getenv("client_email")
    private_key = os.getenv("private_key", "").replace("\\n", "\n")

    if not all([project_id, client_email, private_key]):
        raise RuntimeError("Missing project_id / client_email / private_key env vars")

    cred = credentials.Certificate({
        "type": "service_account",
        "project_id": project_id,
        "private_key_id": "<your-private-key-id>",
        "private_key": private_key,
        "client_email": client_email,
        "client_id": "<your-client-id>",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": "<your-client-cert-url>",
    })
    app = firebase_admin.initialize_app(cred)
    DB = firestore.client()

def rand_id(n=12):
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))

def seed_bots(count: int,
              tier_id: int,
              group_id: int,
              xp_min: int,
              xp_max: int,
              prefix: str,
              friends_of: str = None,
              mutual: bool = False):
    from firebase_admin import firestore as fs

    print(f"[seed_bots] Seeding {count} bots into tier {tier_id}, group {group_id}...")
    batch = DB.batch()
    batch_ops = 0
    bot_ids: List[str] = []

    # Create bots with staggered XP so you get a nice ladder
    for i in range(1, count + 1):
        doc_id = f"bot_{prefix.lower()}_{rand_id(10)}"
        bot_ids.append(doc_id)

        username = f"{prefix} {i:02d}"
        total_xp = random.randint(xp_min, xp_max)

        doc_ref = DB.collection("users").document(doc_id)
        data = {
            "userID": doc_id,
            "username": username,
            "displayName": username,
            "tierID": int(tier_id),
            "groupID": int(group_id),
            "totalXP": int(total_xp),
            "currentStreak": random.randint(0, 5),
            "timeSpentInSeconds": random.randint(0, 3600),
            "lastLoginDate": fs.SERVER_TIMESTAMP,
            "friends": [],
        }
        batch.set(doc_ref, data)
        batch_ops += 1

        # Commit in chunks (Firestore batch limit = 500)
        if batch_ops >= 450:
            batch.commit()
            print(f"[seed_bots] Committed 450 ops…")
            batch = DB.batch()
            batch_ops = 0

    if batch_ops > 0:
        batch.commit()

    print(f"[seed_bots] Created {len(bot_ids)} bots.")

    # Optionally add them to your friends list (so Friends tab populates)
    if friends_of:
        print(f"[seed_bots] Adding {len(bot_ids)} bots to friends of {friends_of} (mutual={mutual})")
        user_ref = DB.collection("users").document(friends_of)
        user_ref.update({"friends": fs.ArrayUnion(bot_ids)})

        if mutual:
            # Make friendship mutual (not required for your current friends leaderboard)
            for bid in bot_ids:
                DB.collection("users").document(bid).update({"friends": fs.ArrayUnion([friends_of])})

    print("[seed_bots] Done.")

def main():
    parser = argparse.ArgumentParser(description="Seed bot users for leaderboard testing.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tier", type=int, help="Tier ID to place bots into (0..4)")
    parser.add_argument("--group", type=int, help="Group ID to place bots into")
    source.add_argument("--mirror-user", type=str, help="Mirror this user's tierID+groupID (e.g., your UID)")

    parser.add_argument("--count", type=int, default=15, help="How many bots to create (default 15)")
    parser.add_argument("--xp-min", type=int, default=80, help="Minimum XP (default 80)")
    parser.add_argument("--xp-max", type=int, default=600, help="Maximum XP (default 600)")
    parser.add_argument("--prefix", type=str, default="Bot", help='Username/displayName prefix (default "Bot")')

    parser.add_argument("--friends-of", type=str, help="UID to add all bots into `friends` array for this user")
    parser.add_argument("--mutual", action="store_true", help="Also add this user into each bot's friends (optional)")

    args = parser.parse_args()

    init_db()

    # Resolve tier/group
    t_id = args.tier
    g_id = args.group
    if args.mirror_user:
        snap = DB.collection("users").document(args.mirror_user).get()
        if not snap.exists:
            raise SystemExit(f"[seed_bots] mirror-user={args.mirror_user} not found in users")
        u = snap.to_dict()
        t_id = u.get("tierID", 0)
        g_id = u.get("groupID", 0)
        print(f"[seed_bots] Mirroring user {args.mirror_user}: tierID={t_id}, groupID={g_id}")
    else:
        if t_id is None or g_id is None:
            raise SystemExit("[seed_bots] --tier and --group are required when not using --mirror-user")

    if args.xp_min > args.xp_max:
        args.xp_min, args.xp_max = args.xp_max, args.xp_min

    seed_bots(count=args.count,
              tier_id=t_id,
              group_id=g_id,
              xp_min=args.xp_min,
              xp_max=args.xp_max,
              prefix=args.prefix,
              friends_of=args.friends_of,
              mutual=args.mutual)

if __name__ == "__main__":
    main()