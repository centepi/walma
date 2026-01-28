import os
import time
import json
import logging

import redis

# Optional: reuse your existing logger style
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alma-worker")


REDIS_URL = os.getenv("REDIS_URL")
QUEUE_NAME = "alma:jobs"


def main():
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL is not set")

    logger.info("Starting Alma worker")
    logger.info("Connecting to Redis…")

    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

    # Simple connectivity check
    r.ping()
    logger.info("Connected to Redis")

    logger.info("Waiting for jobs on queue '%s'", QUEUE_NAME)

    while True:
        try:
            # BLPOP blocks until a job is available
            _, raw_job = r.blpop(QUEUE_NAME)
            job = json.loads(raw_job)

            logger.info("Received job: %s", job.get("type"))

            # ---- PLACEHOLDER ----
            # We will plug real logic here next
            # ---------------------
            time.sleep(1)

            logger.info("Finished job")

        except Exception as e:
            logger.exception("Worker error")
            time.sleep(2)


if __name__ == "__main__":
    main()