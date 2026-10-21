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
import smtplib

from arq import Retry, func
from arq.connections import RedisSettings
from botocore.config import Config

from pipeline import passes
from pipeline.decide import decide
from pipeline.run import run
from pipeline.types import CollegeInfo, RegInfo

log = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO)

FEST_DAY = date.fromisoformat(os.environ.get("FEST_DAY", "2026-10-24"))
PHASH_MAX_DISTANCE = int(os.environ.get("PHASH_MAX_DISTANCE", "6"))
MAX_TRIES = 3
EMAIL_TRIES = 6
EVENT_ID = os.environ.get("EVENT_ID", "moksha26")
EVENT_NAME = os.environ.get("EVENT_NAME", "Moksha 2026")
FEST_DAYS = [int(d) for d in os.environ.get("FEST_DAYS", "1,2,3").split(",") if d.strip()]
DAYS_LABEL = os.environ.get("FEST_DAYS_LABEL", "all fest days")
STATUS_URL_TEMPLATE = os.environ.get("STATUS_URL_TEMPLATE", "http://localhost:3000/status/{token}")
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
        if status == "approved":
            await enqueue(ctx, "issue_pass", registration_id, f"pass:{registration_id}")
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


async def enqueue(ctx, function: str, arg: str, job_id: str) -> None:
    redis = ctx.get("redis")
    if redis is not None:  # absent in unit tests
        await redis.enqueue_job(function, arg, _job_id=job_id)


# ---------- Passes ----------

async def issue_pass(ctx, registration_id: str) -> str:
    """Create the pass for an approved registration: signed token + gate thumbnail. Then email it."""
    pool, s3, bucket = ctx["db"], ctx["s3"], ctx["bucket"]
    reg = await pool.fetchrow("select status, photo_crop_key from registrations where id = $1", registration_id)
    if reg is None or reg["status"] != "approved":
        return "skipped"
    p = await pool.fetchrow(
        """insert into passes (registration_id, days) values ($1, $2)
           on conflict (registration_id) do update set registration_id = excluded.registration_id
           returning id, token, email_sent_at""", registration_id, FEST_DAYS)
    if p["token"] is None:
        thumb = None
        if reg["photo_crop_key"]:
            face = await asyncio.to_thread(
                lambda: s3.get_object(Bucket=bucket, Key=reg["photo_crop_key"])["Body"].read())
            thumb = passes.gate_thumb(face)
        token = passes.sign_pass(ctx["signing_key"], str(p["id"]), EVENT_ID, FEST_DAYS)
        await pool.execute("update passes set token = $2, thumb = $3, days = $4 where id = $1",
                           p["id"], token, thumb, FEST_DAYS)
        await pool.execute(
            "insert into audit_log (actor, action, target) values ('worker', 'pass.issued', $1)", registration_id)
        log.info("%s -> pass %s issued (thumb %s)", registration_id, p["id"], "yes" if thumb else "none")
    if p["email_sent_at"] is None:
        await enqueue(ctx, "send_pass_email", registration_id, f"email:{registration_id}")
    return str(p["id"])


def _smtp_send(msg) -> None:
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise RuntimeError("SMTP_HOST is not set")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user, password = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with cls(host, port, timeout=30) as smtp:
        if port != 465 and os.environ.get("SMTP_STARTTLS", "true").lower() != "false":
            smtp.starttls()
        if user:
            smtp.login(user, password or "")
        smtp.send_message(msg)


async def send_pass_email(ctx, registration_id: str) -> str:
    pool = ctx["db"]
    r = await pool.fetchrow("""
        select r.name, r.email, r.status_token, r.status, coalesce(c.name, r.college_other, '') as college,
               p.id as pass_id, p.token, p.revoked
        from registrations r join passes p on p.registration_id = r.id
        left join colleges c on c.id = r.college_id
        where r.id = $1""", registration_id)
    if r is None or r["token"] is None or r["revoked"] or r["status"] != "approved":
        return "skipped"
    msg = passes.pass_email(
        to=r["email"], sender=os.environ.get("SMTP_FROM", "Moksha <passes@example.com>"),
        reply_to=os.environ.get("SMTP_REPLY_TO") or None,
        name=r["name"], college=r["college"], token=r["token"], event_name=EVENT_NAME, days_label=DAYS_LABEL,
        status_url=STATUS_URL_TEMPLATE.format(token=r["status_token"]))
    try:
        await asyncio.to_thread(ctx.get("send_mail", _smtp_send), msg)
    except smtplib.SMTPRecipientsRefused as e:  # bad address: retrying won't help
        await pool.execute("update passes set email_attempts = email_attempts + 1, email_error = $2 where id = $1",
                           r["pass_id"], f"address refused: {e}"[:300])
        return "refused"
    except Exception as e:
        await pool.execute("update passes set email_attempts = email_attempts + 1, email_error = $2 where id = $1",
                           r["pass_id"], f"{type(e).__name__}: {e}"[:300])
        tries = ctx.get("job_try", 1)
        if tries < EMAIL_TRIES:
            raise Retry(defer=min(30 * 2 ** tries, 1800))
        log.error("giving up emailing %s: %s", registration_id, e)
        return "failed"
    await pool.execute(
        "update passes set email_sent_at = now(), email_attempts = email_attempts + 1, email_error = null where id = $1",
        r["pass_id"])
    return "sent"


async def startup(ctx):
    ctx["db"] = await asyncpg.create_pool(_dsn(), min_size=1, max_size=5)
    ctx["s3"] = _s3()
    ctx["bucket"] = os.environ.get("S3_BUCKET", "moksha-ids")
    key = os.environ.get("PASS_SIGNING_KEY")
    if not key:
        raise RuntimeError("PASS_SIGNING_KEY is not set (run scripts/gen_keys.py once and put it in .env)")
    ctx["signing_key"] = passes.load_key(key)
    # Load the OCR model now, not on the first student's card.
    from pipeline import ocr
    import numpy as np

    await asyncio.to_thread(ocr.read, np.full((64, 64, 3), 255, np.uint8))


async def shutdown(ctx):
    await ctx["db"].close()


class WorkerSettings:
    functions = [process_registration, issue_pass, func(send_pass_email, max_tries=EMAIL_TRIES)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    max_jobs = int(os.environ.get("WORKER_CONCURRENCY", "2"))  # OCR is serialised per process; run more processes to scale
    job_timeout = 120
    max_tries = MAX_TRIES
    keep_result = 0  # lets enqueue_pending re-queue a registration after a failed run
