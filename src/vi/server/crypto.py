"""ES256 (ECDSA P-256) cryptographic operations for VI credential chain.

Wraps the `verifiable-intent` SDK for SD-JWT creation and verification.
The base ARS Ed25519 operations in ars.crypto remain unchanged — this module
provides the ES256 layer used exclusively for the VI credential chain.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDSA,
    SECP256R1,
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
)
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


# ── Key generation ───────────────────────────────────────────────────────────


def generate_es256_keypair() -> tuple[EllipticCurvePrivateKey, dict]:
    """Generate an ES256 (P-256) keypair. Returns (private_key, public_jwk)."""
    private_key = ec.generate_private_key(SECP256R1())
    return private_key, public_key_to_jwk(private_key.public_key())


# ── JWK conversion ──────────────────────────────────────────────────────────


def _b64url(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Base64url decode with padding restoration."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def public_key_to_jwk(public_key: EllipticCurvePublicKey) -> dict:
    """Convert an EC public key to JWK dict."""
    numbers = public_key.public_numbers()
    x_bytes = numbers.x.to_bytes(32, "big")
    y_bytes = numbers.y.to_bytes(32, "big")
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(x_bytes),
        "y": _b64url(y_bytes),
    }


def jwk_to_public_key(jwk: dict) -> EllipticCurvePublicKey:
    """Convert a JWK dict to an EC public key."""
    x = int.from_bytes(_b64url_decode(jwk["x"]), "big")
    y = int.from_bytes(_b64url_decode(jwk["y"]), "big")
    numbers = ec.EllipticCurvePublicNumbers(x, y, SECP256R1())
    return numbers.public_key()


def private_key_to_jwk(private_key: EllipticCurvePrivateKey) -> dict:
    """Convert an EC private key to JWK dict (includes 'd' parameter)."""
    pub_jwk = public_key_to_jwk(private_key.public_key())
    d_bytes = private_key.private_numbers().private_value.to_bytes(32, "big")
    pub_jwk["d"] = _b64url(d_bytes)
    return pub_jwk


def jwk_to_private_key(jwk: dict) -> EllipticCurvePrivateKey:
    """Convert a JWK dict (with 'd') to an EC private key."""
    d = int.from_bytes(_b64url_decode(jwk["d"]), "big")
    x = int.from_bytes(_b64url_decode(jwk["x"]), "big")
    y = int.from_bytes(_b64url_decode(jwk["y"]), "big")
    public_numbers = ec.EllipticCurvePublicNumbers(x, y, SECP256R1())
    private_numbers = ec.EllipticCurvePrivateNumbers(d, public_numbers)
    return private_numbers.private_key()


# ── JWK Thumbprint (RFC 7638) ───────────────────────────────────────────────


def jwk_thumbprint(jwk: dict) -> str:
    """Compute RFC 7638 JWK Thumbprint (SHA-256 hex).

    For EC keys, the required members are: crv, kty, x, y (sorted).
    """
    required = {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"], "y": jwk["y"]}
    canonical = json.dumps(required, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── ES256 signing / verification ────────────────────────────────────────────


def es256_sign(private_key: EllipticCurvePrivateKey, data: bytes) -> bytes:
    """Sign data with ES256 (ECDSA + SHA-256 on P-256). Returns DER signature."""
    return private_key.sign(data, ECDSA(SHA256()))


def es256_verify(
    public_key: EllipticCurvePublicKey, data: bytes, signature: bytes
) -> bool:
    """Verify an ES256 signature. Returns True or False."""
    try:
        public_key.verify(signature, data, ECDSA(SHA256()))
        return True
    except Exception:
        return False


# ── Simple SD-JWT helpers ────────────────────────────────────────────────────
# These provide a minimal SD-JWT implementation for the VI credential chain.
# In production, these would delegate to the verifiable-intent SDK.


def create_sd_jwt(
    issuer_private_key: EllipticCurvePrivateKey,
    payload: dict,
    disclosures: list[dict] | None = None,
) -> str:
    """Create a minimal SD-JWT: base64url(header).base64url(payload).sig~disclosures~

    This is a simplified implementation. In production, use the verifiable-intent SDK.
    """
    header = {"alg": "ES256", "typ": "sd+jwt"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = es256_sign(issuer_private_key, signing_input)
    sig_b64 = _b64url(sig)

    jwt = f"{header_b64}.{payload_b64}.{sig_b64}"

    # Append disclosures
    parts = [jwt]
    if disclosures:
        for d in disclosures:
            d_json = json.dumps(d, separators=(",", ":")).encode()
            parts.append(_b64url(d_json))
    parts.append("")  # trailing ~ separator
    return "~".join(parts)


def decode_sd_jwt(serialized: str) -> dict:
    """Decode an SD-JWT, returning {jwt, disclosures}."""
    parts = serialized.split("~")
    jwt_part = parts[0]
    disclosure_parts = [p for p in parts[1:] if p]

    jwt_segments = jwt_part.split(".")
    payload_b64 = jwt_segments[1]
    payload = json.loads(_b64url_decode(payload_b64))

    disclosures = []
    for d in disclosure_parts:
        disclosures.append(json.loads(_b64url_decode(d)))

    return {"jwt": jwt_part, "payload": payload, "disclosures": disclosures}


def verify_sd_jwt_signature(
    serialized: str, issuer_public_key: EllipticCurvePublicKey,
) -> bool:
    """Verify the issuer signature on an SD-JWT."""
    jwt_part = serialized.split("~")[0]
    segments = jwt_part.split(".")
    if len(segments) != 3:
        return False
    signing_input = f"{segments[0]}.{segments[1]}".encode("ascii")
    sig = _b64url_decode(segments[2])
    return es256_verify(issuer_public_key, signing_input, sig)


def compute_sd_hash(serialized: str) -> str:
    """Compute SHA-256 hash of a serialized SD-JWT (for binding between layers)."""
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
