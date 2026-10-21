import asyncio
import base64
import json
import uuid
from datetime import datetime, timezone

from tests.conftest import ADMIN, db_exec
from tests.test_registrations import form, unique_roll


# ---------- helpers ----------

async def make_staff(client, name="Riya", role="reviewer"):
    r = await client.post("/admin/staff", json={"name": name, "role": role}, headers=ADMIN)
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


async def make_device(client, gate="Main gate"):
    r = await client.post("/admin/devices", json={"gate": gate, "day": 1}, headers=ADMIN)
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["setup"]["token"]}, r.json()


async def registration_in_review(client, college_ids, upload, reasons=("name_mismatch",), roll=None, **over):
    reg = (await client.post("/registrations", json=form(college_ids, upload, roll_no=roll or unique_roll(), **over))).json()
    await db_exec("update registrations set status='review', reasons=$2, ocr='{\"name\":{\"score\":60}}' where id=$1",
                  uuid.UUID(reg["id"]), list(reasons))
    return reg


async def clear_queue():
    await db_exec("update registrations set status='rejected' where status='review'")


async def issued_pass(client, college_ids, upload, thumb=b"WEBPDATA"):
    """An approved registration with a pass, as the worker would leave it."""
    reg = (await client.post("/registrations", json=form(college_ids, upload, roll_no=unique_roll()))).json()
    rid = uuid.UUID(reg["id"])
    await db_exec("update registrations set status='approved' where id=$1", rid)
    row = await db_exec("insert into passes (registration_id, token, thumb) values ($1, $2, $3) returning id",
                        rid, "tok." + reg["id"], thumb)
    return reg, str(row[0]["id"])


# ---------- auth ----------

async def test_staff_and_admin_auth(client):
    assert (await client.get("/review/summary")).status_code == 401
    assert (await client.get("/admin/stats", headers={"Authorization": "Bearer nope"})).status_code == 401
    rev = await make_staff(client)
    assert (await client.get("/review/summary", headers=rev)).status_code == 200
    assert (await client.get("/admin/stats", headers=rev)).status_code == 403
    # the bootstrap admin can't claim cases: decisions must be traceable to a person
    assert (await client.post("/review/claim", json={}, headers=ADMIN)).status_code == 403


async def test_staff_login_url_and_revocation(client):
    r = await client.post("/admin/staff", json={"name": "Kabir", "role": "reviewer"}, headers=ADMIN)
    body = r.json()
    assert body["login_url"] == f"https://api.test/review#token={body['token']}"
    hdr = {"Authorization": "Bearer " + body["token"]}
    assert (await client.delete(f"/admin/staff/{body['id']}", headers=ADMIN)).status_code == 200
    assert (await client.get("/review/summary", headers=hdr)).status_code == 401


# ---------- review ----------

async def test_claim_approve_queues_pass(client, college_ids, upload, queue):
    await clear_queue()
    rev = await make_staff(client)
    reg = await registration_in_review(client, college_ids, upload)
    case = (await client.post("/review/claim", json={}, headers=rev)).json()["case"]
    assert case["id"] == reg["id"]
    assert case["card_url"].startswith("https://storage.test/view/id-cards/")
    assert case["reasons"][0]["code"] == "name_mismatch"

    r = await client.post(f"/review/{reg['id']}/decision", json={"decision": "approve", "name": "Aarav K Sharma"},
                          headers=rev)
    assert r.status_code == 200, r.text
    assert r.json()["corrections"] == {"name": "Aarav K Sharma"}
    assert ("issue_pass", reg["id"]) in queue.calls
    s = (await client.get(f"/status/{reg['status_token']}")).json()
    assert s["status"] == "approved" and s["name"] == "Aarav K Sharma" and s["reasons"] == []
    assert s["qr_token"] is None and "preparing" in s["message"]   # pass not issued yet
    actions = await db_exec("select reviewer, decision from review_actions where registration_id=$1", uuid.UUID(reg["id"]))
    assert actions[0]["decision"] == "approved" and actions[0]["reviewer"].startswith("Riya")


async def test_two_reviewers_never_get_the_same_case(client, college_ids, upload):
    await clear_queue()
    a, b = await make_staff(client, "Asha"), await make_staff(client, "Bina")
    regs = {(await registration_in_review(client, college_ids, upload))["id"] for _ in range(4)}
    ra, rb = await asyncio.gather(client.post("/review/claim", json={}, headers=a),
                                  client.post("/review/claim", json={}, headers=b))
    ca, cb = ra.json()["case"]["id"], rb.json()["case"]["id"]
    assert ca != cb and {ca, cb} <= regs
    # claiming again (e.g. after a page reload) gives back the case you already hold
    assert (await client.post("/review/claim", json={}, headers=a)).json()["case"]["id"] == ca


