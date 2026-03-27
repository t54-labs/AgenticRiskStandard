"""Tests for MockEscrowClient."""

from __future__ import annotations

import pytest

from ap2.server.escrow import DepositStatus, DepositType, MockEscrowClient


@pytest.mark.asyncio
async def test_record_and_release():
    client = MockEscrowClient()
    tx = await client.record_deposit("job-1", DepositType.FEE, "payer", "payee", 1000)
    assert "escrow_tx" in tx

    info = await client.get_deposit("job-1", DepositType.FEE)
    assert info is not None
    assert info.status == DepositStatus.LOCKED
    assert info.amount == 1000

    release_tx = await client.release("job-1", DepositType.FEE)
    assert "release_tx" in release_tx

    info = await client.get_deposit("job-1", DepositType.FEE)
    assert info.status == DepositStatus.RELEASED


@pytest.mark.asyncio
async def test_record_and_refund():
    client = MockEscrowClient()
    await client.record_deposit("job-1", DepositType.FEE, "payer", "payee", 500)
    await client.refund("job-1", DepositType.FEE)

    info = await client.get_deposit("job-1", DepositType.FEE)
    assert info.status == DepositStatus.REFUNDED


@pytest.mark.asyncio
async def test_slash_collateral():
    client = MockEscrowClient()
    await client.record_deposit("job-1", DepositType.COLLATERAL, "payer", "", 2000)
    await client.slash("job-1", "0xTreasury")

    info = await client.get_deposit("job-1", DepositType.COLLATERAL)
    assert info.status == DepositStatus.SLASHED


@pytest.mark.asyncio
async def test_double_deposit_raises():
    client = MockEscrowClient()
    await client.record_deposit("job-1", DepositType.FEE, "p", "q", 100)
    with pytest.raises(ValueError, match="Already deposited"):
        await client.record_deposit("job-1", DepositType.FEE, "p", "q", 100)


@pytest.mark.asyncio
async def test_release_non_locked_raises():
    client = MockEscrowClient()
    await client.record_deposit("job-1", DepositType.FEE, "p", "q", 100)
    await client.release("job-1", DepositType.FEE)
    with pytest.raises(ValueError, match="Cannot release"):
        await client.release("job-1", DepositType.FEE)


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none():
    client = MockEscrowClient()
    assert await client.get_deposit("nope", DepositType.FEE) is None
