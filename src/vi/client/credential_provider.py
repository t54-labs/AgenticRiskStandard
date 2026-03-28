"""VI Credential Provider client — issues L1 credentials, verifies chains."""

from __future__ import annotations

from ._dual_key import VIDualKeyClient
from ._models import ChainVerificationResponse, CredentialTrackResponse


class VICredentialProviderClient(VIDualKeyClient):
    """VI Credential Provider client. Issues L1 and verifies credential chains."""

    def issue_l1(
        self,
        job_id: str,
        agreement_hash: str,
        l1_serialized: str,
        user_jwk: dict | None = None,
    ) -> CredentialTrackResponse:
        """POST /jobs/{id}/credentials/l1 — issue L1 issuer credential."""
        payload = {
            "l1_serialized": l1_serialized,
        }
        if user_jwk:
            payload["user_jwk"] = user_jwk
        data = self._post_envelope(
            f"/jobs/{job_id}/credentials/l1",
            "L1_CREDENTIAL_ISSUED",
            job_id,
            agreement_hash,
            payload=payload,
        )
        return CredentialTrackResponse(**data)

    def verify_l2(self, job_id: str, agreement_hash: str) -> CredentialTrackResponse:
        """POST /jobs/{id}/credentials/l2/verify — verify L1→L2 chain."""
        data = self._post_envelope(
            f"/jobs/{job_id}/credentials/l2/verify",
            "L2_MANDATE_VERIFIED",
            job_id,
            agreement_hash,
        )
        return CredentialTrackResponse(**data)

    def verify_chain(
        self, job_id: str, agreement_hash: str
    ) -> ChainVerificationResponse:
        """POST /jobs/{id}/credentials/l3/verify — verify full chain."""
        data = self._post_envelope(
            f"/jobs/{job_id}/credentials/l3/verify",
            "L3_CHAIN_VERIFIED",
            job_id,
            agreement_hash,
        )
        return ChainVerificationResponse(**data)
