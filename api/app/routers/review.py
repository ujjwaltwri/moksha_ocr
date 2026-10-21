"""Human review of registrations the worker couldn't approve on its own."""

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Staff, reviewer
from ..config import Settings, get_settings
from ..db import get_session
from ..schemas import REASON_TEXT, normalize_roll
from ..services import JobQueue, Storage, get_queue, get_storage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/review", tags=["review"])

REJECT_REASONS = {
    "not_student": "This doesn't look like a valid student ID card.",
    "card_invalid": "Your ID card has expired or isn't valid for this year.",
    "details_mismatch": "The details on your card don't match what you entered.",
    "duplicate": "Another registration already uses this ID card.",
    "college_not_allowed": "Your college isn't part of this year's Moksha.",
}

# A case is ready once OCR has run (or failed for good).
READY = "status = 'review' and (ocr is not null or 'processing_error' = any(reasons))"


def need_person(staff: Staff) -> int:
    if staff.id is None:
        raise HTTPException(403, "Create a reviewer or admin token for yourself on the admin page, and review with that.")
    return staff.id


class ClaimIn(BaseModel):
    reason: str | None = None  # only cases with this reason code


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "reupload"]
    reason: str | None = None              # required for reject: one of REJECT_REASONS
    name: str | None = Field(default=None, max_length=120)      # correction
    roll_no: str | None = Field(default=None, max_length=40)    # correction


@router.get("/summary")
async def summary(staff: Staff = Depends(reviewer), session: AsyncSession = Depends(get_session)):
    """Queue size, and how many cases have each reason."""
    total = await session.scalar(text(f"select count(*) from registrations where {READY}"))
    waiting_ocr = await session.scalar(text("select count(*) from registrations where status in ('pending', 'processing')"))
    rows = (await session.execute(text(
        f"select unnest(reasons) as r, count(*) as n from registrations where {READY} group by 1 order by 2 desc"))).all()
    return {
        "in_queue": total,
        "waiting_for_ocr": waiting_ocr,
        "by_reason": [{"reason": r.r, "label": REASON_TEXT.get(r.r, r.r), "count": r.n} for r in rows],
        "reject_reasons": [{"code": k, "label": v} for k, v in REJECT_REASONS.items()],
        "you": {"name": staff.name, "role": staff.role},
    }


@router.post("/claim")
async def claim(
    body: ClaimIn,
    staff: Staff = Depends(reviewer),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
):
    """Take the oldest unclaimed case. Two reviewers never get the same one."""
    sid = need_person(staff)
    reason_filter = "and :reason = any(reasons)" if body.reason else ""
    row = (await session.execute(text(f"""
        with next as (
          select id from registrations
          where {READY} {reason_filter}
            and (claimed_by is null or claimed_by = :sid
                 or claimed_at < now() - make_interval(mins => :mins))
          order by (claimed_by = :sid) desc nulls last, created_at
          for update skip locked
          limit 1)
        update registrations r set claimed_by = :sid, claimed_at = now()
        from next where r.id = next.id
        returning r.id"""), {"sid": sid, "mins": settings.review_claim_minutes, "reason": body.reason})).first()
    await session.commit()
    if row is None:
        return {"case": None}
    return {"case": await load_case(session, storage, str(row.id))}


