"""Load college templates from worker/templates/*.yaml into the colleges table.

    DATABASE_URL=... python scripts/seed_colleges.py

Upserts by slug (the file name), so re-run it whenever a template changes.
Files starting with "_" are examples and are skipped.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg
import yaml

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "worker" / "templates"


async def main() -> None:
    url = os.environ.get("DATABASE_URL", "postgresql://moksha:moksha@localhost:5432/moksha")
    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    count = 0
    for f in sorted(TEMPLATES.glob("*.yaml")):
        if f.name.startswith("_"):
            continue
        t = yaml.safe_load(f.read_text())
        if not t.get("name"):
            sys.exit(f"{f.name}: missing name")
        await conn.execute(
            """insert into colleges (slug, name, aliases, email_domains, roll_regex, template, allowed)
               values ($1, $2, $3, $4, $5, $6::jsonb, $7)
               on conflict (slug) do update set
                 name = excluded.name, aliases = excluded.aliases, email_domains = excluded.email_domains,
                 roll_regex = excluded.roll_regex, template = excluded.template, allowed = excluded.allowed""",
            f.stem,
            t["name"],
            t.get("aliases", []),
            [d.lower() for d in t.get("email_domains", [])],
            t.get("roll_regex"),
            json.dumps({k: t[k] for k in ("labels", "require_validity_date") if k in t}),
            t.get("allowed", True),
        )
        count += 1
    await conn.close()
    print(f"seeded {count} colleges")


if __name__ == "__main__":
    asyncio.run(main())
