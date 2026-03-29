"""Tests for FeeEscrow + CollateralVault."""

import pytest

from abstract_ars.vaults import DepositStatus, MockCollateralVault, MockFeeEscrow


@pytest.fixture()
def fee_escrow():
    return MockFeeEscrow()


@pytest.fixture()
def collateral_vault():
    return MockCollateralVault()


async def test_record_and_release(fee_escrow):
    tx = await fee_escrow.lock("job-1", "user", "merchant", 5000)
    assert tx

    info = await fee_escrow.get_status("job-1")
    assert info.status == DepositStatus.LOCKED
    assert info.amount == 5000

    release_tx = await fee_escrow.release("job-1")
    assert release_tx

    info = await fee_escrow.get_status("job-1")
    assert info.status == DepositStatus.RELEASED


async def test_record_and_refund(fee_escrow):
    await fee_escrow.lock("job-1", "user", "merchant", 3000)
    tx = await fee_escrow.refund("job-1")
    assert tx

    info = await fee_escrow.get_status("job-1")
    assert info.status == DepositStatus.REFUNDED


async def test_slash_collateral(collateral_vault):
    await collateral_vault.lock("job-1", "merchant", 10000)
    tx = await collateral_vault.slash("job-1", "treasury")
    assert tx

    info = await collateral_vault.get_status("job-1")
    assert info.status == DepositStatus.SLASHED


async def test_double_deposit_raises(fee_escrow):
    await fee_escrow.lock("job-1", "user", "merchant", 5000)
    with pytest.raises(ValueError):
        await fee_escrow.lock("job-1", "user", "merchant", 5000)


async def test_release_non_locked_raises(fee_escrow):
    with pytest.raises(ValueError):
        await fee_escrow.release("job-999")


async def test_get_nonexistent_returns_none(fee_escrow):
    info = await fee_escrow.get_status("job-999")
    assert info is None
