"""Tests for IntentMandate constraint engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ap2_ars.constraints import ConstraintEngine
from ap2_ars.models import CartLineItem, CartMandate, IntentMandate, VDCHeader


def _make_intent(budget=5000, merchants=None, sku_patterns=None, ttl_seconds=3600):
    now = datetime.now(timezone.utc)
    return IntentMandate(
        header=VDCHeader(
            iss="user_pk",
            sub="job-1",
            iat=now.isoformat(),
            exp=(now + timedelta(seconds=ttl_seconds)).isoformat(),
            vdc_type="intent",
        ),
        budget=budget,
        currency="USD",
        allowed_merchants=merchants or ["merchant_pk"],
        sku_patterns=sku_patterns or [],
        description="test",
        signature="sig",
    )


def _make_cart(total=2000, merchant_id="merchant_pk", items=None):
    now = datetime.now(timezone.utc)
    return CartMandate(
        header=VDCHeader(
            iss=merchant_id,
            sub="job-1",
            iat=now.isoformat(),
            exp=(now + timedelta(seconds=900)).isoformat(),
            vdc_type="cart",
        ),
        cart_hash="abc",
        line_items=items
        or [
            CartLineItem(
                sku="ITEM-001", description="Widget", quantity=1, unit_price=total
            ),
        ],
        total=total,
        merchant_id=merchant_id,
        signature="sig",
    )


def test_valid_cart_passes():
    engine = ConstraintEngine()
    intent = _make_intent(budget=5000, merchants=["merchant_pk"])
    cart = _make_cart(total=2000, merchant_id="merchant_pk")
    result = engine.check(intent, cart)
    assert result.allowed
    assert len(result.violations) == 0


def test_budget_exceeded():
    engine = ConstraintEngine()
    intent = _make_intent(budget=1000)
    cart = _make_cart(total=2000)
    result = engine.check(intent, cart)
    assert not result.allowed
    assert any(v.field == "budget" for v in result.violations)


def test_merchant_not_whitelisted():
    engine = ConstraintEngine()
    intent = _make_intent(merchants=["other_merchant"])
    cart = _make_cart(merchant_id="merchant_pk")
    result = engine.check(intent, cart)
    assert not result.allowed
    assert any(v.field == "merchant" for v in result.violations)


def test_sku_pattern_mismatch():
    engine = ConstraintEngine()
    intent = _make_intent(sku_patterns=["FOOD-*"])
    cart = _make_cart(
        items=[
            CartLineItem(
                sku="ELEC-001", description="Phone", quantity=1, unit_price=1000
            )
        ],
        total=1000,
    )
    result = engine.check(intent, cart)
    assert not result.allowed
    assert any(v.field == "sku" for v in result.violations)


def test_sku_pattern_match():
    engine = ConstraintEngine()
    intent = _make_intent(sku_patterns=["ITEM-*"])
    cart = _make_cart(
        items=[
            CartLineItem(
                sku="ITEM-001", description="Widget", quantity=1, unit_price=1000
            )
        ],
        total=1000,
    )
    result = engine.check(intent, cart)
    assert result.allowed


def test_expired_intent():
    engine = ConstraintEngine()
    intent = _make_intent(ttl_seconds=-10)  # already expired
    cart = _make_cart(total=1000)
    result = engine.check(intent, cart)
    assert not result.allowed
    assert any(v.field == "ttl" for v in result.violations)


def test_multiple_violations():
    engine = ConstraintEngine()
    intent = _make_intent(budget=500, merchants=["other"], sku_patterns=["FOOD-*"])
    cart = _make_cart(total=2000, merchant_id="merchant_pk")
    result = engine.check(intent, cart)
    assert not result.allowed
    assert len(result.violations) >= 2
