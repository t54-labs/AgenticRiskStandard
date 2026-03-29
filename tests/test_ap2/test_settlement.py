"""Tests for MockSettlementLayer."""

from __future__ import annotations

import pytest

from abstract_ars.settlement import MockSettlementLayer


@pytest.mark.asyncio
async def test_fee_lock_and_release():
    sl = MockSettlementLayer()
    lock = await sl.lock_fee("job-1", 1000, "USD", "payer", "payee")
    assert lock.ref == "lock:job-1"

    release = await sl.release_fee("job-1")
    assert "release" in release.ref


@pytest.mark.asyncio
async def test_fee_lock_and_refund():
    sl = MockSettlementLayer()
    await sl.lock_fee("job-1", 1000, "USD", "payer", "payee")
    refund = await sl.refund_fee("job-1")
    assert "refund" in refund.ref


@pytest.mark.asyncio
async def test_collateral_lock_and_slash():
    sl = MockSettlementLayer()
    lock = await sl.lock_collateral("job-1", 5000, "USD", "payer")
    assert lock.ref == "collateral:job-1"

    slash = await sl.slash_collateral("job-1", "user-addr")
    assert "slashed" in slash.ref


@pytest.mark.asyncio
async def test_collateral_lock_and_unlock():
    sl = MockSettlementLayer()
    await sl.lock_collateral("job-1", 5000, "USD", "payer")
    unlock = await sl.unlock_collateral("job-1")
    assert "collateral_unlocked" in unlock.ref


@pytest.mark.asyncio
async def test_pay_premium():
    sl = MockSettlementLayer()
    result = await sl.pay_premium("job-1", 200, "USD", "user", "underwriter")
    assert "premium:job-1" in result.ref
