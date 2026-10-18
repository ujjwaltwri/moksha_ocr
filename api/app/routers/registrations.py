import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..consent import CONSENT_DATASET, CONSENT_ENTRY
from ..db import get_session
from ..models import LIVE_STATUSES, AuditLog, College, Registration, RegStatus
from ..schemas import (
    ALLOWED_TYPES,
    REASON_TEXT,
    STATUS_TEXT,
    CollegeOut,
    FormConfigOut,
    PresignIn,
    PresignOut,
    RegistrationIn,
    RegistrationOut,
    ReuploadIn,
    StatusOut,
)
from ..services import Captcha, JobQueue, RateLimiter, Storage, get_captcha, get_queue, get_rate_limiter, get_storage

log = logging.getLogger(__name__)
router = APIRouter()

REUPLOAD_REASONS = {"poor_image", "no_face"}


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def email_matches_college(email: str, college: College | None) -> bool:
    if college is None:
        return False
    domain = email.rsplit("@", 1)[-1].lower()
    return any(domain == d.lower() or domain.endswith("." + d.lower()) for d in college.email_domains)


async def require_uploaded(storage: Storage, key: str, settings: Settings) -> None:
    size = storage.object_size(key)
    if size is None:
        raise HTTPException(422, "We didn't receive your ID card photo. Please upload it again.")
    if size > settings.max_upload_bytes:
        raise HTTPException(422, "Your photo is larger than 8 MB.")


@router.get("/form-config", response_model=FormConfigOut)
async def form_config(settings: Settings = Depends(get_settings)):
    """Everything the registration form needs that might change: consent wording, captcha key, limits."""
    return FormConfigOut(
        consent_version=settings.consent_version,
        consent_entry_text=CONSENT_ENTRY,
        consent_dataset_text=CONSENT_DATASET,
        turnstile_site_key=settings.turnstile_site_key,
        max_upload_bytes=settings.max_upload_bytes,
        allowed_content_types=sorted(ALLOWED_TYPES),
        min_image_long_side_px=1000,
    )


@router.get("/colleges", response_model=list[CollegeOut])
async def list_colleges(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(College).where(College.allowed).order_by(College.name))
    return [CollegeOut(id=c.id, name=c.name) for c in rows]


