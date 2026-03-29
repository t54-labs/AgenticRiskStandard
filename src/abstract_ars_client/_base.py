"""Base client class with shared transport, signing, and GET endpoints."""

from __future__ import annotations

from nacl.signing import SigningKey

from ._signing import build_create_request, build_envelope, load_signing_key, pubkey_hex
from ._transport import Transport


class BaseClient:
    """Base ARS protocol client. All role-specific clients inherit from this."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        signing_key: SigningKey | None = None,
        key_hex: str | None = None,
        key_file: str | None = None,
        timeout: float = 30.0,
        transport: Transport | None = None,
    ) -> None:
        self._sk = load_signing_key(key=signing_key, key_hex=key_hex, key_file=key_file)
        self._transport = transport or Transport(base_url=base_url, timeout=timeout)

    @property
    def pubkey(self) -> str:
        """Hex-encoded Ed25519 public key."""
        return pubkey_hex(self._sk)

    def get_job(self, job_id: str) -> dict:
        """GET /jobs/{job_id} — current job state."""
        return self._transport.get(f"/jobs/{job_id}")

    def get_events(self, job_id: str) -> dict:
        """GET /jobs/{job_id}/events — full event history."""
        return self._transport.get(f"/jobs/{job_id}/events")

    def _post_envelope(
        self,
        path: str,
        event_type: str,
        job_id: str,
        agreement_hash: str,
        payload: dict | None = None,
    ) -> dict:
        """Build, sign, and POST an envelope."""
        envelope = build_envelope(
            self._sk, event_type, job_id, agreement_hash, payload or {},
        )
        return self._transport.post(path, json=envelope)

    def _post_create(self, agreement_dict: dict) -> dict:
        """Build, sign, and POST a create-job request."""
        req = build_create_request(self._sk, agreement_dict)
        return self._transport.post("/jobs", json=req)
