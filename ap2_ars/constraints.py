"""IntentMandate constraint engine for human-NOT-present mode."""

from __future__ import annotations

import fnmatch
from datetime import datetime, timezone

from pydantic import BaseModel

from .models import CartMandate, IntentMandate


class ConstraintViolation(BaseModel):
    field: str
    message: str


class ConstraintResult(BaseModel):
    allowed: bool
    violations: list[ConstraintViolation]


class ConstraintEngine:
    """Validates a CartMandate against IntentMandate boundaries.

    Pure logic, no I/O. Used by the server to gate human-NOT-present flows.
    """

    def check(self, intent: IntentMandate, cart: CartMandate) -> ConstraintResult:
        violations: list[ConstraintViolation] = []

        # Budget: cart total must not exceed intent budget
        if cart.total > intent.budget:
            violations.append(
                ConstraintViolation(
                    field="budget",
                    message=f"Cart total {cart.total} exceeds budget {intent.budget}",
                )
            )

        # Merchant whitelist: cart merchant must be in allowed list
        if cart.merchant_id not in intent.allowed_merchants:
            violations.append(
                ConstraintViolation(
                    field="merchant",
                    message=f"Merchant {cart.merchant_id} not in allowed list",
                )
            )

        # SKU patterns: every cart item must match at least one pattern
        if intent.sku_patterns:
            for item in cart.line_items:
                if not any(
                    fnmatch.fnmatch(item.sku, pat) for pat in intent.sku_patterns
                ):
                    violations.append(
                        ConstraintViolation(
                            field="sku",
                            message=f"SKU '{item.sku}' does not match any allowed pattern",
                        )
                    )

        # TTL: intent must not be expired
        exp_dt = datetime.fromisoformat(intent.header.exp)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp_dt:
            violations.append(
                ConstraintViolation(field="ttl", message="IntentMandate has expired",)
            )

        return ConstraintResult(allowed=len(violations) == 0, violations=violations,)
