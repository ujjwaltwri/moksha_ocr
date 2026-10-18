"""Signed QR pass tokens: base64url(payload) + "." + base64url(Ed25519 signature).

The payload carries no personal data. Gate phones verify with the public key, offline.
"""

import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_pass(key: Ed25519PrivateKey, payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return f"{b64(body)}.{b64(key.sign(body))}"


def verify_pass(pub: Ed25519PublicKey, token: str) -> dict:
    """Returns the payload, or raises ValueError if the token is malformed or forged."""
    try:
        body_b64, sig_b64 = token.split(".")
        body = unb64(body_b64)
        pub.verify(unb64(sig_b64), body)
        return json.loads(body)
    except Exception as e:
        raise ValueError("invalid pass") from e
