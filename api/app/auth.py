"""Bearer-token auth for staff (reviewers, admins) and gate devices.

Tokens are random strings shown once when created; the database keeps only their SHA-256.
The first admin uses ADMIN_TOKEN from .env to create everyone else.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session


def new_token(prefix: str) -> tuple[str, str]:
    """(token to hand out, hash to store)."""
    token = f"{prefix}_{secrets.token_urlsafe(24)}"
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing token")
    return authorization[7:].strip()


@dataclass
class Staff:
    id: int | None  # None = the bootstrap admin from ADMIN_TOKEN
    name: str
    role: str


async def current_staff(
    authorization: str | None = Header(default=None), session: AsyncSession = Depends(get_session)
) -> Staff:
    token = _bearer(authorization)
    admin = get_settings().admin_token
    if admin and hmac.compare_digest(token, admin):
        return Staff(id=None, name="admin", role="admin")
    row = (await session.execute(
        text("select id, name, role from staff where token_hash = :h and not revoked"), {"h": hash_token(token)}
    )).first()
    if row is None:
        raise HTTPException(401, "Invalid or revoked token")
    return Staff(id=row.id, name=row.name, role=row.role)


async def reviewer(staff: Staff = Depends(current_staff)) -> Staff:
    return staff  # admins can review too


async def admin(staff: Staff = Depends(current_staff)) -> Staff:
    if staff.role != "admin":
        raise HTTPException(403, "Admins only")
    return staff


@dataclass
class Device:
    id: int
    gate: str


async def current_device(
    authorization: str | None = Header(default=None), session: AsyncSession = Depends(get_session)
) -> Device:
    token = _bearer(authorization)
    row = (await session.execute(
        text("""update devices set last_seen_at = now() where token_hash = :h and not revoked
                returning id, gate"""), {"h": hash_token(token)}
    )).first()
    if row is None:
        raise HTTPException(401, "This phone's token is invalid or was revoked. Ask an admin for a new setup code.")
    await session.commit()
    return Device(id=row.id, gate=row.gate)
