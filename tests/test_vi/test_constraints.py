"""VI constraint engine tests."""

import pytest

from vi.server.constraints import VIConstraintEngine


@pytest.fixture()
def engine():
    return VIConstraintEngine()


def test_valid_fulfillment_passes(engine):
    constraints = {
        "payment_amount": {"min_amount": 0, "max_amount": 5000},
        "allowed_merchants": {"merchant_ids": ["merchant-abc"]},
    }
    l3a = {"amount": 3000, "payee": "vendor"}
    l3b = {"merchant_id": "merchant-abc"}
    result = engine.check(constraints, l3a, l3b)
    assert result.allowed
    assert result.violations == []


def test_payment_amount_exceeded(engine):
    constraints = {"payment_amount": {"max_amount": 5000}}
    l3a = {"amount": 6000}
    result = engine.check(constraints, l3a)
    assert not result.allowed
    assert any(v.field == "payment_amount" for v in result.violations)


def test_payment_amount_below_minimum(engine):
    constraints = {"payment_amount": {"min_amount": 1000}}
    l3a = {"amount": 500}
    result = engine.check(constraints, l3a)
    assert not result.allowed
    assert any("below minimum" in v.message for v in result.violations)


def test_merchant_not_in_allowlist(engine):
    constraints = {"allowed_merchants": {"merchant_ids": ["merchant-abc"]}}
    l3b = {"merchant_id": "merchant-xyz"}
    result = engine.check(constraints, l3b_checkout=l3b)
    assert not result.allowed
    assert any(v.field == "merchant" for v in result.violations)


def test_payee_not_in_allowlist(engine):
    constraints = {"allowed_payees": {"payee_ids": ["vendor-a", "vendor-b"]}}
    l3a = {"payee": "vendor-z"}
    result = engine.check(constraints, l3a)
    assert not result.allowed
    assert any(v.field == "payee" for v in result.violations)


def test_line_item_product_not_allowed(engine):
    constraints = {
        "line_items": {"items": [{"product_id": "PROD-001", "max_quantity": 10}]}
    }
    l3b = {"line_items": [{"product_id": "PROD-999", "quantity": 1}]}
    result = engine.check(constraints, l3b_checkout=l3b)
    assert not result.allowed
    assert any("not in allowed" in v.message for v in result.violations)


def test_line_item_quantity_exceeded(engine):
    constraints = {
        "line_items": {"items": [{"product_id": "PROD-001", "max_quantity": 5}]}
    }
    l3b = {"line_items": [{"product_id": "PROD-001", "quantity": 10}]}
    result = engine.check(constraints, l3b_checkout=l3b)
    assert not result.allowed
    assert any("exceeds max" in v.message for v in result.violations)


def test_budget_cap_exceeded(engine):
    constraints = {"payment_budget": {"max_budget": 10000}}
    l3a = {"amount": 15000}
    result = engine.check(constraints, l3a)
    assert not result.allowed
    assert any(v.field == "payment_budget" for v in result.violations)


def test_multiple_violations(engine):
    constraints = {
        "payment_amount": {"max_amount": 1000},
        "allowed_merchants": {"merchant_ids": ["merchant-abc"]},
    }
    l3a = {"amount": 5000}
    l3b = {"merchant_id": "merchant-xyz"}
    result = engine.check(constraints, l3a, l3b)
    assert not result.allowed
    assert len(result.violations) >= 2
