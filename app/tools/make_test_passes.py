#!/usr/bin/env python3
"""Make test data for the gate app: a TEST key pair, fake students with
photos, a pass list, and a page of QR passes covering every gate outcome.

    pip install cryptography "qrcode[pil]" pillow
    python tools/make_test_passes.py            # 40 students
    python tools/make_test_passes.py --count 25000   # load test

Writes tools/test_data/. The key here is for testing only; the fest key is
made by the backend's scripts/gen_keys.py and never leaves the server.
"""
import argparse
import base64
import hashlib
import io
import json
import random
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "test_data"
EVENT = "moksha26"

FIRST = ["Aarav", "Ananya", "Ishaan", "Diya", "Kabir", "Meera", "Rohan", "Saanvi",
         "Vihaan", "Aditi", "Arjun", "Kavya", "Dev", "Nisha", "Yash", "Riya",
         "Aryan", "Tanvi", "Kunal", "Pooja"]
LAST = ["Sharma", "Verma", "Gupta", "Singh", "Iyer", "Nair", "Reddy", "Jain",
        "Malhotra", "Kapoor", "Bansal", "Chopra", "Mehta", "Rao", "Das"]
COLLEGES = ["Netaji Subhas University of Technology", "Delhi Technological University",
            "IGDTUW", "Hansraj College", "St. Stephen's College",
            "Shri Ram College of Commerce", "IIIT Delhi", "Miranda House"]


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign_pass(key: Ed25519PrivateKey, payload: dict) -> str:
    """Same as api/signing.py in the build spec."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    return f"{b64url(body)}.{b64url(key.sign(body))}"


def load_or_make_key() -> Ed25519PrivateKey:
    path = OUT / "test_key.json"
    if path.exists():
        raw = base64.urlsafe_b64decode(json.loads(path.read_text())["private"] + "==")
        return Ed25519PrivateKey.from_private_bytes(raw)
    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(serialization.Encoding.Raw,
                             serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    path.write_text(json.dumps({"private": b64url(priv),
                                "public": public_key_b64(key),
                                "note": "TEST KEY ONLY"}, indent=2))
    return key


def public_key_b64(key: Ed25519PrivateKey) -> str:
    return b64url(key.public_key().public_bytes(serialization.Encoding.Raw,
                                                serialization.PublicFormat.Raw))


def avatar(name: str, size: int = 160) -> bytes:
    """A stand-in face photo: coloured square with initials, as WebP."""
    h = hashlib.md5(name.encode()).digest()
    img = Image.new("RGB", (size, size), (60 + h[0] % 150, 60 + h[1] % 150, 60 + h[2] % 150))
    d = ImageDraw.Draw(img)
    d.ellipse([size * .3, size * .18, size * .7, size * .58], fill=(240, 220, 200))
    d.ellipse([size * .15, size * .6, size * .85, size * 1.2], fill=(240, 220, 200))
    initials = "".join(p[0] for p in name.split()[:2])
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:
        font = ImageFont.load_default()
    d.text((8, 6), initials, fill="white", font=font)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=70)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=40)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    key = load_or_make_key()
    rng = random.Random(7)
    now = int(time.time())

    passes, scenarios = [], []
    photo_cache = {}
    for i in range(args.count):
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        pid = str(uuid.UUID(int=rng.getrandbits(128)))
        if i < 200 or name not in photo_cache:  # big runs reuse photos
            photo_cache[name] = base64.b64encode(avatar(name)).decode()
        passes.append({
            "id": pid,
            "name": name,
            "college": rng.choice(COLLEGES),
            "roll_no": f"2023UIC{3000 + i}",
            "thumb_b64": photo_cache[name],
            "revoked": False,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    def tok(p, days=(1, 2, 3), event=EVENT):
        return sign_pass(key, {"v": 1, "p": p["id"], "e": event, "d": list(days), "iat": now})

    # Scenarios for the test sheet.
    for p in passes[:6]:
        scenarios.append(("green", "Valid pass (scan twice: 2nd time is ALREADY USED)", p, tok(p)))
    passes[6]["revoked"] = True
    scenarios.append(("red", "PASS CANCELLED (revoked)", passes[6], tok(passes[6])))
    scenarios.append(("red", "NOT FOR TODAY (Day 2 only, phone set to Day 1)",
                      passes[7], tok(passes[7], days=[2])))
    scenarios.append(("red", "WRONG EVENT", passes[8], tok(passes[8], event="engifest26")))
    forged = tok(passes[9])
    body, sig = forged.split(".")
    fake_body = b64url(json.dumps({"v": 1, "p": passes[10]["id"], "e": EVENT, "d": [1, 2, 3],
                                   "iat": now}, separators=(",", ":")).encode())
    scenarios.append(("red", "INVALID PASS (payload swapped, signature kept)", passes[10],
                      f"{fake_body}.{sig}"))
    ghost = {"id": str(uuid.uuid4()), "name": "(not in list)"}
    scenarios.append(("red", "PASS NOT FOUND (signed, but not in the pass list)", ghost, tok(ghost)))
    scenarios.append(("red", "NOT A PASS (any other QR)", {"name": "-"}, "https://example.com"))

    (OUT / "manifest.json").write_text(json.dumps({"passes": passes}))
    (OUT / "scenarios.json").write_text(json.dumps(
        [{"kind": k, "label": l, "name": p.get("name"), "token": t} for k, l, p, t in scenarios],
        indent=2))

    pub = public_key_b64(key)
    print(f"Wrote {len(passes)} passes and {len(scenarios)} test QRs to {OUT}")
    print("\nPublic key for the app build:")
    print(f"  --dart-define=PASS_PUBLIC_KEY={pub}")
    print("\nNext: python tools/mock_server.py, then open the address it prints and scan the setup code.")


if __name__ == "__main__":
    main()