@router.post("/uploads/presign", response_model=PresignOut)
async def presign_upload(
    body: PresignIn,
    request: Request,
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    if body.size > settings.max_upload_bytes:
        raise HTTPException(422, "Your photo is larger than 8 MB.")
    if not await limiter.hit(f"presign:{client_ip(request)}", settings.rate_limit_per_ip_per_hour * 3):
        raise HTTPException(429, "Too many attempts. Please try again in a while.")
    key = f"id-cards/{uuid.uuid4()}.{ALLOWED_TYPES[body.content_type]}"
    up = storage.presign_upload(key, body.content_type, settings.max_upload_bytes, settings.upload_url_ttl_s)
    return PresignOut(url=up.url, fields=up.fields, key=up.key, expires_in=settings.upload_url_ttl_s)


@router.post("/registrations", response_model=RegistrationOut, status_code=201)
async def create_registration(
    body: RegistrationIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    queue: JobQueue = Depends(get_queue),
    limiter: RateLimiter = Depends(get_rate_limiter),
    captcha: Captcha = Depends(get_captcha),
):
    ip = client_ip(request)
    if not await captcha.verify(body.captcha_token, ip):
        raise HTTPException(400, "Captcha check failed. Please try again.")
    if not await limiter.hit(f"reg:ip:{ip}", settings.rate_limit_per_ip_per_hour):
        raise HTTPException(429, "Too many registrations from this network. Please try again later.")
    if body.consent_version != settings.consent_version:
        raise HTTPException(409, "The form has been updated. Please reload the page and submit again.")

    college = None
    if body.college_id is not None:
        college = await session.get(College, body.college_id)
        if college is None or not college.allowed:
            raise HTTPException(422, "That college isn't part of this year's Moksha.")

    await require_uploaded(storage, body.id_image_key, settings)

    if await session.scalar(select(Registration.id).where(func.lower(Registration.email) == body.email.lower())):
        raise HTTPException(
            409, "This email is already registered. Use the status link from your confirmation to check it."
        )

    reasons: list[str] = []
    if college is None:
        reasons.append("other_college")

    existing = None
    if college is not None:
        existing = await session.scalar(
            select(Registration).where(
                Registration.college_id == college.id,
                func.lower(Registration.roll_no) == body.roll_no.lower(),
                Registration.status.in_(LIVE_STATUSES),
            )
        )

    reg = Registration(
        name=body.name,
        college_id=body.college_id,
        college_other=body.college_other,
        roll_no=body.roll_no,
        course=body.course,
        email=body.email.lower(),
        college_email=email_matches_college(body.email, college),
        phone=body.phone,
        id_image_key=body.id_image_key,
        status=RegStatus.pending,
        reasons=reasons,
        consent_entry=True,
        consent_dataset=body.consent_dataset,
        consent_version=body.consent_version,
        status_token=secrets.token_urlsafe(24),
        client_ip=ip,
    )
    if existing is not None:
        mark_duplicate(reg, existing)

    session.add(reg)
    try:
        await session.flush()
    except IntegrityError as e:
        # Lost a race with a concurrent registration.
        await session.rollback()
        if "registrations_email_key" in str(e.orig):
            raise HTTPException(409, "This email is already registered.")
        if "one_active_roll" not in str(e.orig):
            raise
        existing = await session.scalar(
            select(Registration).where(
                Registration.college_id == body.college_id,
                func.lower(Registration.roll_no) == body.roll_no.lower(),
                Registration.status.in_(LIVE_STATUSES),
            )
        )
        reg = Registration(**{c: getattr(reg, c) for c in REG_COPY_FIELDS})
        mark_duplicate(reg, existing)
        session.add(reg)
        await session.flush()

    session.add(AuditLog(actor="student", action="registration.created", target=reg.id, detail={"ip": ip}))
    await session.commit()

    try:
        await queue.enqueue_ocr(str(reg.id))
    except Exception:
        # Registration is saved; scripts/enqueue_pending.py picks up anything missed.
        log.exception("enqueue failed for %s", reg.id)

    return RegistrationOut(
        id=str(reg.id),
        status=reg.status.value,
        status_token=reg.status_token,
        status_url=settings.status_url_template.format(token=reg.status_token),
    )


REG_COPY_FIELDS = [
    "name", "college_id", "college_other", "roll_no", "course", "email", "college_email", "phone",
    "id_image_key", "status", "reasons", "consent_entry", "consent_dataset", "consent_version",
    "status_token", "client_ip",
]


def mark_duplicate(reg: Registration, existing: Registration | None) -> None:
    """New registration goes to review; the existing one is flagged so reviewers see both."""
    reg.status = RegStatus.review
    reg.reasons = sorted(set(reg.reasons) | {"duplicate_roll"})
    if existing is not None and "duplicate_roll" not in existing.reasons:
        existing.reasons = sorted(set(existing.reasons) | {"duplicate_roll"})


@router.get("/status/{token}", response_model=StatusOut)
async def get_status(token: str, session: AsyncSession = Depends(get_session)):
    reg = await session.scalar(select(Registration).where(Registration.status_token == token))
    if reg is None:
        raise HTTPException(404, "We couldn't find that registration.")
    college = await session.get(College, reg.college_id) if reg.college_id else None
    return StatusOut(
        name=reg.name,
        college=college.name if college else (reg.college_other or ""),
        status=reg.status.value,
        message=STATUS_TEXT[reg.status.value],
        reasons=[REASON_TEXT.get(r, r) for r in reg.reasons],
        can_reupload=can_reupload(reg),
        qr_token=None,  # filled in once passes ship (day 3)
    )


def can_reupload(reg: Registration) -> bool:
    return (
        reg.status in (RegStatus.review, RegStatus.rejected)
        and bool(REUPLOAD_REASONS & set(reg.reasons))
        and "duplicate_roll" not in reg.reasons
    )


@router.post("/status/{token}/reupload/presign", response_model=PresignOut)
async def presign_reupload(
    token: str,
    body: PresignIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    reg = await session.scalar(select(Registration).where(Registration.status_token == token))
    if reg is None or not can_reupload(reg):
        raise HTTPException(409, "A new photo isn't needed for this registration.")
    return await presign_upload(body, request, settings, storage, limiter)


@router.post("/status/{token}/reupload", response_model=StatusOut)
async def reupload(
    token: str,
    body: ReuploadIn,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    queue: JobQueue = Depends(get_queue),
):
    reg = await session.scalar(select(Registration).where(Registration.status_token == token).with_for_update())
    if reg is None or not can_reupload(reg):
        raise HTTPException(409, "A new photo isn't needed for this registration.")
    key = body.id_image_key
    await require_uploaded(storage, key, settings)

    old_key = reg.id_image_key
    reg.id_image_key = key
    reg.reasons = [r for r in reg.reasons if r not in REUPLOAD_REASONS]
    reg.status = RegStatus.pending
    reg.ocr = None
    reg.photo_crop_key = None
    reg.image_phash = None
    session.add(AuditLog(actor="student", action="registration.reupload", target=reg.id, detail={"old_key": old_key}))
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, "This roll number is already registered. A volunteer will check it.")
    try:
        await queue.enqueue_ocr(str(reg.id))
    except Exception:
        log.exception("enqueue failed for %s", reg.id)
    return await get_status(token, session)
