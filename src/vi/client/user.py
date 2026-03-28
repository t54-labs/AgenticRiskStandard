"""VI User client — extends RequestorClient with L2 credential methods."""

from __future__ import annotations

from ars_client.requestor import RequestorClient

from ._models import CredentialTrackResponse


class VIUserClient(RequestorClient):
    """VI User client. Creates L2 mandates (immediate or autonomous)."""

    def create_l2_mandate(
        self,
        job_id: str,
        agreement_hash: str,
        mode: str,
        l2_serialized: str,
        constraints: dict | None = None,
    ) -> CredentialTrackResponse:
        """POST /jobs/{id}/credentials/l2 — create an L2 mandate."""
        payload = {
            "mode": mode,
            "l2_serialized": l2_serialized,
        }
        if constraints:
            payload["constraints"] = constraints
        data = self._post_envelope(
            f"/jobs/{job_id}/credentials/l2",
            "L2_MANDATE_CREATED",
            job_id,
            agreement_hash,
            payload=payload,
        )
        return CredentialTrackResponse(**data)
