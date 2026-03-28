"""Requestor client — creates jobs, locks fees, manages UW overrides."""

from __future__ import annotations

from ._base import BaseClient
from ._models import (
    CreateJobResponse,
    LockFeeResponse,
    SettleFeeResponse,
    SignatureResponse,
    UWResponse,
)


class RequestorClient(BaseClient):
    """Client for the Requestor role (maps to User in AP2)."""

    def create_job(self, agreement: dict) -> CreateJobResponse:
        """POST /jobs — create a new job with an agreement draft."""
        data = self._post_create(agreement)
        return CreateJobResponse(**data)

    def sign_agreement(self, job_id: str, agreement_hash: str) -> SignatureResponse:
        """POST /jobs/{id}/signatures — sign the agreement."""
        data = self._post_envelope(
            f"/jobs/{job_id}/signatures", "AGREEMENT_SIGNED", job_id, agreement_hash,
        )
        return SignatureResponse(**data)

    def lock_fee(self, job_id: str, agreement_hash: str) -> LockFeeResponse:
        """POST /jobs/{id}/fee/lock — lock fee in escrow."""
        data = self._post_envelope(
            f"/jobs/{job_id}/fee/lock", "FEE_ESCROW_LOCKED", job_id, agreement_hash,
        )
        return LockFeeResponse(**data)

    def settle_fee(
        self, job_id: str, agreement_hash: str, action: str,
    ) -> SettleFeeResponse:
        """POST /jobs/{id}/fee/settle — release or refund fee."""
        data = self._post_envelope(
            f"/jobs/{job_id}/fee/settle",
            "FEE_SETTLED",
            job_id,
            agreement_hash,
            payload={"action": action},
        )
        return SettleFeeResponse(**data)

    def pay_premium(
        self, job_id: str, agreement_hash: str, premium_ref: str,
    ) -> UWResponse:
        """POST /jobs/{id}/uw/premium — pay UW premium."""
        data = self._post_envelope(
            f"/jobs/{job_id}/uw/premium",
            "PREMIUM_PAID",
            job_id,
            agreement_hash,
            payload={"premium_ref": premium_ref},
        )
        return UWResponse(**data)

    def refuse_premium(self, job_id: str, agreement_hash: str) -> UWResponse:
        """POST /jobs/{id}/uw/premium/refuse — refuse to pay premium."""
        data = self._post_envelope(
            f"/jobs/{job_id}/uw/premium/refuse",
            "PREMIUM_REFUSED",
            job_id,
            agreement_hash,
        )
        return UWResponse(**data)

    def refuse_collateral(self, job_id: str, agreement_hash: str) -> UWResponse:
        """POST /jobs/{id}/uw/collateral/refuse — refuse collateral."""
        data = self._post_envelope(
            f"/jobs/{job_id}/uw/collateral/refuse",
            "COLLATERAL_REFUSED",
            job_id,
            agreement_hash,
        )
        return UWResponse(**data)

    def override(
        self, job_id: str, agreement_hash: str, decision: str = "proceed",
    ) -> UWResponse:
        """POST /jobs/{id}/uw/override — override UW decision."""
        data = self._post_envelope(
            f"/jobs/{job_id}/uw/override",
            "OVERRIDE_DECIDED",
            job_id,
            agreement_hash,
            payload={"decision": decision},
        )
        return UWResponse(**data)