async def load_case(session: AsyncSession, storage: Storage, rid: str) -> dict:
    r = (await session.execute(text("""
        select r.*, c.name as college_name from registrations r left join colleges c on c.id = r.college_id
        where r.id = :id"""), {"id": rid})).mappings().one()
    ocr = r["ocr"] if isinstance(r["ocr"], dict) else (json.loads(r["ocr"]) if r["ocr"] else None)

    # Other registrations involved in a duplicate, so the reviewer can compare.
    related = []
    dup_of = (ocr or {}).get("duplicate_of")
    rows = (await session.execute(text("""
        select id, name, roll_no, email, status, id_image_key, photo_crop_key from registrations
        where id <> :id and (
              (college_id is not distinct from :cid and lower(roll_no) = lower(:roll))
           or id::text = :dup)
        order by created_at limit 5"""), {"id": rid, "cid": r["college_id"], "roll": r["roll_no"], "dup": dup_of or ""})).mappings().all()
    for o in rows:
        related.append({
            "id": str(o["id"]), "name": o["name"], "roll_no": o["roll_no"], "email": o["email"], "status": o["status"],
            "card_url": storage.view_url(o["id_image_key"]),
            "face_url": storage.view_url(o["photo_crop_key"]) if o["photo_crop_key"] else None,
        })

    return {
        "id": str(r["id"]),
        "name": r["name"],
        "college": r["college_name"] or f"Other: {r['college_other']}",
        "college_email": r["college_email"],
        "roll_no": r["roll_no"],
        "course": r["course"],
        "email": r["email"],
        "created_at": r["created_at"].isoformat(),
        "reasons": [{"code": c, "label": REASON_TEXT.get(c, c)} for c in r["reasons"]],
        "card_url": storage.view_url(r["id_image_key"]),
        "face_url": storage.view_url(r["photo_crop_key"]) if r["photo_crop_key"] else None,
        "ocr": ocr,
        "related": related,
    }


@router.post("/{rid}/release")
async def release(rid: str, staff: Staff = Depends(reviewer), session: AsyncSession = Depends(get_session)):
    """Put a claimed case back in the queue (the "skip" key)."""
    sid = need_person(staff)
    await session.execute(text(
        "update registrations set claimed_by = null, claimed_at = null where id = :id and claimed_by = :sid"),
        {"id": rid, "sid": sid})
    await session.commit()
    return {"ok": True}


@router.post("/{rid}/decision")
async def decide(
    rid: str,
    body: DecisionIn,
    staff: Staff = Depends(reviewer),
    session: AsyncSession = Depends(get_session),
    queue: JobQueue = Depends(get_queue),
):
    sid = need_person(staff)
    r = (await session.execute(text(
        "select id, status, claimed_by, name, roll_no from registrations where id = :id for update"), {"id": rid})).first()
    if r is None:
        raise HTTPException(404, "No such registration")
    if r.status != "review":
        raise HTTPException(409, f"Already decided ({r.status})")
    if r.claimed_by != sid:
        raise HTTPException(409, "This case isn't claimed by you (it may have timed out). Claim the next case.")

    corrections = {}
    if body.name and body.name.strip() != r.name:
        corrections["name"] = " ".join(body.name.split())
    if body.roll_no and normalize_roll(body.roll_no) != r.roll_no:
        corrections["roll_no"] = normalize_roll(body.roll_no)

    if body.decision == "approve":
        status, reasons = "approved", []
    elif body.decision == "reject":
        if body.reason not in REJECT_REASONS:
            raise HTTPException(422, f"Pick a reject reason: {', '.join(REJECT_REASONS)}")
        status, reasons = "rejected", [body.reason]
    else:  # reupload
        status, reasons = "review", ["reupload_requested"]

    try:
        await session.execute(text("""
            update registrations set status = :status, reasons = :reasons,
                   name = coalesce(:name, name), roll_no = coalesce(:roll, roll_no),
                   claimed_by = null, claimed_at = null, updated_at = now()
            where id = :id"""), {"status": status, "reasons": reasons, "name": corrections.get("name"),
                                 "roll": corrections.get("roll_no"), "id": rid})
        await session.execute(text("""
            insert into review_actions (registration_id, reviewer, decision, reason, corrections)
            values (:id, :who, :decision, :reason, cast(:corr as jsonb))"""),
            {"id": rid, "who": f"{staff.name} (#{sid})", "decision": status, "reason": body.reason,
             "corr": json.dumps(corrections) if corrections else None})
        await session.execute(text("""
            insert into audit_log (actor, action, target, detail) values (:who, 'review.decision', :id, cast(:d as jsonb))"""),
            {"who": staff.name, "id": rid, "d": json.dumps({"decision": body.decision, "reason": body.reason})})
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Another live registration already has this roll number. Reject one of them first.")

    if status == "approved":
        try:
            await queue.enqueue_pass(rid)
        except Exception:
            log.exception("could not queue pass for %s", rid)  # scripts/issue_missing_passes.py catches up
    return {"id": rid, "status": status, "reasons": reasons, "corrections": corrections}
