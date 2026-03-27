"""Underwriter client — assesses risk, sets premium/collateral terms."""

from __future__ import annotations

from ._base import BaseClient
from ._models import UWResponse


class UnderwriterClient(BaseClient):
    """Client for the Underwriter role."""

    def uw_decide(
        self,
        job_id: str,
        agreement_hash: str,
        approve: bool,
        premium: int = 0,
        collateral_required: int = 0,
    ) -> UWResponse:
        """POST /jobs/{id}/uw/decide — submit underwriting decision."""
        data = self._post_envelope(
            f"/jobs/{job_id}/uw/decide",
            "UW_DECIDED",
            job_id,
            agreement_hash,
            payload={
                "approve": approve,
                "premium": premium,
                "collateral_required": collateral_required,
            },
        )
        return UWResponse(**data)
