"""VI escrow tests (MockEscrowClient from ars.escrow — shared with AP2)."""

import pytest

from ars.escrow import DepositStatus, DepositType, MockEscrowClient


@pytest.fixture()
def escrow():
    return MockEscrowClient()


async def test_record_and_release(escrow):
    tx = await escrow.record_deposit("job-1", DepositType.FEE, "user", "merchant", 5000)
    assert tx

    info = await escrow.get_deposit("job-1", DepositType.FEE)
    assert info.status == DepositStatus.LOCKED
    assert info.amount == 5000

    release_tx = await escrow.release("job-1", DepositType.FEE)
    assert release_tx

    info = await escrow.get_deposit("job-1", DepositType.FEE)
    assert info.status == DepositStatus.RELEASED


async def test_record_and_refund(escrow):
    await escrow.record_deposit("job-1", DepositType.FEE, "user", "merchant", 3000)
    tx = await escrow.refund("job-1", DepositType.FEE)
    assert tx

    info = await escrow.get_deposit("job-1", DepositType.FEE)
    assert info.status == DepositStatus.REFUNDED


async def test_slash_collateral(escrow):
    await escrow.record_deposit("job-1", DepositType.COLLATERAL, "merchant", "", 10000)
    tx = await escrow.slash("job-1", "treasury")
    assert tx

    info = await escrow.get_deposit("job-1", DepositType.COLLATERAL)
    assert info.status == DepositStatus.SLASHED


async def test_double_deposit_raises(escrow):
    await escrow.record_deposit("job-1", DepositType.FEE, "user", "merchant", 5000)
    with pytest.raises(Exception):
        await escrow.record_deposit("job-1", DepositType.FEE, "user", "merchant", 5000)


async def test_release_non_locked_raises(escrow):
    with pytest.raises(Exception):
        await escrow.release("job-999", DepositType.FEE)


async def test_get_nonexistent_returns_none(escrow):
    info = await escrow.get_deposit("job-999", DepositType.FEE)
    assert info is None