async def test_decision_needs_your_claim_and_a_reject_reason(client, college_ids, upload):
    await clear_queue()
    a, b = await make_staff(client, "Asha"), await make_staff(client, "Bina")
    reg = await registration_in_review(client, college_ids, upload)
    await client.post("/review/claim", json={}, headers=a)
    r = await client.post(f"/review/{reg['id']}/decision", json={"decision": "approve"}, headers=b)
    assert r.status_code == 409
    r = await client.post(f"/review/{reg['id']}/decision", json={"decision": "reject"}, headers=a)
    assert r.status_code == 422
    r = await client.post(f"/review/{reg['id']}/decision", json={"decision": "reject", "reason": "not_student"}, headers=a)
    assert r.status_code == 200
    s = (await client.get(f"/status/{reg['status_token']}")).json()
    assert s["status"] == "rejected" and "valid student ID" in s["reasons"][0]
    again = await client.post(f"/review/{reg['id']}/decision", json={"decision": "approve"}, headers=a)
    assert again.status_code == 409


async def test_reupload_request_lets_student_upload(client, college_ids, upload, queue):
    await clear_queue()
    rev = await make_staff(client)
    reg = await registration_in_review(client, college_ids, upload)
    await client.post("/review/claim", json={}, headers=rev)
    await client.post(f"/review/{reg['id']}/decision", json={"decision": "reupload"}, headers=rev)
    s = (await client.get(f"/status/{reg['status_token']}")).json()
    assert s["can_reupload"] and "clearer photo" in s["reasons"][0]
    r = await client.post(f"/status/{reg['status_token']}/reupload", json={"id_image_key": upload()})
    assert r.status_code == 200 and r.json()["status"] == "pending"


async def test_skip_releases_case_and_filter_by_reason(client, college_ids, upload):
    await clear_queue()
    rev = await make_staff(client)
    dup = await registration_in_review(client, college_ids, upload, reasons=("duplicate_card",))
    await registration_in_review(client, college_ids, upload, reasons=("no_face",))
    case = (await client.post("/review/claim", json={"reason": "duplicate_card"}, headers=rev)).json()["case"]
    assert case["id"] == dup["id"]
    await client.post(f"/review/{dup['id']}/release", headers=rev)
    other = await make_staff(client, "Other")
    case2 = (await client.post("/review/claim", json={"reason": "duplicate_card"}, headers=other)).json()["case"]
    assert case2["id"] == dup["id"]
    summary = (await client.get("/review/summary", headers=rev)).json()
    assert {r["reason"] for r in summary["by_reason"]} >= {"duplicate_card", "no_face"}


async def test_approving_a_second_live_roll_is_refused(client, college_ids, upload):
    await clear_queue()
    rev = await make_staff(client)
    roll = unique_roll()
    first = (await client.post("/registrations", json=form(college_ids, upload, roll_no=roll))).json()
    second = (await client.post("/registrations", json=form(college_ids, upload, roll_no=roll))).json()
    assert second["status"] == "review"
    await db_exec("update registrations set ocr='{}' where id=$1", uuid.UUID(second["id"]))
    case = (await client.post("/review/claim", json={}, headers=rev)).json()["case"]
    assert case["id"] == second["id"]
    assert [r["id"] for r in case["related"]] == [first["id"]]
    r = await client.post(f"/review/{second['id']}/decision", json={"decision": "approve"}, headers=rev)
    assert r.status_code == 409 and "Reject one" in r.json()["detail"]


async def test_cases_wait_for_ocr(client, college_ids, upload):
    await clear_queue()
    rev = await make_staff(client)
    roll = unique_roll()
    await client.post("/registrations", json=form(college_ids, upload, roll_no=roll))
    await client.post("/registrations", json=form(college_ids, upload, roll_no=roll))  # review, but no OCR yet
    assert (await client.post("/review/claim", json={}, headers=rev)).json()["case"] is None


# ---------- status page QR ----------

