"""AP2 Shopping Agent client — read-only orchestrator, user's proxy."""

from __future__ import annotations

from ars_client._base import BaseClient


class ShoppingAgentClient(BaseClient):
    """AP2 Shopping Agent client. Reads state and orchestrates on behalf of user.

    The shopping agent is the user's proxy — it never receives payment
    and never accesses payment credentials (enforced by the agent-payment firewall).
    """

    def get_mandates(self, job_id: str) -> dict:
        """GET /jobs/{id}/mandates — get mandate track state."""
        return self._transport.get(f"/jobs/{job_id}/mandates")

    def check_constraints(self, job_id: str) -> dict:
        """GET /jobs/{id}/constraints/check — check intent constraints against cart."""
        return self._transport.get(f"/jobs/{job_id}/constraints/check")

    def propose_agreement(
        self, job_id: str, agreement_hash: str, agreement: dict,
    ) -> dict:
        """POST /jobs/{id}/proposals — propose agreement on behalf of user."""
        data = self._post_envelope(
            f"/jobs/{job_id}/proposals",
            "PROPOSAL_SUBMITTED",
            job_id,
            agreement_hash,
            payload={"agreement": agreement},
        )
        return data
