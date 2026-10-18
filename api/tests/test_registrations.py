import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import get_settings
from app.signing import sign_pass, verify_pass


def form(college_ids, upload, **over):
    data = {
        "name": "Aarav  Sharma",
        "college_id": college_ids["nsut"],
        "roll_no": "2022 UIC-3501",
        "course": "B.Tech ICE, 3rd year",
        "email": f"aarav.{uuid.uuid4().hex[:8]}@nsut.ac.in",
        "phone": "+91 98765 43210",
        "id_image_key": upload(),
        "consent_entry": True,
        "consent_dataset": False,
        "consent_version": get_settings().consent_version,
    }
    data.update(over)
    return data


def unique_roll():
    return f"2022UIC{uuid.uuid4().int % 10000:04d}X"


async def test_colleges_lists_only_allowed(client):
    r = await client.get("/colleges")
    assert r.status_code == 200
    names = [c["name"] for c in r.json()]
    assert "Not Invited College" not in names
    assert names == sorted(names)


async def test_presign_rejects_bad_type_and_size(client):
    assert (await client.post("/uploads/presign", json={"content_type": "application/pdf", "size": 10})).status_code == 422
    assert (await client.post("/uploads/presign", json={"content_type": "image/jpeg", "size": 9 * 2**20})).status_code == 422
    r = await client.post("/uploads/presign", json={"content_type": "image/JPEG", "size": 10_000})
    assert r.status_code == 200
    assert r.json()["key"].startswith("id-cards/") and r.json()["key"].endswith(".jpg")


