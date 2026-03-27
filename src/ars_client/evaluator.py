"""Evaluator client — issues pass/fail verdicts on deliverables."""

from __future__ import annotations

from ._base import BaseClient
from ._models import EvaluateResponse


class EvaluatorClient(BaseClient):
    """Client for the Evaluator role."""

    def evaluate(
        self, job_id: str, agreement_hash: str, verdict: str,
    ) -> EvaluateResponse:
        """POST /jobs/{id}/evaluate — evaluate outcome (pass or fail)."""
        data = self._post_envelope(
            f"/jobs/{job_id}/evaluate",
            "OUTCOME_EVALUATED",
            job_id,
            agreement_hash,
            payload={"verdict": verdict},
        )
        return EvaluateResponse(**data)
