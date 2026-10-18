"""Queue an OCR job for every registration still in `pending`.

Use it when the worker starts for the first time (day 2), or after any outage:

    DATABASE_URL=... REDIS_URL=... python scripts/enqueue_pending.py

Safe to run repeatedly: a registration already waiting in the queue isn't queued twice.
"""

import asyncio
import os

import asyncpg
from arq import create_pool
from arq.connections import RedisSettings


async def main() -> None:
    db = os.environ.get("DATABASE_URL", "postgresql://moksha:moksha@localhost:5432/moksha")
    conn = await asyncpg.connect(db.replace("postgresql+asyncpg://", "postgresql://"))
    ids = [str(r["id"]) for r in await conn.fetch("select id from registrations where status = 'pending' order by created_at")]
    await conn.close()

    redis = await create_pool(RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0")))
    queued = 0
    for rid in ids:
        if await redis.enqueue_job("process_registration", rid, _job_id=f"ocr:{rid}"):
            queued += 1
    await redis.aclose()
    print(f"{len(ids)} pending, {queued} newly queued")


if __name__ == "__main__":
    asyncio.run(main())
