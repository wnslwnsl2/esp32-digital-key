"""ECC P-256 key generation and ECDSA signing."""

import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives import hashes, serialization


def get_key_dir() -> Path:
    d = Path.home() / ".dk-client"
    d.mkdir(exist_ok=True)
    return d


def generate_key_id() -> str:
    """Generate a 16-char hex key ID."""
    return os.urandom(8).hex()


def load_or_create_key(key_id: str | None = None) -> tuple[str, ec.EllipticCurvePrivateKey]:
    """Load existing key or create a new one.

    Returns (key_id, private_key).
    """
    key_dir = get_key_dir()

    if key_id:
        pem_path = key_dir / f"{key_id}.pem"
        if pem_path.exists():
            pem = pem_path.read_bytes()
            pk = serialization.load_pem_private_key(pem, password=None)
            return key_id, pk

    # Create new key
    if not key_id:
        key_id = generate_key_id()

    pk = ec.generate_private_key(ec.SECP256R1())
    pem = pk.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pem_path = key_dir / f"{key_id}.pem"
    pem_path.write_bytes(pem)
    print(f"[crypto] new key generated: {key_id} → {pem_path}")

    return key_id, pk


def get_public_key_bytes(pk: ec.EllipticCurvePrivateKey) -> bytes:
    """Return uncompressed P-256 public key (65 bytes: 04 + X + Y)."""
    return pk.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )


def sign_challenge(pk: ec.EllipticCurvePrivateKey, challenge: bytes) -> bytes:
    """Sign SHA-256(challenge) with ECDSA, return DER signature."""
    return pk.sign(challenge, ec.ECDSA(hashes.SHA256()))
