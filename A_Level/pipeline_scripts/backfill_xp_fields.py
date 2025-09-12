import argparse
from pipeline_scripts import firebase_uploader
from pipeline_scripts.firebase_uploader import XP_TABLE, marks_to_difficulty
from pipeline_scripts.utils import setup_logger

logger = setup_logger(__name__)

def backfill(force: bool = False, topic_filter: list[str] | None = None, dry_run: bool = False):
    db = firebase_uploader.initialize_firebase()
    if not db:
        logger.error("Failed to init Firebase Admin.")
        return

    updated = 0
    scanned = 0
    batch = db.batch()
    batch_size = 0
    BATCH_LIMIT = 400  # keep below 500 to be safe

    def commit_batch():
        nonlocal batch, batch_size
        if batch_size > 0 and not dry_run:
            batch.commit()
        batch = db.batch()
        batch_size = 0

    topics_ref = db.collection("Topics")
    topics = topics_ref.stream()

    for topic in topics:
        topic_id = topic.id
        if topic_filter and topic_id not in topic_filter:
            continue

        qcoll = topic.reference.collection("Questions")
        for qdoc in qcoll.stream():
            scanned += 1
            data = qdoc.to_dict() or {}

            # Skip if nothing to do (unless --force)
            has_diff = "difficulty" in data and isinstance(data["difficulty"], int)
            has_xp   = "xp_base"   in data and isinstance(data["xp_base"], int)

            if not force and has_diff and has_xp:
                continue

            marks = int(data.get("total_marks", 0) or 0)
            d = marks_to_difficulty(marks)
            payload = {}

            if force or not has_diff:
                payload["difficulty"] = d
            if force or not has_xp:
                payload["xp_base"] = XP_TABLE.get(d, XP_TABLE[1])
            if "xp_curve_version" not in data or force:
                payload["xp_curve_version"] = 1

            if payload:
                if dry_run:
                    logger.info("[DRY RUN] Would update %s/%s with %s", topic_id, qdoc.id, payload)
                else:
                    batch.update(qdoc.reference, payload)
                    batch_size += 1
                    updated += 1
                    if batch_size >= BATCH_LIMIT:
                        commit_batch()

    commit_batch()
    logger.info("Backfill completed. Scanned: %d, Updated: %d (force=%s, dry_run=%s)", scanned, updated, force, dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill difficulty/xp_base onto existing question docs.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing difficulty/xp_base with new computed values.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Do not write; just log what would change.")
    parser.add_argument("--topics", nargs="*", default=None,
                        help="Optional list of topic IDs to limit the backfill (default: all).")
    args = parser.parse_args()

    backfill(force=args.force, topic_filter=args.topics, dry_run=args.dry_run)
