"""VI Payment Network client — verifies chains, manages VI settlement."""

from __future__ import annotations

from ._dual_key import VIDualKeyClient
from ._models import (
    ChainVerificationResponse,
    CredentialTrackResponse,
    SelectivePresentationResponse,
)


class VIPaymentNetworkClient(VIDualKeyClient):
    """VI Payment Network client. Verifies chains, initiates/confirms settlement."""

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

    def initiate_settlement(
        self, job_id: str, agreement_hash: str, settlement_ref: str = "",
    ) -> CredentialTrackResponse:
        """POST /jobs/{id}/credentials/settlement/initiate — initiate VI settlement."""
        data = self._post_envelope(
            f"/jobs/{job_id}/credentials/settlement/initiate",
            "SETTLEMENT_VI_INITIATED",
            job_id,
            agreement_hash,
            payload={"settlement_ref": settlement_ref},
        )
        return CredentialTrackResponse(**data)

    def confirm_settlement(
        self, job_id: str, agreement_hash: str,
    ) -> CredentialTrackResponse:
        """POST /jobs/{id}/credentials/settlement/confirm — confirm VI settlement."""
        data = self._post_envelope(
            f"/jobs/{job_id}/credentials/settlement/confirm",
            "SETTLEMENT_VI_CONFIRMED",
            job_id,
            agreement_hash,
        )
        return CredentialTrackResponse(**data)

    def get_network_presentation(self, job_id: str) -> SelectivePresentationResponse:
        """GET /jobs/{id}/credentials/present/network — payment disclosures only."""
        data = self._transport.get(f"/jobs/{job_id}/credentials/present/network")
        return SelectivePresentationResponse(**data)
