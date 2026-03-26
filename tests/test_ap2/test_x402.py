"""Tests for x402 payment rail (mock + structural validation)."""

from __future__ import annotations

import pytest

from ap2_ars.x402 import MockX402Settlement, PaymentRequirement, USDC_ADDRESSES


@pytest.mark.asyncio
async def test_mock_happy_path():
    mock = MockX402Settlement()
    req = await mock.create_payment_requirement("job-1", 1000, "USD")
    assert req.job_id == "job-1"
    assert req.amount == "1000"

    verify = await mock.verify("job-1", {}, {})
    assert verify.valid
    assert verify.payer is not None

    settle = await mock.settle("job-1", {}, {})
    assert settle.success
    assert settle.transaction is not None
    assert "job-1" in settle.transaction


@pytest.mark.asyncio
async def test_mock_settle_before_verify_fails():
    mock = MockX402Settlement()
    result = await mock.settle("job-1", {}, {})
    assert not result.success


def test_payment_requirement_to_dict():
    req = PaymentRequirement(
        job_id="j1",
        network="eip155:84532",
        asset="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        amount="5000",
        pay_to="0xRecipient",
    )
    d = req.to_dict()
    assert d["x402Version"] == 2
    assert len(d["accepts"]) == 1
    assert d["accepts"][0]["scheme"] == "exact"
    assert d["accepts"][0]["amount"] == "5000"
    assert d["accepts"][0]["payTo"] == "0xRecipient"


def test_usdc_addresses():
    assert "eip155:8453" in USDC_ADDRESSES
    assert "eip155:84532" in USDC_ADDRESSES
    assert "eip155:1" in USDC_ADDRESSES
