"""External services behind small interfaces, so tests can swap them out."""

import time
from dataclasses import dataclass
from functools import lru_cache

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import ClientError
from redis.asyncio import Redis

from .config import get_settings


# ---------- Object storage ----------

@dataclass
class PresignedUpload:
    url: str
    fields: dict
    key: str


class Storage:
    def __init__(self) -> None:
        s = get_settings()
        common = dict(
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self.bucket = s.s3_bucket
        self.client = boto3.client("s3", endpoint_url=s.s3_endpoint_url, **common)
        # URLs handed to browsers must use the browser-reachable host.
        self.public = boto3.client("s3", endpoint_url=s.s3_public_endpoint_url or s.s3_endpoint_url, **common)

    def presign_upload(self, key: str, content_type: str, max_bytes: int, ttl_s: int) -> PresignedUpload:
        post = self.public.generate_presigned_post(
            Bucket=self.bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
            ExpiresIn=ttl_s,
        )
        return PresignedUpload(url=post["url"], fields=post["fields"], key=key)

    def object_size(self, key: str) -> int | None:
        """Size in bytes, or None if the object doesn't exist."""
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise


@lru_cache
def get_storage() -> Storage:
    return Storage()


# ---------- Redis: job queue + rate limits ----------

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url)
    return _redis


class JobQueue:
    """Enqueues OCR jobs for the Arq worker."""

    async def enqueue_ocr(self, registration_id: str) -> None:
        from arq.connections import ArqRedis

        arq = ArqRedis(connection_pool=get_redis().connection_pool)
        # _job_id makes re-enqueueing the same registration a no-op while one is queued.
        await arq.enqueue_job("process_registration", registration_id, _job_id=f"ocr:{registration_id}")


def get_queue() -> JobQueue:
    return JobQueue()


class RateLimiter:
    """Fixed-window counter per key. Fails open if Redis is down, so the form keeps working."""

    async def hit(self, key: str, limit: int, window_s: int = 3600) -> bool:
        bucket = f"rl:{key}:{int(time.time()) // window_s}"
        try:
            r = get_redis()
            n = await r.incr(bucket)
            if n == 1:
                await r.expire(bucket, window_s)
            return n <= limit
        except Exception:
            return True


def get_rate_limiter() -> RateLimiter:
    return RateLimiter()


# ---------- Cloudflare Turnstile ----------

class Captcha:
    async def verify(self, token: str | None, ip: str | None) -> bool:
        secret = get_settings().turnstile_secret
        if not secret:
            return True  # dev mode
        if not token:
            return False
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={"secret": secret, "response": token, "remoteip": ip or ""},
            )
        return bool(resp.json().get("success"))


def get_captcha() -> Captcha:
    return Captcha()
