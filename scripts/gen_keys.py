"""Generate the Ed25519 key pair for signing QR passes. Run ONCE, then keep the private key secret.

    python scripts/gen_keys.py

Prints:
  PASS_SIGNING_KEY  -> put in the server's .env / secret store (never commit it)
  PASS_PUBLIC_KEY   -> goes into the gate app
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate()
priv = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


print(f"PASS_SIGNING_KEY={b64(priv)}")
print(f"PASS_PUBLIC_KEY={b64(pub)}")
