"""VI Agent client — creates L3a/L3b credentials, reads credential state."""

from __future__ import annotations

from ._dual_key import VIDualKeyClient
from ._models import CredentialTrackResponse


class VIAgentClient(VIDualKeyClient):
    """VI Agent client. Creates L3 fulfillment credentials in autonomous mode."""

    def create_l3a_payment(
        self,
        job_id: str,
        agreement_hash: str,
        l3a_serialized: str,
        transaction_id: str,
        payee: str,
        amount: int,
        currency: str = "USD",
    ) -> CredentialTrackResponse:
        """POST /jobs/{id}/credentials/l3a — create L3a payment fulfillment."""
        payload = {
            "l3a_serialized": l3a_serialized,
            "transaction_id": transaction_id,
            "payee": payee,
            "amount": amount,
            "currency": currency,
        }
        data = self._post_envelope(
            f"/jobs/{job_id}/credentials/l3a",
            "L3A_PAYMENT_CREATED",
            job_id,
            agreement_hash,
            payload=payload,
        )
        return CredentialTrackResponse(**data)

    def create_l3b_checkout(
        self,
        job_id: str,
        agreement_hash: str,
        l3b_serialized: str,
        checkout_jwt: str,
        merchant_id: str = "",
        line_items: list[dict] | None = None,
    ) -> CredentialTrackResponse:
        """POST /jobs/{id}/credentials/l3b — create L3b checkout fulfillment."""
        payload = {
            "l3b_serialized": l3b_serialized,
            "checkout_jwt": checkout_jwt,
            "merchant_id": merchant_id,
        }
        if line_items:
            payload["line_items"] = line_items
        data = self._post_envelope(
            f"/jobs/{job_id}/credentials/l3b",
            "L3B_CHECKOUT_CREATED",
            job_id,
            agreement_hash,
            payload=payload,
        )
        return CredentialTrackResponse(**data)

    def get_credentials(self, job_id: str) -> dict:
        """GET /jobs/{id}/credentials — get credential track state."""
        return self._transport.get(f"/jobs/{job_id}/credentials")

    def check_constraints(self, job_id: str) -> dict:
        """GET /jobs/{id}/constraints/check — check L2 constraints against L3."""
        return self._transport.get(f"/jobs/{job_id}/constraints/check")
