"""AP2 User client — extends RequestorClient with mandate methods."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from abstract_ars_client._models import MandateTrackResponse
from abstract_ars_client.requestor import RequestorClient


class UserClient(RequestorClient):
    """AP2 User client. Creates mandates, approves carts, signs payments."""

    def create_intent_mandate(
        self,
        job_id: str,
        agreement_hash: str,
        budget: int,
        allowed_merchants: list[str],
        description: str = "",
        currency: str = "USD",
        sku_patterns: list[str] | None = None,
        ttl_seconds: int = 3600,
        requires_principal: bool = False,
    ) -> MandateTrackResponse:
        """POST /jobs/{id}/mandates/intent — create an IntentMandate."""
        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=ttl_seconds)
        payload = {
            "header": {
                "iss": self.pubkey,
                "sub": job_id,
                "iat": now.isoformat(),
                "exp": exp.isoformat(),
                "vdc_type": "intent",
            },
            "budget": budget,
            "currency": currency,
            "allowed_merchants": allowed_merchants,
            "sku_patterns": sku_patterns or [],
            "description": description,
            "requires_principal": requires_principal,
            "signature": "placeholder",
        }
        data = self._post_envelope(
            f"/jobs/{job_id}/mandates/intent",
            "INTENT_MANDATE_CREATED",
            job_id,
            agreement_hash,
            payload=payload,
        )
        return MandateTrackResponse(**data)

    def approve_cart(self, job_id: str, agreement_hash: str) -> MandateTrackResponse:
        """POST /jobs/{id}/mandates/cart/approve — approve cart (human-present)."""
        data = self._post_envelope(
            f"/jobs/{job_id}/mandates/cart/approve",
            "CART_APPROVED_BY_USER",
            job_id,
            agreement_hash,
        )
        return MandateTrackResponse(**data)

    def sign_payment(self, job_id: str, agreement_hash: str) -> MandateTrackResponse:
        """POST /jobs/{id}/mandates/payment/sign — sign payment mandate."""
        data = self._post_envelope(
            f"/jobs/{job_id}/mandates/payment/sign",
            "PAYMENT_MANDATE_SIGNED",
            job_id,
            agreement_hash,
        )
        return MandateTrackResponse(**data)
