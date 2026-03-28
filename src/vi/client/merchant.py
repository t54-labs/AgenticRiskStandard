"""VI Merchant client — extends BusinessAgentClient with selective presentation."""

from __future__ import annotations

from ars_client.business_agent import BusinessAgentClient

from ._models import SelectivePresentationResponse


class VIMerchantClient(BusinessAgentClient):
    """VI Merchant client. Delivers goods, gets merchant-only credential view."""

    def get_merchant_presentation(self, job_id: str) -> SelectivePresentationResponse:
        """GET /jobs/{id}/credentials/present/merchant — checkout disclosures only."""
        data = self._transport.get(f"/jobs/{job_id}/credentials/present/merchant")
        return SelectivePresentationResponse(**data)
