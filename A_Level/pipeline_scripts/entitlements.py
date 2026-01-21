# pipeline_scripts/entitlements.py
from typing import Dict, Any, Tuple
from firebase_admin import firestore

def _ref(db_client, uid: str):
    return (
        db_client.collection("Users")
                 .document(uid)
                 .collection("Entitlements")
                 .document("main")
    )

def try_consume_question_credit(
    db_client,
    *,
    uid: str,
    n: int = 1,
    default_free_cap: int = 30,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Atomically consume n credits (question creations) for uid.
    Returns (ok, info) where info includes cap/used/subscribed.
    """
    n = max(0, int(n))
    ref = _ref(db_client, uid)

    def txn_fn(txn):
        snap = ref.get(transaction=txn)
        if snap.exists:
            ent = snap.to_dict() or {}
        else:
            ent = {}

        cap = ent.get("free_question_cap")
        used = ent.get("questions_created_total")
        is_sub = bool(ent.get("is_subscribed", False))

        if not isinstance(cap, int):
            cap = int(default_free_cap)
        if not isinstance(used, int):
            used = 0

        # If subscribed, allow without consuming.
        if is_sub:
            # Still backfill defaults if missing
            txn.set(ref, {"free_question_cap": cap, "questions_created_total": used, "updated_at": firestore.SERVER_TIMESTAMP}, merge=True)
            return True, {"is_subscribed": True, "cap": cap, "used": used}

        # Not subscribed: enforce cap
        if used + n > cap:
            txn.set(ref, {"free_question_cap": cap, "questions_created_total": used, "updated_at": firestore.SERVER_TIMESTAMP}, merge=True)
            return False, {"is_subscribed": False, "cap": cap, "used": used}

        txn.set(
            ref,
            {
                "free_question_cap": cap,
                "questions_created_total": firestore.Increment(n),
                "updated_at": firestore.SERVER_TIMESTAMP,
                "created_at": ent.get("created_at") or firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        return True, {"is_subscribed": False, "cap": cap, "used": used + n}

    txn = db_client.transaction()
    ok, info = txn.call(txn_fn)
    return ok, info