"""The worker job end to end: Postgres (real) + S3 (moto) + real OCR on synthetic cards.

Needs TEST_DATABASE_URL (a database it may wipe), like the API tests.
"""

import json
import os
import secrets
import uuid

import asyncpg
import boto3
import pytest
from moto import mock_aws

TEST_DB = os.environ.get("TEST_DATABASE_URL")
if not TEST_DB:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)
DSN = TEST_DB.replace("postgresql+asyncpg://", "postgresql://")
MIGRATIONS = os.path.join(os.path.dirname(__file__), "..", "..", "api", "migrations")

import worker  # noqa: E402
from tests.cards import card, jpeg, photographed  # noqa: E402


@pytest.fixture(scope="module")
async def ctx():
    conn = await asyncpg.connect(DSN)
    await conn.execute("drop schema public cascade; create schema public;")
    for f in sorted(os.listdir(MIGRATIONS)):
        await conn.execute(open(os.path.join(MIGRATIONS, f)).read())
    await conn.execute(
        """insert into colleges (id, slug, name, aliases, email_domains, roll_regex) values
           (1, 'nsut', 'Netaji Subhas University of Technology', '{NSUT}', '{nsut.ac.in}', '^20\\d{2}U[A-Z]{2}\\d{4}$'),
           (2, 'dtu', 'Delhi Technological University', '{DTU}', '{dtu.ac.in}', null)""")
    await conn.close()
    worker._colleges = (0.0, [])
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        pool = await asyncpg.create_pool(DSN, min_size=1, max_size=3)
        yield {"db": pool, "s3": s3, "bucket": "test-bucket", "job_try": 1}
        await pool.close()


async def register(ctx, image: bytes, name="Aarav Sharma", roll="2022UIC3501", college_id=1, reasons=(), status="pending"):
    key = f"id-cards/{uuid.uuid4()}.jpg"
    ctx["s3"].put_object(Bucket=ctx["bucket"], Key=key, Body=image)
    return str(await ctx["db"].fetchval(
        """insert into registrations (name, college_id, roll_no, email, college_email, id_image_key, status, reasons,
               consent_entry, consent_version, status_token)
           values ($1, $2, $3, $4, true, $5, $6, $7, true, 'v1', $8) returning id""",
        name, college_id, roll, f"{uuid.uuid4().hex[:10]}@nsut.ac.in", key, status, list(reasons),
        secrets.token_urlsafe(12)))


async def row(ctx, rid):
    return await ctx["db"].fetchrow("select * from registrations where id = $1", rid)


async def test_clean_card_is_approved_and_face_saved(ctx):
    rid = await register(ctx, jpeg(photographed(card())))
    assert await worker.process_registration(ctx, rid) == "approved"
    r = await row(ctx, rid)
    assert r["status"] == "approved" and r["reasons"] == []
    assert r["photo_crop_key"] == f"faces/{rid}.jpg" and r["image_phash"] is not None
    face = ctx["s3"].get_object(Bucket=ctx["bucket"], Key=r["photo_crop_key"])
    assert face["ContentType"] == "image/jpeg"
    ocr = json.loads(r["ocr"])
    assert ocr["roll"]["match"] == "exact" and ocr["name"]["score"] >= 85
    audit = await ctx["db"].fetchval("select count(*) from audit_log where target = $1", uuid.UUID(rid))
    assert audit == 1


async def test_same_card_reused_flags_both(ctx):
    img = jpeg(photographed(card(name="ROHAN VERMA", roll="2023UCS1234", person=1)))
    first = await register(ctx, img, name="Rohan Verma", roll="2023UCS1234")
    await worker.process_registration(ctx, first)
    # Someone else submits the same card photo under a different roll number.
    second = await register(ctx, jpeg(card(name="ROHAN VERMA", roll="2023UCS1234", person=1)), name="Rohan Verma", roll="2023UCS1235")
    assert await worker.process_registration(ctx, second) == "review"
    r2 = await row(ctx, second)
    assert "duplicate_card" in r2["reasons"]
    assert json.loads(r2["ocr"])["duplicate_of"] is not None
    assert "duplicate_card" in (await row(ctx, first))["reasons"]


async def test_registration_time_reasons_are_kept(ctx):
    rid = await register(ctx, jpeg(card(name="NEHA GUPTA", roll="2021UEE0042", person=2)), name="Neha Gupta",
                         roll="2021UEE0042", reasons=["duplicate_roll"], status="review")
    assert await worker.process_registration(ctx, rid) == "review"
    r = await row(ctx, rid)
    assert r["reasons"] == ["duplicate_roll"] and r["ocr"] is not None


async def test_already_decided_is_skipped(ctx):
    rid = await register(ctx, jpeg(card(name="KABIR SINGH", roll="2022UME0101", person=3)), name="Kabir Singh", roll="2022UME0101")
    await ctx["db"].execute("update registrations set status = 'approved' where id = $1", rid)
    assert await worker.process_registration(ctx, rid) == "skipped"


async def test_unreadable_upload_retries_then_goes_to_review(ctx):
    rid = await register(ctx, b"not an image", name="Ira Das", roll="2022UBT0007")
    with pytest.raises(Exception):
        await worker.process_registration(ctx, rid)
    assert (await row(ctx, rid))["status"] == "processing"  # Arq will retry
    assert await worker.process_registration({**ctx, "job_try": worker.MAX_TRIES}, rid) == "review"
    r = await row(ctx, rid)
    assert r["status"] == "review" and r["reasons"] == ["processing_error"]