async def test_status_shows_qr_once_pass_exists(client, college_ids, upload):
    reg, pid = await issued_pass(client, college_ids, upload)
    s = (await client.get(f"/status/{reg['status_token']}")).json()
    assert s["qr_token"] == "tok." + reg["id"] and "below" in s["message"]
    await client.post(f"/admin/passes/{pid}/revoke", headers=ADMIN)
    assert (await client.get(f"/status/{reg['status_token']}")).json()["qr_token"] is None


# ---------- gate ----------

async def test_device_setup_qr(client):
    _, body = await make_device(client, "Lane 3")
    s = body["setup"]
    assert s["t"] == "moksha-gate-setup" and s["url"] == "https://api.test" and s["gate"] == "Lane 3" and s["day"] == 1
    assert s["key"] == "test-public-key" and s["token"].startswith("gate_")
    assert body["setup_qr"].startswith("data:image/png;base64,")


async def test_gate_needs_a_valid_device_token(client):
    assert (await client.get("/gate/manifest")).status_code == 401
    assert (await client.get("/gate/manifest", headers={"Authorization": "Bearer nope"})).status_code == 401
    dev, body = await make_device(client)
    assert (await client.get("/gate/manifest", headers=dev)).status_code == 200
    await client.delete(f"/admin/devices/{body['id']}", headers=ADMIN)
    assert (await client.get("/gate/manifest", headers=dev)).status_code == 401


async def test_manifest_full_then_incremental(client, college_ids, upload):
    dev, _ = await make_device(client)
    await db_exec("delete from checkins")
    await db_exec("delete from passes")
    made = [await issued_pass(client, college_ids, upload) for _ in range(5)]
    # an approved registration whose pass isn't signed yet is not sent
    reg = (await client.post("/registrations", json=form(college_ids, upload, roll_no=unique_roll()))).json()
    await db_exec("update registrations set status='approved' where id=$1", uuid.UUID(reg["id"]))
    await db_exec("insert into passes (registration_id) values ($1)", uuid.UUID(reg["id"]))

    p1 = (await client.get("/gate/manifest?limit=3", headers=dev)).json()
    assert p1["total"] == 5 and p1["has_more"] and len(p1["passes"]) == 3
    first = p1["passes"][0]
    assert set(first) == {"id", "name", "college", "roll_no", "thumb_b64", "revoked", "updated_at"}
    assert base64.b64decode(first["thumb_b64"]) == b"WEBPDATA"
    assert first["college"].startswith("Netaji") and first["revoked"] is False
    p2 = (await client.get(f"/gate/manifest?limit=3&since={p1['next_cursor']}", headers=dev)).json()
    assert p2["total"] is None and not p2["has_more"] and len(p2["passes"]) == 2
    ids = {p["id"] for p in p1["passes"] + p2["passes"]}
    assert ids == {pid for _, pid in made}

    # nothing changed: empty page, same cursor
    p3 = (await client.get(f"/gate/manifest?since={p2['next_cursor']}", headers=dev)).json()
    assert p3["passes"] == [] and p3["next_cursor"] == p2["next_cursor"]

    # revoking one pass and rejecting another's registration both show up as revoked
    await client.post(f"/admin/passes/{made[0][1]}/revoke", headers=ADMIN)
    p4 = (await client.get(f"/gate/manifest?since={p3['next_cursor']}", headers=dev)).json()
    assert [(p["id"], p["revoked"]) for p in p4["passes"]] == [(made[0][1], True)]
    await db_exec("update registrations set status='rejected' where id=$1", uuid.UUID(made[1][0]["id"]))
    full = (await client.get("/gate/manifest", headers=dev)).json()
    by_id = {p["id"]: p["revoked"] for p in full["passes"]}
    assert by_id[made[0][1]] and by_id[made[1][1]] and not by_id[made[2][1]]


def ci(pass_id, result="admitted", day=1, cid=None):
    return {"id": cid or str(uuid.uuid4()), "pass_id": pass_id, "scanned_at": datetime.now(timezone.utc).isoformat(),
            "result": result, "reason": "ok" if result == "admitted" else "already_used", "day": day}


