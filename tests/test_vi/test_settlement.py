"""VI settlement layer tests (MockSettlementLayer from abstract_ars.settlement)."""

import pytest

from abstract_ars.settlement import MockSettlementLayer


@pytest.fixture()
def settlement():
    return MockSettlementLayer()


async def test_fee_lock_and_release(settlement):
    result = await settlement.lock_fee("job-1", 5000, "USD", "user", "merchant")
    assert "lock:job-1" in result.ref

    settle = await settlement.release_fee("job-1")
    assert "release" in settle.ref


async def test_fee_lock_and_refund(settlement):
    await settlement.lock_fee("job-1", 5000, "USD", "user", "merchant")
    settle = await settlement.refund_fee("job-1")
    assert "refund" in settle.ref


async def test_collateral_lock_and_unlock(settlement):
    result = await settlement.lock_collateral("job-1", 10000, "USD", "merchant")
    assert "collateral:job-1" in result.ref

    unlock = await settlement.unlock_collateral("job-1")
    assert "unlocked" in unlock.ref


async def test_collateral_lock_and_slash(settlement):
    await settlement.lock_collateral("job-1", 10000, "USD", "merchant")
    slash = await settlement.slash_collateral("job-1", "user-addr")
    assert "slashed" in slash.ref


async def test_pay_premium(settlement):
    result = await settlement.pay_premium("job-1", 200, "USD", "user", "underwriter")
    assert "premium:job-1" in result.ref
