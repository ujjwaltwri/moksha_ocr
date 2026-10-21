"""Admin and help desk: stats, search, resend, manual approve, revoke, staff and gate-phone tokens."""

import base64
import io
import json
import logging
from typing import Literal

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Staff, admin, new_token
from ..config import Settings, get_settings
from ..db import get_session
from ..schemas import REASON_TEXT
from ..services import JobQueue, Storage, get_queue, get_storage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def qr_png(data: str) -> str:
    img = qrcode.make(data, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def audit(session: AsyncSession, who: Staff, action: str, target=None, detail=None):
    await session.execute(text(
        "insert into audit_log (actor, action, target, detail) values (:a, :act, :t, cast(:d as jsonb))"),
        {"a": who.name, "act": action, "t": target, "d": json.dumps(detail) if detail else None})


# ---------- Stats ----------

@router.get("/stats")
async def stats(_: Staff = Depends(admin), session: AsyncSession = Depends(get_session)):
    by_status = dict((await session.execute(text(
        "select status::text, count(*) from registrations group by 1"))).all())
    passes = (await session.execute(text("""
        select count(*) filter (where token is not null) as issued,
               count(*) filter (where revoked) as revoked,
               count(*) filter (where email_sent_at is not null) as emailed,
               count(*) filter (where email_sent_at is null and email_error is not null) as email_failed
        from passes"""))).mappings().one()
    approved_without_pass = await session.scalar(text("""
        select count(*) from registrations r where status = 'approved'
          and not exists (select 1 from passes p where p.registration_id = r.id and p.token is not null)"""))
    gate = [dict(r) for r in (await session.execute(text("""
        select day, result, count(*) as n, count(*) filter (where conflict) as conflicts
        from checkins group by 1, 2 order by 1, 2"""))).mappings().all()]
    devices = (await session.execute(text("""
        select count(*) filter (where not revoked) as active,
               count(*) filter (where not revoked and last_seen_at > now() - interval '2 minutes') as online
        from devices"""))).mappings().one()
    return {
        "registrations": {s: by_status.get(s, 0) for s in ("pending", "processing", "review", "approved", "rejected")},
        "passes": dict(passes),
        "approved_without_pass": approved_without_pass,
        "gate": gate,
        "devices": dict(devices),
    }


# ---------- Help desk ----------

@router.get("/search")
async def search(q: str, _: Staff = Depends(admin), session: AsyncSession = Depends(get_session),
                 storage: Storage = Depends(get_storage), settings: Settings = Depends(get_settings)):
    q = q.strip()
    if len(q) < 2:
        return {"results": []}
    rows = (await session.execute(text("""
        select r.id, r.name, r.roll_no, r.email, r.phone, r.status::text, r.reasons, r.status_token,
               r.id_image_key, r.photo_crop_key, coalesce(c.name, r.college_other) as college,
               p.id as pass_id, p.revoked, p.email_sent_at, p.email_error,
               (select json_agg(json_build_object('day', k.day, 'result', k.result, 'gate', k.gate,
                                                  'at', k.scanned_at, 'conflict', k.conflict) order by k.seq)
                  from checkins k where k.pass_id = p.id::text) as checkins
        from registrations r
        left join colleges c on c.id = r.college_id
        left join passes p on p.registration_id = r.id
        where r.email ilike :like or r.roll_no ilike :roll or r.name ilike :like or r.phone = :q
           or p.id::text = :q or r.id::text = :q
        order by r.created_at desc limit 20"""),
        {"like": f"%{q}%", "roll": f"%{q.replace(' ', '').replace('-', '')}%", "q": q})).mappings().all()
    return {"results": [{
        "id": str(r["id"]), "name": r["name"], "college": r["college"], "roll_no": r["roll_no"],
        "email": r["email"], "phone": r["phone"], "status": r["status"],
        "reasons": [REASON_TEXT.get(x, x) for x in r["reasons"]],
        "status_url": settings.status_url_template.format(token=r["status_token"]),
        "card_url": storage.view_url(r["id_image_key"]),
        "face_url": storage.view_url(r["photo_crop_key"]) if r["photo_crop_key"] else None,
        "pass": None if r["pass_id"] is None else {
            "id": str(r["pass_id"]), "revoked": r["revoked"],
            "email_sent_at": r["email_sent_at"].isoformat() if r["email_sent_at"] else None,
            "email_error": r["email_error"],
        },
        "checkins": r["checkins"] or [],
    } for r in rows]}


@router.post("/registrations/{rid}/resend")
async def resend(rid: str, who: Staff = Depends(admin), session: AsyncSession = Depends(get_session),
                 queue: JobQueue = Depends(get_queue)):
    status = await session.scalar(text("select status::text from registrations where id = :id"), {"id": rid})
    if status != "approved":
        raise HTTPException(409, f"Only approved registrations have a pass (this one is {status}).")
    has_pass = await session.scalar(text(
        "select 1 from passes where registration_id = :id and token is not null"), {"id": rid})
    await audit(session, who, "pass.resend", rid)
    await session.commit()
    await (queue.enqueue_email(rid) if has_pass else queue.enqueue_pass(rid))
    return {"queued": "email" if has_pass else "pass"}


@router.post("/registrations/{rid}/approve")
async def approve(rid: str, who: Staff = Depends(admin), session: AsyncSession = Depends(get_session),
                  queue: JobQueue = Depends(get_queue)):
    """Help desk: approve after checking the student and their card in person."""
    try:
        res = await session.execute(text("""
            update registrations set status = 'approved', reasons = '{}', claimed_by = null, claimed_at = null,
                   updated_at = now()
            where id = :id and status in ('pending', 'processing', 'review', 'rejected') returning id"""), {"id": rid})
        if res.first() is None:
            raise HTTPException(409, "Already approved, or not found")
        await session.execute(text("""
            insert into review_actions (registration_id, reviewer, decision, reason)
            values (:id, :who, 'approved', 'help_desk')"""), {"id": rid, "who": who.name})
        await audit(session, who, "registration.approve", rid)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Another live registration already has this roll number.")
    await queue.enqueue_pass(rid)
    return {"id": rid, "status": "approved"}


@router.post("/passes/{pid}/revoke")
async def revoke(pid: str, who: Staff = Depends(admin), session: AsyncSession = Depends(get_session)):
    res = await session.execute(text("update passes set revoked = true where id = :id returning id"), {"id": pid})
    if res.first() is None:
        raise HTTPException(404, "No such pass")
    await audit(session, who, "pass.revoke", pid)
    await session.commit()
    return {"id": pid, "revoked": True, "note": "Gate phones pick this up within a minute."}


@router.post("/passes/{pid}/unrevoke")
async def unrevoke(pid: str, who: Staff = Depends(admin), session: AsyncSession = Depends(get_session)):
    res = await session.execute(text("update passes set revoked = false where id = :id returning id"), {"id": pid})
    if res.first() is None:
        raise HTTPException(404, "No such pass")
    await audit(session, who, "pass.unrevoke", pid)
    await session.commit()
    return {"id": pid, "revoked": False}


@router.post("/passes/issue-missing")
async def issue_missing(who: Staff = Depends(admin), session: AsyncSession = Depends(get_session),
                        queue: JobQueue = Depends(get_queue)):
    """Queue passes for approved registrations that don't have one (e.g. the worker was down)."""
    ids = list(await session.scalars(text("""
        select r.id::text from registrations r where status = 'approved'
          and not exists (select 1 from passes p where p.registration_id = r.id and p.token is not null)""")))
    for rid in ids:
        await queue.enqueue_pass(rid)
    return {"queued": len(ids)}


# ---------- Staff tokens ----------

class StaffIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    role: Literal["reviewer", "admin"] = "reviewer"


@router.get("/staff")
async def list_staff(_: Staff = Depends(admin), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(text("""
        select s.id, s.name, s.role, s.revoked, s.created_at,
               (select count(*) from review_actions a where a.reviewer = s.name || ' (#' || s.id || ')') as decisions
        from staff s order by s.id"""))).mappings().all()
    return {"staff": [dict(r, created_at=r["created_at"].isoformat()) for r in rows]}


@router.post("/staff")
async def create_staff(body: StaffIn, who: Staff = Depends(admin), session: AsyncSession = Depends(get_session),
                       settings: Settings = Depends(get_settings)):
    token, h = new_token("rev" if body.role == "reviewer" else "adm")
    sid = await session.scalar(text(
        "insert into staff (name, role, token_hash) values (:n, :r, :h) returning id"),
        {"n": body.name.strip(), "r": body.role, "h": h})
    await audit(session, who, "staff.create", detail={"id": sid, "name": body.name, "role": body.role})
    await session.commit()
    page = "review" if body.role == "reviewer" else "admin"
    return {"id": sid, "token": token,
            "login_url": f"{settings.api_public_url}/{page}#token={token}",
            "note": "Shown once. Send it to them privately."}


@router.delete("/staff/{sid}")
async def revoke_staff(sid: int, who: Staff = Depends(admin), session: AsyncSession = Depends(get_session)):
    await session.execute(text("update staff set revoked = true where id = :id"), {"id": sid})
    await session.execute(text("update registrations set claimed_by = null, claimed_at = null where claimed_by = :id"),
                          {"id": sid})
    await audit(session, who, "staff.revoke", detail={"id": sid})
    await session.commit()
    return {"id": sid, "revoked": True}


# ---------- Gate phones ----------

class DeviceIn(BaseModel):
    gate: str = Field(min_length=1, max_length=40)
    day: int = Field(1, ge=1, le=31)


@router.get("/devices")
async def list_devices(_: Staff = Depends(admin), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(text("""
        select d.id, d.gate, d.revoked, d.created_at, d.last_seen_at,
               (select count(*) from checkins k where k.device = d.id) as checkins
        from devices d order by d.id"""))).mappings().all()
    return {"devices": [dict(r, created_at=r["created_at"].isoformat(),
                             last_seen_at=r["last_seen_at"].isoformat() if r["last_seen_at"] else None) for r in rows]}


@router.post("/devices")
async def create_device(body: DeviceIn, who: Staff = Depends(admin), session: AsyncSession = Depends(get_session),
                        settings: Settings = Depends(get_settings)):
    """A token for one gate phone, as the setup QR the app scans."""
    token, h = new_token("gate")
    did = await session.scalar(text("insert into devices (gate, token_hash) values (:g, :h) returning id"),
                               {"g": body.gate.strip(), "h": h})
    await audit(session, who, "device.create", detail={"id": did, "gate": body.gate})
    await session.commit()
    setup = {"t": "moksha-gate-setup", "url": settings.api_public_url, "token": token,
             "gate": body.gate.strip(), "day": body.day}
    if settings.pass_public_key:
        setup["key"] = settings.pass_public_key  # used by debug builds; release builds have it compiled in
    return {"id": did, "setup": setup, "setup_qr": qr_png(json.dumps(setup, separators=(",", ":"))),
            "note": "Scan this from the app's setup screen. Make one per phone, so a lost phone can be revoked on its own."}


@router.delete("/devices/{did}")
async def revoke_device(did: int, who: Staff = Depends(admin), session: AsyncSession = Depends(get_session)):
    await session.execute(text("update devices set revoked = true where id = :id"), {"id": did})
    await audit(session, who, "device.revoke", detail={"id": did})
    await session.commit()
    return {"id": did, "revoked": True}
