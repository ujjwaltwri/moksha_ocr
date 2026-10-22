"""Check a deployed API end to end with a fake ID card. Run from anywhere:

    python scripts/smoke_test.py https://api.example.com you@example.com
    python scripts/smoke_test.py https://api.example.com you@example.com --admin-token <ADMIN_TOKEN>

1. health, form config, colleges
2. upload a synthetic card to storage and register (as the website form does)
3. wait for the OCR worker to process it (it has no face, so it lands in review)
4. with --admin-token: approve it at the help desk, wait for the pass, and the pass email goes to
   the address you gave. Check your inbox (and spam). Then revoke it so it can't be used.
The test registration is labelled SMOKE TEST; revoke or ignore it afterwards.
"""

import argparse
import io
import sys
import time
import uuid

import httpx
from PIL import Image, ImageDraw, ImageFont

p = argparse.ArgumentParser()
p.add_argument("api")
p.add_argument("email")
p.add_argument("--admin-token")
a = p.parse_args()
api = a.api.rstrip("/")
c = httpx.Client(timeout=30)


def step(ok, msg):
    print(("OK   " if ok else "FAIL ") + msg)
    if not ok:
        sys.exit(1)


r = c.get(api + "/healthz")
step(r.status_code == 200, f"health ({r.status_code})")
cfg = c.get(api + "/form-config").json()
step("consent_version" in cfg, f"form config, consent version {cfg.get('consent_version')}")
colleges = c.get(api + "/colleges").json()
step(len(colleges) > 0, f"{len(colleges)} colleges loaded")
college = colleges[0]

roll = f"SMOKE{uuid.uuid4().int % 10**6:06d}"
img = Image.new("RGB", (1400, 880), "white")
d = ImageDraw.Draw(img)
try:
    f = ImageFont.truetype("DejaVuSans.ttf", 44)
except OSError:
    f = ImageFont.load_default()
d.rectangle([0, 0, 1400, 150], fill=(20, 60, 140))
d.text((40, 50), college["name"].upper(), fill="white", font=f)
d.text((420, 260), "Name: SMOKE TEST", fill="black", font=f)
d.text((420, 340), f"Roll No: {roll}", fill="black", font=f)
buf = io.BytesIO()
img.save(buf, "JPEG", quality=90)
data = buf.getvalue()

pre = c.post(api + "/uploads/presign", json={"content_type": "image/jpeg", "size": len(data)}).json()
up = c.post(pre["url"], data=pre["fields"], files={"file": ("card.jpg", data, "image/jpeg")})
step(up.status_code in (200, 201, 204), f"upload to storage ({up.status_code})")
reg = c.post(api + "/registrations", json={
    "name": "Smoke Test", "college_id": college["id"], "roll_no": roll, "email": a.email,
    "id_image_key": pre["key"], "consent_entry": True, "consent_dataset": False,
    "consent_version": cfg["consent_version"]})
step(reg.status_code == 201, f"registration ({reg.status_code} {reg.text[:120]})")
token = reg.json()["status_token"]
print("     status link:", reg.json()["status_url"])

for _ in range(60):
    s = c.get(f"{api}/status/{token}").json()
    if s["status"] not in ("pending", "processing"):
        break
    time.sleep(2)
step(s["status"] in ("review", "approved", "rejected"), f"OCR worker processed it: {s['status']} {s['reasons']}")

if not a.admin_token:
    print("Done. Add --admin-token to also test pass issuing and email.")
    sys.exit(0)

H = {"Authorization": "Bearer " + a.admin_token}
rid = reg.json()["id"]
r = c.post(f"{api}/admin/registrations/{rid}/approve", headers=H)
step(r.status_code == 200, f"help-desk approve ({r.status_code})")
for _ in range(30):
    s = c.get(f"{api}/status/{token}").json()
    if s["qr_token"]:
        break
    time.sleep(2)
step(bool(s["qr_token"]), "pass issued (worker signed it)")
for _ in range(30):
    res = c.get(f"{api}/admin/search", params={"q": rid}, headers=H).json()["results"][0]["pass"]
    if res["email_sent_at"] or res["email_error"]:
        break
    time.sleep(2)
step(bool(res["email_sent_at"]), f"pass email sent to {a.email}" if res["email_sent_at"] else f"email failed: {res['email_error']}")
c.post(f"{api}/admin/passes/{res['id']}/revoke", headers=H)
print("OK   test pass revoked. Check your inbox for the email (and spam).")