async def test_checkins_sync_between_gates(client, college_ids, upload):
    await db_exec("delete from checkins")
    a, _ = await make_device(client, "Gate A")
    b, _ = await make_device(client, "Gate B")
    _, p1 = await issued_pass(client, college_ids, upload)
    _, p2 = await issued_pass(client, college_ids, upload)

    first = ci(p1)
    r = (await client.post("/gate/checkins", json={"device_id": "phone-a", "gate": "Gate A", "since": None,
                                                   "checkins": [first, ci(p2, "denied")]}, headers=a)).json()
    assert r["accepted"] == [first["id"], r["accepted"][1]] and r["conflicts"] == [] and r["remote"] == []
    cursor_a = r["next_since"]

    # B pulls everything from A, then admits p1 again on the same day: conflict
    r = (await client.post("/gate/checkins", json={"device_id": "phone-b", "gate": "Gate B", "since": None,
                                                   "checkins": []}, headers=b)).json()
    assert {x["pass_id"] for x in r["remote"]} == {p1, p2}
    assert all(x["device_id"] == "phone-a" and x["gate"] == "Gate A" for x in r["remote"])
    second = ci(p1)
    r = (await client.post("/gate/checkins", json={"device_id": "phone-b", "gate": "Gate B", "since": r["next_since"],
                                                   "checkins": [second, ci(p1, day=2)]}, headers=b)).json()
    assert r["conflicts"] == [second["id"]]          # day 2 is a different day: no conflict

    # A retries its first batch (phones retry): accepted again, nothing duplicated
    r = (await client.post("/gate/checkins", json={"device_id": "phone-a", "gate": "Gate A", "since": cursor_a,
                                                   "checkins": [first]}, headers=a)).json()
    assert r["accepted"] == [first["id"]] and r["conflicts"] == []
    assert sorted(x["id"] for x in r["remote"]) == sorted([second["id"], r["remote"][1]["id"]]) and len(r["remote"]) == 2
    n = await db_exec("select count(*) from checkins where id=$1", first["id"])
    assert n[0]["count"] == 1

    # unknown pass ids (scans of passes not on the list) are still stored
    r = (await client.post("/gate/checkins", json={"device_id": "phone-a", "gate": "Gate A", "since": r["next_since"],
                                                   "checkins": [ci("not-a-real-pass", "denied")]}, headers=a))
    assert r.status_code == 200
    bad = await client.post("/gate/checkins", json={"device_id": "phone-a", "checkins": [dict(ci(p1), result="maybe")]},
                            headers=a)
    assert bad.status_code == 422


async def test_concurrent_admissions_flag_exactly_one_conflict(client, college_ids, upload):
    await db_exec("delete from checkins")
    devs = [(await make_device(client, f"Gate {i}"))[0] for i in range(4)]
    _, pid = await issued_pass(client, college_ids, upload)
    res = await asyncio.gather(*[
        client.post("/gate/checkins", json={"device_id": f"phone-{i}", "checkins": [ci(pid)]}, headers=d)
        for i, d in enumerate(devs)])
    conflicts = sum(len(r.json()["conflicts"]) for r in res)
    assert conflicts == 3   # the first admission is fine; the other three are flagged


# ---------- admin ----------

async def test_admin_stats_search_resend_approve(client, college_ids, upload, queue):
    reg, pid = await issued_pass(client, college_ids, upload)
    stats = (await client.get("/admin/stats", headers=ADMIN)).json()
    assert stats["registrations"]["approved"] >= 1 and stats["passes"]["issued"] >= 1

    email = (await db_exec("select email from registrations where id=$1", uuid.UUID(reg["id"])))[0]["email"]
    res = (await client.get("/admin/search", params={"q": email}, headers=ADMIN)).json()["results"]
    assert len(res) == 1 and res[0]["pass"]["id"] == pid and res[0]["status_url"].endswith(reg["status_token"])

    r = await client.post(f"/admin/registrations/{reg['id']}/resend", headers=ADMIN)
    assert r.json() == {"queued": "email"} and ("send_pass_email", reg["id"]) in queue.calls

    pending = (await client.post("/registrations", json=form(college_ids, upload, roll_no=unique_roll()))).json()
    assert (await client.post(f"/admin/registrations/{pending['id']}/resend", headers=ADMIN)).status_code == 409
    r = await client.post(f"/admin/registrations/{pending['id']}/approve", headers=ADMIN)
    assert r.status_code == 200 and ("issue_pass", pending["id"]) in queue.calls
    assert (await client.post(f"/admin/registrations/{pending['id']}/approve", headers=ADMIN)).status_code == 409

    r = (await client.post("/admin/passes/issue-missing", headers=ADMIN)).json()
    assert r["queued"] >= 1


async def test_pages_are_served(client):
    for page in ("/review", "/admin"):
        r = await client.get(page)
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
        assert r.headers["cache-control"] == "no-store"
