"""Tests run against a real Postgres (citext, enums, partial unique index).

Set TEST_DATABASE_URL, e.g. postgresql+asyncpg://postgres@localhost:5432/moksha_test.
The database's public schema is wiped at the start of the run.
"""

import os
import uuid

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

TEST_DB = os.environ.get("TEST_DATABASE_URL")
if not TEST_DB:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)
os.environ["DATABASE_URL"] = TEST_DB

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import migrate, plain_dsn  # noqa: E402
from app.services import get_captcha, get_queue, get_rate_limiter, get_storage  # noqa: E402

get_settings.cache_clear()


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, int] = {}

    def presign_upload(self, key, content_type, max_bytes, ttl_s):
        from app.services import PresignedUpload

        return PresignedUpload(url="https://storage.test/upload", fields={"key": key}, key=key)

    def object_size(self, key):
        return self.objects.get(key)


class FakeQueue:
    def __init__(self):
        self.jobs: list[str] = []

    async def enqueue_ocr(self, registration_id):
        self.jobs.append(registration_id)


class AllowAll:
    async def hit(self, *a, **k):
        return True

    async def verify(self, *a, **k):
        return True


@pytest.fixture(scope="session", autouse=True)
async def database():
    conn = await asyncpg.connect(plain_dsn(TEST_DB))
    await conn.execute("drop schema public cascade; create schema public;")
    await conn.close()
    await migrate(TEST_DB)
    conn = await asyncpg.connect(plain_dsn(TEST_DB))
    await conn.execute(
        """insert into colleges (slug, name, email_domains, roll_regex, allowed) values
           ('nsut', 'Netaji Subhas University of Technology', '{nsut.ac.in}', '^20\\d{2}U[A-Z]{2}\\d{4}$', true),
           ('dtu', 'Delhi Technological University', '{dtu.ac.in}', null, true),
           ('banned', 'Not Invited College', '{}', null, false)"""
    )
    await conn.close()
    yield


@pytest.fixture
def storage():
    return FakeStorage()


@pytest.fixture
def queue():
    return FakeQueue()


@pytest.fixture
async def client(storage, queue):
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_queue] = lambda: queue
    app.dependency_overrides[get_rate_limiter] = lambda: AllowAll()
    app.dependency_overrides[get_captcha] = lambda: AllowAll()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def upload(storage):
    """Puts a fake uploaded card in storage and returns its key."""

    def make(size: int = 500_000) -> str:
        key = f"id-cards/{uuid.uuid4()}.jpg"
        storage.objects[key] = size
        return key

    return make


@pytest.fixture
async def college_ids():
    conn = await asyncpg.connect(plain_dsn(TEST_DB))
    rows = await conn.fetch("select slug, id from colleges")
    await conn.close()
    return {r["slug"]: r["id"] for r in rows}
