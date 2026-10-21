"""Gate phone sync. Contract: app/lib/services/api.dart and app/tools/mock_server.py.

GET  /gate/manifest?since=<cursor>&limit=<n>
  -> {"passes":[{"id","name","college","roll_no","thumb_b64","revoked","updated_at"}],
      "next_cursor","has_more","total"}
POST /gate/checkins
  <- {"device_id","gate","since","checkins":[{"id","pass_id","scanned_at","result","reason","day"}]}
  -> {"accepted":[ids],"conflicts":[ids],"remote":[...],"next_since"}
"""

import base64
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Device, current_device
from ..db import get_session

router = APIRouter(prefix="/gate", tags=["gate"])

REMOTE_PAGE = 5000


def _cursor(v: str | None) -> int:
    try:
        return max(0, int(v or 0))
    except ValueError:
        return 0


@router.get("/manifest")
async def manifest(
    since: str | None = None,
    limit: int = Query(1000, ge=1, le=2000),
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
):
    after = _cursor(since)
    rows = (await session.execute(text("""
        select p.id, p.seq, p.revoked or r.status <> 'approved' as revoked, p.thumb, p.updated_at,
               r.name, r.roll_no, coalesce(c.name, r.college_other, '') as college
        from passes p
        join registrations r on r.id = p.registration_id
        left join colleges c on c.id = r.college_id
        where p.token is not null and p.seq > :after
        order by p.seq
        limit :lim"""), {"after": after, "lim": limit + 1})).all()
    page, has_more = rows[:limit], len(rows) > limit
    total = None
    if since is None:
        total = await session.scalar(text("select count(*) from passes where token is not null"))
    return {
        "passes": [{
            "id": str(r.id),
            "name": r.name,
            "college": r.college,
            "roll_no": r.roll_no,
            "thumb_b64": base64.b64encode(r.thumb).decode() if r.thumb else None,
            "revoked": bool(r.revoked),
            "updated_at": r.updated_at.isoformat(),
        } for r in page],
        "next_cursor": str(page[-1].seq if page else after),
        "has_more": has_more,
        "total": total,
    }


class CheckinIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    pass_id: str = Field(min_length=1, max_length=64)
    scanned_at: datetime
    result: Literal["admitted", "denied", "duplicate"]
    reason: str | None = Field(default=None, max_length=64)
    day: int = Field(ge=0, le=31)


class CheckinsIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    gate: str | None = Field(default=None, max_length=64)
    since: str | None = None
    checkins: list[CheckinIn] = Field(default_factory=list, max_length=2000)


@router.post("/checkins")
async def checkins(body: CheckinsIn, device: Device = Depends(current_device),
                   session: AsyncSession = Depends(get_session)):
    gate = body.gate or device.gate
    accepted, conflicts = [], []
    if body.checkins:
        # Serialise writers so seq values commit in order and no other gate's cursor skips a row.
        await session.execute(text("select pg_advisory_xact_lock(4242)"))
        for c in body.checkins:
            new = (await session.execute(text("""
                insert into checkins (id, pass_id, device_id, device, gate, day, result, reason, scanned_at)
                values (:id, :pass_id, :device_id, :device, :gate, :day, :result, :reason, :scanned_at)
                on conflict (id) do nothing
                returning seq"""), {**c.model_dump(), "device_id": body.device_id, "device": device.id,
                                    "gate": gate})).first()
            if new is not None and c.result == "admitted":
                # Another phone admitted this pass for the same day first: a likely shared pass.
                earlier = await session.scalar(text("""
                    select 1 from checkins where pass_id = :p and day = :d and result = 'admitted'
                      and device_id <> :dev and seq < :seq limit 1"""),
                    {"p": c.pass_id, "d": c.day, "dev": body.device_id, "seq": new.seq})
                if earlier:
                    await session.execute(text("update checkins set conflict = true where seq = :s"), {"s": new.seq})
            accepted.append(c.id)
        conflicts = list(await session.scalars(text(
            "select id from checkins where conflict and id = any(:ids)"), {"ids": accepted}))
        await session.commit()

    after = _cursor(body.since)
    rows = (await session.execute(text("""
        select seq, id, pass_id, device_id, gate, scanned_at, result, reason, day from checkins
        where seq > :after order by seq limit :lim"""), {"after": after, "lim": REMOTE_PAGE})).all()
    return {
        "accepted": accepted,
        "conflicts": conflicts,
        "remote": [{
            "id": r.id, "pass_id": r.pass_id, "device_id": r.device_id, "gate": r.gate or "?",
            "scanned_at": r.scanned_at.isoformat(), "result": r.result, "reason": r.reason, "day": r.day,
        } for r in rows if r.device_id != body.device_id],
        "next_since": str(rows[-1].seq if rows else after),
    }
