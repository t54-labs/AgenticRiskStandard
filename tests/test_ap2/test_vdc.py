"""Tests for VDC creation, signing, verification, and expiry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from nacl.signing import SigningKey

from ap2.server.models import CartLineItem
from ap2.server.vdc import (
    compute_mandate_hash,
    create_cart_mandate,
    create_intent_mandate,
    create_payment_mandate,
    is_expired,
    verify_mandate,
)


def test_intent_mandate_sign_and_verify():
    sk = SigningKey.generate()
    pk = sk.verify_key.encode().hex()
    mandate = create_intent_mandate(
        sk,
        "job-1",
        budget=5000,
        allowed_merchants=["m1", "m2"],
        description="buy coffee",
        ttl_seconds=3600,
    )
    assert mandate.header.iss == pk
    assert mandate.header.vdc_type == "intent"
    assert mandate.budget == 5000
    assert verify_mandate(mandate, pk)


def test_intent_mandate_wrong_key_fails():
    sk = SigningKey.generate()
    other_sk = SigningKey.generate()
    other_pk = other_sk.verify_key.encode().hex()
    mandate = create_intent_mandate(
        sk, "job-1", budget=5000, allowed_merchants=[], description="test",
    )
    assert not verify_mandate(mandate, other_pk)


def test_cart_mandate_computes_total():
    sk = SigningKey.generate()
    items = [
        CartLineItem(sku="A", description="Widget", quantity=2, unit_price=500),
        CartLineItem(sku="B", description="Gadget", quantity=1, unit_price=1000),
    ]
    mandate = create_cart_mandate(sk, "job-1", items)
    assert mandate.total == 2000  # 2*500 + 1*1000
    assert verify_mandate(mandate, sk.verify_key.encode().hex())


def test_payment_mandate_references_cart():
    merchant_sk = SigningKey.generate()
    user_sk = SigningKey.generate()

    items = [CartLineItem(sku="A", description="W", quantity=1, unit_price=100)]
    cart = create_cart_mandate(merchant_sk, "job-1", items)
    cart_hash = compute_mandate_hash(cart)

    payment = create_payment_mandate(user_sk, "job-1", cart, "token_hash_xyz")
    assert payment.cart_mandate_hash == cart_hash
    assert payment.amount == 100
    assert verify_mandate(payment, user_sk.verify_key.encode().hex())


def test_mandate_hash_deterministic():
    sk = SigningKey.generate()
    mandate = create_intent_mandate(
        sk, "job-1", budget=1000, allowed_merchants=["m1"], description="test",
    )
    h1 = compute_mandate_hash(mandate)
    h2 = compute_mandate_hash(mandate)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_is_expired():
    sk = SigningKey.generate()
    mandate = create_intent_mandate(
        sk,
        "job-1",
        budget=1000,
        allowed_merchants=[],
        description="test",
        ttl_seconds=0,  # expires immediately
    )
    assert is_expired(mandate)


def test_not_expired():
    sk = SigningKey.generate()
    mandate = create_intent_mandate(
        sk,
        "job-1",
        budget=1000,
        allowed_merchants=[],
        description="test",
        ttl_seconds=3600,
    )
    assert not is_expired(mandate)
