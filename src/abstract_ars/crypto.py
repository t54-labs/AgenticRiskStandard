from __future__ import annotations

import hashlib
import json

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey


def canonicalize(obj: dict) -> bytes:
    """RFC 8785 JCS-subset canonicalization.

    For the data types in ARS (strings, ints, bools, null, nested dicts/lists)
    sorted-key JSON with minimal whitespace is sufficient.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_agreement_hash(agreement: dict) -> str:
    """SHA-256 hex digest of the canonicalized agreement."""
    return hashlib.sha256(canonicalize(agreement)).hexdigest()


def envelope_body(envelope_dict: dict) -> dict:
    """Return the signable portion of an envelope (everything except 'signature')."""
    return {k: v for k, v in envelope_dict.items() if k != "signature"}


def sign_envelope(signing_key: SigningKey, body: dict) -> str:
    """Sign canonicalized *body* with Ed25519, return hex-encoded 64-byte signature."""
    canonical = canonicalize(body)
    signed = signing_key.sign(canonical)
    return signed.signature.hex()


def verify_envelope_signature(pubkey_hex: str, body: dict, signature_hex: str) -> bool:
    """Verify Ed25519 signature. Returns True or raises BadSignatureError."""
    vk = VerifyKey(bytes.fromhex(pubkey_hex))
    canonical = canonicalize(body)
    # signature hex = canonical + private key
    sig_bytes = bytes.fromhex(signature_hex)
    try:
        vk.verify(canonical, sig_bytes)
        return True
    except BadSignatureError:
        return False


def generate_keypair() -> tuple[SigningKey, str]:
    """Generate Ed25519 keypair. Returns (signing_key, verify_key_hex)."""
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()
