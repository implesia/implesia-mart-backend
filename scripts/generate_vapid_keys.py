"""Generate a fresh VAPID ECDSA P-256 keypair for W3C Web Push.

Usage:
    uv run python scripts/generate_vapid_keys.py

Paste the printed lines into your backend `.env` file.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def main() -> None:
    vapid = Vapid()
    vapid.generate_keys()

    pub_bytes = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode("ascii")

    priv_num = vapid.private_key.private_numbers().private_value
    priv_bytes = priv_num.to_bytes(32, byteorder="big")
    private_b64 = base64.urlsafe_b64encode(priv_bytes).rstrip(b"=").decode("ascii")

    print("# Add these to implesia-mart-backend/.env:")
    print(f"VAPID_PUBLIC_KEY={public_b64}")
    print(f"VAPID_PRIVATE_KEY={private_b64}")
    print("VAPID_SUBJECT=mailto:support@implesia.com")


if __name__ == "__main__":
    main()
