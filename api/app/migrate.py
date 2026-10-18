"""Applies api/migrations/*.sql in order, once each. Run: python -m app.migrate"""

import asyncio
from pathlib import Path

import asyncpg

from .config import get_settings

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def plain_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def migrate(database_url: str | None = None) -> list[str]:
    conn = await asyncpg.connect(plain_dsn(database_url or get_settings().database_url))
    applied: list[str] = []
    try:
        await conn.execute("create table if not exists schema_migrations (name text primary key, at timestamptz default now())")
        done = {r["name"] for r in await conn.fetch("select name from schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            async with conn.transaction():
                await conn.execute(f.read_text())
                await conn.execute("insert into schema_migrations (name) values ($1)", f.name)
            applied.append(f.name)
    finally:
        await conn.close()
    return applied


if __name__ == "__main__":
    names = asyncio.run(migrate())
    print("applied:", ", ".join(names) if names else "nothing new")
