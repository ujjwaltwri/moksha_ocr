"""Arq worker: one `process_registration` job per registration.

    cd worker && arq worker.WorkerSettings

Steps: load the registration -> download the card -> run the pipeline -> check for a reused
card image -> upload the face crop -> save the verdict. Passes are issued on day 3.
"""

import asyncio
import json
import logging
import os
import time
from datetime import date

import asyncpg
import boto3
from arq.connections import RedisSettings
from botocore.config import Config

from pipeline.decide import decide
from pipeline.run import run
from pipeline.types import CollegeInfo, RegInfo

log = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO)

FEST_DAY = date.fromisoformat(os.environ.get("FEST_DAY", "2026-10-24"))
PHASH_MAX_DISTANCE = int(os.environ.get("PHASH_MAX_DISTANCE", "6"))
MAX_TRIES = 3
_colleges: tuple[float, list[CollegeInfo]] = (0.0, [])


def _dsn() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://moksha:moksha@localhost:5432/moksha").replace(
        "postgresql+asyncpg://", "postgresql://")


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
        region_name=os.environ.get("S3_REGION", "ap-south-1"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


async def colleges(pool) -> list[CollegeInfo]:
    """All colleges, refreshed every 5 minutes so template edits apply without a restart."""
    global _colleges
    if time.monotonic() - _colleges[0] > 300:
        rows = await pool.fetch("select id, name, aliases, email_domains, roll_regex, template, allowed from colleges")
        _colleges = (time.monotonic(), [
            CollegeInfo(id=r["id"], name=r["name"], aliases=list(r["aliases"]), email_domains=list(r["email_domains"]),
                        roll_regex=r["roll_regex"], template=json.loads(r["template"]) if r["template"] else None,
                        allowed=r["allowed"])
            for r in rows
        ])
    return _colleges[1]


async def process_registration(ctx, registration_id: str) -> str:
    pool, s3, bucket = ctx["db"], ctx["s3"], ctx["bucket"]
    row = await pool.fetchrow(
        """update registrations set status = 'processing', updated_at = now()
           where id = $1 and (status in ('pending', 'processing') or (status = 'review' and ocr is null))
           returning id, name, roll_no, college_id, college_email, reasons, status""",
        registration_id,
    )
    if row is None:
        return "skipped"  # already decided, or not found

    try:
        all_colleges = await colleges(pool)
        chosen = next((c for c in all_colleges if c.id == row["college_id"]), None)
        reg = RegInfo(id=str(row["id"]), name=row["name"], roll_no=row["roll_no"], college_id=row["college_id"],
                      college_email=row["college_email"], reasons=list(row["reasons"]))
        key = await pool.fetchval("select id_image_key from registrations where id = $1", registration_id)
        data = await asyncio.to_thread(lambda: s3.get_object(Bucket=bucket, Key=key)["Body"].read())

        result = await asyncio.to_thread(run, data, reg, chosen, all_colleges)

        dup = None
        if result.phash is not None:  # same portrait on another registration = the same card reused
            dup = await pool.fetchval(
                """select id from registrations
                   where id <> $1 and image_phash is not null
                     and bit_count((image_phash # $2)::bit(64)) <= $3
                   limit 1""",
                registration_id, result.phash, PHASH_MAX_DISTANCE,
            )
        result.checks.duplicate_card = dup is not None

        face_key = None
        if result.face_jpeg:
            face_key = f"faces/{registration_id}.jpg"
            await asyncio.to_thread(s3.put_object, Bucket=bucket, Key=face_key, Body=result.face_jpeg,
                                    ContentType="image/jpeg")

        status, reasons = decide(reg, chosen, result.checks, FEST_DAY)
        ocr = dict(result.ocr, duplicate_of=str(dup) if dup else None)

        async with pool.acquire() as conn, conn.transaction():
            # Reasons can be added while we worked (e.g. someone else registered the same roll number).
            current = await conn.fetchval("select reasons from registrations where id = $1 for update", registration_id)
            reasons = sorted(set(reasons) | set(current or []))
            if status == "approved" and reasons:
                status = "review"
            await conn.execute(
                """update registrations set status = $2, reasons = $3, ocr = $4::jsonb, photo_crop_key = $5,
                       image_phash = $6, updated_at = now() where id = $1""",
                registration_id, status, reasons, json.dumps(ocr), face_key, result.phash,
            )
            if dup:  # flag the earlier registration too, so reviewers see both
                await conn.execute(
                    """update registrations set reasons = array_append(reasons, 'duplicate_card')
                       where id = $1 and not ('duplicate_card' = any(reasons))""", dup)
            await conn.execute(
                "insert into audit_log (actor, action, target, detail) values ('worker', 'registration.verdict', $1, $2::jsonb)",
                registration_id, json.dumps({"status": status, "reasons": reasons, "ms": ocr["ms"]}),
            )
        log.info("%s -> %s %s (%d ms)", registration_id, status, reasons, ocr["ms"])
        return status

    except Exception:
        log.exception("processing failed for %s (try %s)", registration_id, ctx.get("job_try"))
        if ctx.get("job_try", 1) >= MAX_TRIES:
            # Give up and hand it to a person rather than leaving it stuck.
            await pool.execute(
                """update registrations set status = 'review',
                       reasons = array_append(array_remove(reasons, 'processing_error'), 'processing_error'),
                       updated_at = now() where id = $1""", registration_id)
            return "review"
        raise


async def startup(ctx):
    ctx["db"] = await asyncpg.create_pool(_dsn(), min_size=1, max_size=5)
    ctx["s3"] = _s3()
    ctx["bucket"] = os.environ.get("S3_BUCKET", "moksha-ids")
    # Load the OCR model now, not on the first student's card.
    from pipeline import ocr
    import numpy as np

    await asyncio.to_thread(ocr.read, np.full((64, 64, 3), 255, np.uint8))


async def shutdown(ctx):
    await ctx["db"].close()


class WorkerSettings:
    functions = [process_registration]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    max_jobs = int(os.environ.get("WORKER_CONCURRENCY", "2"))  # OCR is serialised per process; run more processes to scale
    job_timeout = 120
    max_tries = MAX_TRIES
    keep_result = 0  # lets enqueue_pending re-queue a registration after a failed run
