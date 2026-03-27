"""Business Agent client — signs agreements, delivers, manages collateral."""

from __future__ import annotations

from ._base import BaseClient
from ._models import (
    CollateralResponse,
    DeliverableResponse,
    SignatureResponse,
    UWResponse,
)


class BusinessAgentClient(BaseClient):
    """Client for the Business Agent role (maps to Merchant in AP2)."""

    def sign_agreement(self, job_id: str, agreement_hash: str) -> SignatureResponse:
        """POST /jobs/{id}/signatures — sign the agreement."""
        data = self._post_envelope(
            f"/jobs/{job_id}/signatures", "AGREEMENT_SIGNED", job_id, agreement_hash,
        )
        return SignatureResponse(**data)

    def propose_agreement(
        self, job_id: str, agreement_hash: str, agreement: dict,
    ) -> dict:
        """POST /jobs/{id}/proposals — propose/counter-propose an agreement."""
        data = self._post_envelope(
            f"/jobs/{job_id}/proposals",
            "PROPOSAL_SUBMITTED",
            job_id,
            agreement_hash,
            payload={"agreement": agreement},
        )
        return data

    def submit_deliverable(
        self, job_id: str, agreement_hash: str, deliverable_ref: str,
    ) -> DeliverableResponse:
        """POST /jobs/{id}/deliverable — submit the deliverable."""
        data = self._post_envelope(
            f"/jobs/{job_id}/deliverable",
            "DELIVERABLE_SUBMITTED",
            job_id,
            agreement_hash,
            payload={"deliverable_ref": deliverable_ref},
        )
        return DeliverableResponse(**data)

    def request_uw(self, job_id: str, agreement_hash: str) -> UWResponse:
        """POST /jobs/{id}/uw/request — request underwriting."""
        data = self._post_envelope(
            f"/jobs/{job_id}/uw/request", "UW_REQUESTED", job_id, agreement_hash,
        )
        return UWResponse(**data)

    def lock_collateral(self, job_id: str, agreement_hash: str) -> CollateralResponse:
        """POST /jobs/{id}/uw/collateral/lock — lock collateral."""
        data = self._post_envelope(
            f"/jobs/{job_id}/uw/collateral/lock",
            "COLLATERAL_LOCKED",
            job_id,
            agreement_hash,
        )
        return CollateralResponse(**data)

    def submit_execution_evidence(
        self, job_id: str, agreement_hash: str, exec_evidence_ref: str,
    ) -> UWResponse:
        """POST /jobs/{id}/execution-evidence — submit execution evidence."""
        data = self._post_envelope(
            f"/jobs/{job_id}/execution-evidence",
            "EXECUTION_EVIDENCE_SUBMITTED",
            job_id,
            agreement_hash,
            payload={"exec_evidence_ref": exec_evidence_ref},
        )
        return UWResponse(**data)