async def test_register_happy_path(client, college_ids, upload, queue):
    r = await client.post("/registrations", json=form(college_ids, upload, roll_no="2022 uic-3501"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["status_url"].endswith(body["status_token"])
    assert queue.jobs == [body["id"]]

    s = (await client.get(f"/status/{body['status_token']}")).json()
    assert s["name"] == "Aarav Sharma"  # whitespace collapsed
    assert s["college"].startswith("Netaji")
    assert s["status"] == "pending" and s["reasons"] == [] and s["qr_token"] is None


async def test_roll_is_normalised_and_college_email_detected(client, college_ids, upload):
    roll = unique_roll()
    r = await client.post("/registrations", json=form(college_ids, upload, roll_no=f"{roll[:4]} {roll[4:7]}-{roll[7:]}".lower()))
    assert r.status_code == 201
    import asyncpg

    from tests.conftest import TEST_DB, plain_dsn

    conn = await asyncpg.connect(plain_dsn(TEST_DB))
    row = await conn.fetchrow("select roll_no, college_email, phone from registrations where id=$1", uuid.UUID(r.json()["id"]))
    await conn.close()
    assert row["roll_no"] == roll and row["college_email"] is True and row["phone"] == "9876543210"


async def test_duplicate_email_is_rejected(client, college_ids, upload):
    f = form(college_ids, upload, roll_no=unique_roll())
    assert (await client.post("/registrations", json=f)).status_code == 201
    f2 = dict(f, roll_no=unique_roll(), id_image_key=upload(), email=f["email"].upper())
    r = await client.post("/registrations", json=f2)
    assert r.status_code == 409


async def test_duplicate_roll_goes_to_review_and_flags_both(client, college_ids, upload):
    roll = unique_roll()
    first = (await client.post("/registrations", json=form(college_ids, upload, roll_no=roll))).json()
    second = await client.post("/registrations", json=form(college_ids, upload, roll_no=roll.lower()))
    assert second.status_code == 201
    assert second.json()["status"] == "review"

    s1 = (await client.get(f"/status/{first['status_token']}")).json()
    s2 = (await client.get(f"/status/{second.json()['status_token']}")).json()
    assert any("already registered" in m for m in s1["reasons"])
    assert any("already registered" in m for m in s2["reasons"])
    assert s1["status"] == "pending"  # existing one keeps its status, just flagged


async def test_same_roll_different_college_is_fine(client, college_ids, upload):
    roll = unique_roll()
    a = await client.post("/registrations", json=form(college_ids, upload, roll_no=roll))
    b = await client.post("/registrations", json=form(college_ids, upload, roll_no=roll, college_id=college_ids["dtu"], email=f"x{uuid.uuid4().hex[:6]}@dtu.ac.in"))
    assert a.json()["status"] == b.json()["status"] == "pending"


async def test_other_college_is_flagged(client, college_ids, upload):
    r = await client.post("/registrations", json=form(college_ids, upload, college_id=None, college_other="Some DU College", roll_no=unique_roll(), email=f"s{uuid.uuid4().hex[:6]}@gmail.com"))
    assert r.status_code == 201
    s = (await client.get(f"/status/{r.json()['status_token']}")).json()
    assert s["college"] == "Some DU College"
    assert any("isn't on our list" in m for m in s["reasons"])


async def test_validation_errors(client, college_ids, upload):
    cases = [
        dict(consent_entry=False),
        dict(college_id=None),  # neither college nor "Other"
        dict(college_other="Both"),  # both
        dict(id_image_key="../../etc/passwd"),
        dict(phone="12345"),
        dict(email="not-an-email"),
    ]
    for over in cases:
        r = await client.post("/registrations", json=form(college_ids, upload, roll_no=unique_roll(), **over))
        assert r.status_code == 422, over


async def test_disallowed_college_missing_upload_and_old_form(client, college_ids, upload):
    r = await client.post("/registrations", json=form(college_ids, upload, college_id=college_ids["banned"], roll_no=unique_roll()))
    assert r.status_code == 422
    r = await client.post("/registrations", json=form(college_ids, upload, roll_no=unique_roll(), id_image_key=f"id-cards/{uuid.uuid4()}.jpg"))
    assert r.status_code == 422 and "didn't receive" in r.json()["detail"]
    r = await client.post("/registrations", json=form(college_ids, upload, roll_no=unique_roll(), id_image_key=upload(size=9 * 2**20)))
    assert r.status_code == 422
    r = await client.post("/registrations", json=form(college_ids, upload, roll_no=unique_roll(), consent_version="old"))
    assert r.status_code == 409


async def test_unknown_status_token(client):
    assert (await client.get("/status/nope")).status_code == 404


async def test_reupload_only_when_photo_was_the_problem(client, college_ids, upload, queue):
    import asyncpg

    from tests.conftest import TEST_DB, plain_dsn

    reg = (await client.post("/registrations", json=form(college_ids, upload, roll_no=unique_roll()))).json()
    tok = reg["status_token"]
    assert (await client.post(f"/status/{tok}/reupload", json={"id_image_key": upload()})).status_code == 409

    conn = await asyncpg.connect(plain_dsn(TEST_DB))
    await conn.execute("update registrations set status='review', reasons='{poor_image}' where status_token=$1", tok)
    await conn.close()
    assert (await client.get(f"/status/{tok}")).json()["can_reupload"] is True

    r = await client.post(f"/status/{tok}/reupload", json={"id_image_key": upload()})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending" and r.json()["reasons"] == []
    assert queue.jobs.count(reg["id"]) == 2


def test_pass_signing_roundtrip():
    key = Ed25519PrivateKey.generate()
    tok = sign_pass(key, {"v": 1, "p": "abc", "e": "moksha26", "d": [1, 2]})
    assert verify_pass(key.public_key(), tok)["p"] == "abc"
    body, sig = tok.split(".")
    import pytest

    with pytest.raises(ValueError):
        verify_pass(key.public_key(), body[:-2] + "AA." + sig)
    with pytest.raises(ValueError):
        verify_pass(Ed25519PrivateKey.generate().public_key(), tok)


async def test_simultaneous_same_roll_never_creates_two_live_registrations(client, college_ids, upload):
    import asyncio

    roll = unique_roll()
    results = await asyncio.gather(
        *[client.post("/registrations", json=form(college_ids, upload, roll_no=roll)) for _ in range(6)]
    )
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    statuses = sorted(r.json()["status"] for r in results)
    assert statuses.count("pending") == 1 and statuses.count("review") == 5


async def test_form_config(client):
    r = (await client.get("/form-config")).json()
    assert r["consent_version"] == get_settings().consent_version
    assert "30 days" in r["consent_entry_text"]
    assert "image/jpeg" in r["allowed_content_types"]
