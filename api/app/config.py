from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+asyncpg://moksha:moksha@localhost:5432/moksha"
    redis_url: str = "redis://localhost:6379/0"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
