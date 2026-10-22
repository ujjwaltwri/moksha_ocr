from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+asyncpg://moksha:moksha@localhost:5432/moksha"
    redis_url: str = "redis://localhost:6379/0"
    db_pool_size: int = 4                       # per API process; 2 processes x (4 + 4 overflow) = 16 connections max

    # S3-compatible storage (AWS S3, GCS interop, or MinIO locally)
    s3_bucket: str = "moksha-ids"
    s3_region: str = "ap-south-1"
    s3_endpoint_url: str | None = None          # set for MinIO / GCS
    s3_public_endpoint_url: str | None = None   # browser-facing endpoint, if different
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    upload_url_ttl_s: int = 600
    max_upload_bytes: int = 8 * 1024 * 1024

    # Abuse protection
    turnstile_secret: str | None = None         # unset = skip (dev only)
    turnstile_site_key: str | None = None       # public; the form needs it to show the widget
    rate_limit_per_ip_per_hour: int = 20

    # Consent text version shown on the form; bump whenever the wording changes
    consent_version: str = "2026-10-18.v1"

    # Origins allowed to call the API (the fest website hosting the form)
    cors_origins: list[str] = ["http://localhost:3000"]

    # Where the student's status page lives on the website. {token} is replaced.
    status_url_template: str = "http://localhost:3000/status/{token}"

    # Staff and gates
    admin_token: str | None = None              # bootstrap admin; creates reviewer, admin and device tokens
    api_public_url: str = "http://localhost:8000"  # what gate phones connect to (goes in the setup QR)
    event_id: str = "moksha26"                  # must match the gate app's EVENT_ID
    pass_public_key: str | None = None          # from scripts/gen_keys.py; included in the setup QR
    review_claim_minutes: int = 10              # a claimed case returns to the queue after this


@lru_cache
def get_settings() -> Settings:
    return Settings()
