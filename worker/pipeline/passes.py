"""Pass token signing, gate thumbnail and the pass email. Pure functions; the jobs do I/O.

Token format (must match api/app/signing.py and app/lib/services/pass_verifier.dart):
    base64url(body) + "." + base64url(Ed25519 signature over body), no padding
    body = compact JSON, e.g. {"d":[1,2,3],"e":"moksha26","iat":1761300000,"p":"<pass uuid>","v":1}
"""

import base64
import html
import io
import json
import time
from email.message import EmailMessage
from email.utils import make_msgid

import qrcode
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image, ImageOps

THUMB_PX = 160


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def load_key(b64: str) -> Ed25519PrivateKey:
    raw = base64.urlsafe_b64decode(b64.strip() + "=" * (-len(b64.strip()) % 4))
    if len(raw) != 32:
        raise ValueError("PASS_SIGNING_KEY must be the 32-byte key printed by scripts/gen_keys.py")
    return Ed25519PrivateKey.from_private_bytes(raw)


def sign_pass(key: Ed25519PrivateKey, pass_id: str, event: str, days: list[int], iat: int | None = None) -> str:
    payload = {"v": 1, "p": pass_id, "e": event, "d": sorted(days), "iat": iat or int(time.time())}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return f"{b64url(body)}.{b64url(key.sign(body))}"


def gate_thumb(face_jpeg: bytes) -> bytes:
    """Square 160x160 WebP of the face crop (~5-9 KB) for the gate screen."""
    img = Image.open(io.BytesIO(face_jpeg)).convert("RGB")
    img = ImageOps.fit(img, (THUMB_PX, THUMB_PX), method=Image.LANCZOS, centering=(0.5, 0.4))
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=80, method=6)
    return buf.getvalue()


def qr_png(token: str) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=3)
    qr.add_data(token)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, "PNG")
    return buf.getvalue()


def pass_email(*, to: str, sender: str, name: str, college: str, token: str, status_url: str,
               event_name: str, days_label: str, reply_to: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Your {event_name} entry pass"
    msg["From"] = sender
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    cid = make_msgid(domain="moksha.pass")
    n, c = html.escape(name), html.escape(college)
    msg.set_content(
        f"Hi {name},\n\n"
        f"You're approved for {event_name} ({days_label}).\n\n"
        f"Your entry pass QR code is shown in this email, and is always on your status page:\n{status_url}\n\n"
        "At the gate:\n"
        "- Have this QR ready on your phone (a screenshot works offline).\n"
        "- Bring your physical college ID card. The volunteer checks your face against it.\n"
        "- The pass is for you only. It works once per day; after entry you get a wristband.\n\n"
        f"See you at {event_name}!\n")
    msg.add_alternative(f"""\
<!doctype html><html><body style="font-family:Arial,sans-serif;color:#1c1c1c;max-width:520px;margin:auto">
<h2 style="margin-bottom:4px">Your {html.escape(event_name)} entry pass</h2>
<p style="margin-top:0;color:#555">{n} &middot; {c} &middot; {html.escape(days_label)}</p>
<p style="text-align:center"><img src="cid:{cid[1:-1]}" alt="Entry pass QR code" width="280" height="280"></p>
<p><b>At the gate</b></p>
<ul>
<li>Have this QR ready on your phone. A screenshot works without internet.</li>
<li>Bring your <b>physical college ID card</b>. The volunteer checks your face against it.</li>
<li>The pass is for you only and works once per day. After entry you get a wristband.</li>
</ul>
<p>Lost this email? Your pass is always on your <a href="{html.escape(status_url)}">status page</a>.</p>
</body></html>""", subtype="html")
    msg.get_payload()[1].add_related(qr_png(token), maintype="image", subtype="png", cid=cid,
                                     filename="moksha-pass.png")
    return msg
