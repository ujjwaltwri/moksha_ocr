"""Arq worker. Start with:  arq worker.WorkerSettings

Day 1: the API already queues one `process_registration` job per registration.
Day 2: replace the body of `process_registration` with the OCR pipeline
(quality check -> find card -> OCR -> identify college -> extract -> compare -> face crop -> phash -> verdict).

Until the pipeline exists, DON'T run this worker against production: it would
consume jobs and do nothing. Leave registrations queued, or re-queue them later
with scripts/enqueue_pending.py.
"""

import logging
import os

from arq.connections import RedisSettings

log = logging.getLogger("worker")


async def process_registration(ctx, registration_id: str) -> None:
    # TODO(day 2): set status=processing, run the pipeline, write ocr/reasons/photo_crop_key/
    # image_phash, then set approved / review / rejected. Keep any reasons already
    # present (e.g. duplicate_roll, other_college) - they come from registration time.
    raise NotImplementedError("OCR pipeline not built yet")


class WorkerSettings:
    functions = [process_registration]
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    max_jobs = int(os.environ.get("WORKER_CONCURRENCY", "4"))
    job_timeout = 120
    max_tries = 3
    keep_result = 0  # lets enqueue_pending re-queue a registration after a failed run
