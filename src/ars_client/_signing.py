"""Envelope building and signing helpers wrapping ars.crypto."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from nacl.signing import SigningKey

from ars.crypto import sign_envelope


def pubkey_hex(signing_key: SigningKey) -> str:
    """Extract hex-encoded public key from a signing key."""
    return signing_key.verify_key.encode().hex()


def load_signing_key(
    key: SigningKey | None = None,
    key_hex: str | None = None,
    key_file: str | None = None,
    env_var: str = "ARS_SIGNING_KEY",
) -> SigningKey:
    """Resolve a signing key from various sources.

    Priority: key > key_hex > key_file > env_var.
    """
    if key is not None:
        return key
    if key_hex is not None:
        return SigningKey(bytes.fromhex(key_hex))
    if key_file is not None:
        raw = open(key_file, "rb").read()
        if len(raw) == 64:
            raw = bytes.fromhex(raw.decode())
        return SigningKey(raw)
    env_val = os.environ.get(env_var)
    if env_val:
        return SigningKey(bytes.fromhex(env_val))
    raise ValueError(
        "No signing key provided. Pass key, key_hex, key_file, "
        f"or set {env_var} environment variable."
    )


def build_envelope(
    signing_key: SigningKey,
    event_type: str,
    job_id: str,
    agreement_hash: str,
    payload: dict,
) -> dict:
    """Build and sign a SignedActionEnvelope dict."""
    body = {
        "type": event_type,
        "job_id": job_id,
        "agreement_hash": agreement_hash,
        "payload": payload,
        "actor": pubkey_hex(signing_key),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    body["signature"] = sign_envelope(signing_key, body)
    return body


def build_create_request(signing_key: SigningKey, agreement_dict: dict,) -> dict:
    """Build and sign a CreateJobRequest dict."""
    body = {
        "type": "JOB_CREATED",
        "payload": {"agreement": agreement_dict},
        "actor": pubkey_hex(signing_key),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    body["signature"] = sign_envelope(signing_key, body)
    return body
