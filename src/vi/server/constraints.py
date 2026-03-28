"""VI constraint engine for autonomous mode.

Validates L3 fulfillment values against L2 autonomous constraints.
Analogous to ap2/server/constraints.py but with richer constraint types.
"""

from __future__ import annotations

from pydantic import BaseModel


class ConstraintViolation(BaseModel):
    field: str
    message: str


class ConstraintResult(BaseModel):
    allowed: bool
    violations: list[ConstraintViolation]


class VIConstraintEngine:
    """Validates L3 fulfillment against L2 autonomous constraints.

    Pure logic, no I/O. Used by the server to gate autonomous-mode flows.

    Constraints are extracted from L2 mandate payload. Each constraint type
    maps to a validation rule applied against L3a (payment) / L3b (checkout).
    """

    def check(
        self,
        l2_constraints: dict,
        l3a_payment: dict | None = None,
        l3b_checkout: dict | None = None,
    ) -> ConstraintResult:
        violations: list[ConstraintViolation] = []

        # Payment amount constraint (min/max bounds in minor units)
        amount_constraint = l2_constraints.get("payment_amount")
        if amount_constraint and l3a_payment:
            amount = l3a_payment.get("amount", 0)
            min_amount = amount_constraint.get("min_amount")
            max_amount = amount_constraint.get("max_amount")
            if min_amount is not None and amount < min_amount:
                violations.append(
                    ConstraintViolation(
                        field="payment_amount",
                        message=f"Amount {amount} below minimum {min_amount}",
                    )
                )
            if max_amount is not None and amount > max_amount:
                violations.append(
                    ConstraintViolation(
                        field="payment_amount",
                        message=f"Amount {amount} exceeds maximum {max_amount}",
                    )
                )

        # Allowed merchant constraint
        merchant_constraint = l2_constraints.get("allowed_merchants")
        if merchant_constraint and l3b_checkout:
            merchant_id = l3b_checkout.get("merchant_id", "")
            allowed = merchant_constraint.get("merchant_ids", [])
            if allowed and merchant_id not in allowed:
                violations.append(
                    ConstraintViolation(
                        field="merchant",
                        message=f"Merchant {merchant_id} not in allowed list",
                    )
                )

        # Allowed payee constraint
        payee_constraint = l2_constraints.get("allowed_payees")
        if payee_constraint and l3a_payment:
            payee = l3a_payment.get("payee", "")
            allowed_payees = payee_constraint.get("payee_ids", [])
            if allowed_payees and payee not in allowed_payees:
                violations.append(
                    ConstraintViolation(
                        field="payee", message=f"Payee {payee} not in allowed list",
                    )
                )

        # Line items constraint (product ID + quantity bounds)
        line_items_constraint = l2_constraints.get("line_items")
        if line_items_constraint and l3b_checkout:
            allowed_products = {
                item["product_id"]: item
                for item in line_items_constraint.get("items", [])
            }
            checkout_items = l3b_checkout.get("line_items", [])
            for item in checkout_items:
                pid = item.get("product_id", "")
                if pid not in allowed_products:
                    violations.append(
                        ConstraintViolation(
                            field="line_items",
                            message=f"Product {pid} not in allowed products",
                        )
                    )
                else:
                    spec = allowed_products[pid]
                    qty = item.get("quantity", 0)
                    max_qty = spec.get("max_quantity")
                    if max_qty is not None and qty > max_qty:
                        violations.append(
                            ConstraintViolation(
                                field="line_items",
                                message=f"Product {pid} quantity {qty} exceeds max {max_qty}",
                            )
                        )

        # Payment budget constraint (cumulative spend cap)
        budget_constraint = l2_constraints.get("payment_budget")
        if budget_constraint and l3a_payment:
            amount = l3a_payment.get("amount", 0)
            budget = budget_constraint.get("max_budget")
            if budget is not None and amount > budget:
                violations.append(
                    ConstraintViolation(
                        field="payment_budget",
                        message=f"Amount {amount} exceeds budget cap {budget}",
                    )
                )

        return ConstraintResult(allowed=len(violations) == 0, violations=violations)
