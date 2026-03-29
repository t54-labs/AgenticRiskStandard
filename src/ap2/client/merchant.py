"""AP2 Merchant client — extends BusinessAgentClient with cart methods."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from abstract_ars_client._models import MandateTrackResponse
from abstract_ars_client.business_agent import BusinessAgentClient


class MerchantClient(BusinessAgentClient):
    """AP2 Merchant client. Proposes/signs carts, delivers goods."""

    def propose_cart(
        self,
        job_id: str,
        agreement_hash: str,
        line_items: list[dict],
        total: int,
        ttl_seconds: int = 900,
    ) -> MandateTrackResponse:
        """POST /jobs/{id}/mandates/cart — propose a CartMandate."""
        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=ttl_seconds)
        payload = {
            "header": {
                "iss": self.pubkey,
                "sub": job_id,
                "iat": now.isoformat(),
                "exp": exp.isoformat(),
                "vdc_type": "cart",
            },
            "cart_hash": "computed_by_server",
            "line_items": line_items,
            "total": total,
            "merchant_id": self.pubkey,
            "signature": "placeholder",
        }
        data = self._post_envelope(
            f"/jobs/{job_id}/mandates/cart",
            "CART_MANDATE_PROPOSED",
            job_id,
            agreement_hash,
            payload=payload,
        )
        return MandateTrackResponse(**data)

    def sign_cart(self, job_id: str, agreement_hash: str) -> MandateTrackResponse:
        """POST /jobs/{id}/mandates/cart/sign — sign the cart mandate."""
        data = self._post_envelope(
            f"/jobs/{job_id}/mandates/cart/sign",
            "CART_MANDATE_SIGNED",
            job_id,
            agreement_hash,
        )
        return MandateTrackResponse(**data)
