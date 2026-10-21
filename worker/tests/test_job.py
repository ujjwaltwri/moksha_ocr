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
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        yield {"db": pool, "s3": s3, "bucket": "test-bucket", "job_try": 1, "signing_key": Ed25519PrivateKey.generate()}
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


# ---------- passes and email ----------

import base64  # noqa: E402
import io  # noqa: E402
import smtplib  # noqa: E402

from arq import Retry  # noqa: E402
from PIL import Image  # noqa: E402


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


async def approved(ctx, person, roll):
    rid = await register(ctx, jpeg(photographed(card(name="TARA NAIR", roll=roll, person=person))),
                         name="Tara Nair", roll=roll)
    assert await worker.process_registration(ctx, rid) == "approved"
    return rid


async def test_issue_pass_signs_token_and_makes_thumb(ctx):
    rid = await approved(ctx, 4, "2022UCS0808")
    pid = await worker.issue_pass(ctx, rid)
    p = await ctx["db"].fetchrow("select * from passes where id = $1", uuid.UUID(pid))
    body_b64, sig_b64 = p["token"].split(".")
    body = _unb64(body_b64)
    ctx["signing_key"].public_key().verify(_unb64(sig_b64), body)   # raises if forged
    payload = json.loads(body)
    assert payload["p"] == pid and payload["e"] == "moksha26" and payload["d"] == [1, 2, 3] and payload["v"] == 1
    assert "name" not in body.decode()                               # no personal data in the QR
    thumb = Image.open(io.BytesIO(p["thumb"]))
    assert thumb.format == "WEBP" and thumb.size == (160, 160) and len(p["thumb"]) < 20_000
    # running again (a retried job) keeps the same pass and token
    assert await worker.issue_pass(ctx, rid) == pid
    assert (await ctx["db"].fetchval("select token from passes where id = $1", uuid.UUID(pid))) == p["token"]


async def test_issue_pass_skips_unapproved(ctx):
    rid = await register(ctx, jpeg(card(person=5)), name="Not Approved", roll="2022UCS0999")
    assert await worker.issue_pass(ctx, rid) == "skipped"


async def test_email_sent_with_inline_qr(ctx):
    rid = await approved(ctx, 5, "2022UCS0809")
    await worker.issue_pass(ctx, rid)
    sent = []
    assert await worker.send_pass_email({**ctx, "send_mail": sent.append}, rid) == "sent"
    msg = sent[0]
    assert msg["Subject"].endswith("entry pass") and msg["To"].endswith("@nsut.ac.in")
    images = [part for part in msg.walk() if part.get_content_type() == "image/png"]
    assert len(images) == 1 and images[0].get_payload(decode=True)[:4] == b"\x89PNG"
    html_part = next(part for part in msg.walk() if part.get_content_type() == "text/html").get_content()
    cid = images[0]["Content-ID"].strip("<>")
    assert f"cid:{cid}" in html_part and "Tara Nair" in html_part
    row = await ctx["db"].fetchrow("select email_sent_at, email_attempts, email_error from passes p "
                                   "join registrations r on r.id = p.registration_id where r.id = $1", uuid.UUID(rid))
    assert row["email_sent_at"] is not None and row["email_attempts"] == 1 and row["email_error"] is None


async def test_email_failure_retries_then_gives_up(ctx):
    rid = await register(ctx, jpeg(card(face=False)), name="Om Prakash", roll="2022UEC0777", status="approved")
    await worker.issue_pass(ctx, rid)   # no face crop: pass without a thumbnail

    def down(msg):
        raise ConnectionRefusedError("smtp down")

    with pytest.raises(Retry):
        await worker.send_pass_email({**ctx, "send_mail": down, "job_try": 1}, rid)
    assert await worker.send_pass_email({**ctx, "send_mail": down, "job_try": worker.EMAIL_TRIES}, rid) == "failed"
    row = await ctx["db"].fetchrow("select email_sent_at, email_attempts, email_error from passes p "
                                   "join registrations r on r.id = p.registration_id where r.id = $1", uuid.UUID(rid))
    assert row["email_sent_at"] is None and row["email_attempts"] == 2 and "smtp down" in row["email_error"]

    def refused(msg):
        raise smtplib.SMTPRecipientsRefused({"x@y": (550, b"no such user")})

    assert await worker.send_pass_email({**ctx, "send_mail": refused}, rid) == "refused"


async def test_no_email_for_revoked_pass(ctx):
    rid = await ctx["db"].fetchval("select r.id::text from registrations r join passes p on p.registration_id = r.id limit 1")
    await ctx["db"].execute("update passes set revoked = true where registration_id = $1", uuid.UUID(rid))
    assert await worker.send_pass_email({**ctx, "send_mail": lambda m: None}, rid) == "skipped"
