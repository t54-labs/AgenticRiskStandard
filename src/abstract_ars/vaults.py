"""Escrow and collateral vault abstractions: ABCs + mocks for development/testing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


class DepositStatus(IntEnum):
    LOCKED = 0
    RELEASED = 1
    REFUNDED = 2
    SLASHED = 3


@dataclass
class DepositInfo:
    job_id: str
    payer: str
    payee: str
    amount: int
    status: DepositStatus


# ── Fee Escrow ───────────────────────────────────────────────────────────────


class FeeEscrow(ABC):
    """Holds fee funds in trust. Released to payee on pass, refunded to payer on fail."""

    @abstractmethod
    async def lock(self, job_id: str, payer: str, payee: str, amount: int) -> str:
        """Lock fee in escrow. Returns tx hash."""
        ...

    @abstractmethod
    async def release(self, job_id: str) -> str:
        """Release fee to payee. Returns tx hash."""
        ...

    @abstractmethod
    async def refund(self, job_id: str) -> str:
        """Refund fee to payer. Returns tx hash."""
        ...

    @abstractmethod
    async def get_status(self, job_id: str) -> Optional[DepositInfo]:
        """Query fee deposit status."""
        ...


# ── Collateral Vault ─────────────────────────────────────────────────────────


class CollateralVault(ABC):
    """Holds delivery guarantee bond. Returned on success, slashed on failure."""

    @abstractmethod
    async def lock(self, job_id: str, payer: str, amount: int) -> str:
        """Lock collateral. Returns tx hash."""
        ...

    @abstractmethod
    async def unlock(self, job_id: str) -> str:
        """Return collateral to payer. Returns tx hash."""
        ...

    @abstractmethod
    async def slash(self, job_id: str, recipient: str) -> str:
        """Seize collateral to recipient (the harmed party). Returns tx hash."""
        ...

    @abstractmethod
    async def get_status(self, job_id: str) -> Optional[DepositInfo]:
        """Query collateral deposit status."""
        ...


# ── Mock implementations ────────────────────────────────────────────────────


class MockFeeEscrow(FeeEscrow):
    """In-memory mock fee escrow for tests."""

    def __init__(self) -> None:
        self._deposits: dict[str, DepositInfo] = {}

    async def lock(self, job_id: str, payer: str, payee: str, amount: int) -> str:
        if job_id in self._deposits:
            raise ValueError(f"Fee already locked: {job_id}")
        self._deposits[job_id] = DepositInfo(
            job_id=job_id,
            payer=payer,
            payee=payee,
            amount=amount,
            status=DepositStatus.LOCKED,
        )
        return f"escrow_tx:{job_id[:8]}:FEE"

    async def release(self, job_id: str) -> str:
        d = self._deposits.get(job_id)
        if d is None or d.status != DepositStatus.LOCKED:
            raise ValueError(f"Cannot release fee: {job_id}")
        d.status = DepositStatus.RELEASED
        return f"release_tx:{job_id[:8]}:FEE"

    async def refund(self, job_id: str) -> str:
        d = self._deposits.get(job_id)
        if d is None or d.status != DepositStatus.LOCKED:
            raise ValueError(f"Cannot refund fee: {job_id}")
        d.status = DepositStatus.REFUNDED
        return f"refund_tx:{job_id[:8]}:FEE"

    async def get_status(self, job_id: str) -> Optional[DepositInfo]:
        return self._deposits.get(job_id)


class MockCollateralVault(CollateralVault):
    """In-memory mock collateral vault for tests."""

    def __init__(self) -> None:
        self._deposits: dict[str, DepositInfo] = {}

    async def lock(self, job_id: str, payer: str, amount: int) -> str:
        if job_id in self._deposits:
            raise ValueError(f"Collateral already locked: {job_id}")
        self._deposits[job_id] = DepositInfo(
            job_id=job_id,
            payer=payer,
            payee="",
            amount=amount,
            status=DepositStatus.LOCKED,
        )
        return f"escrow_tx:{job_id[:8]}:COLLATERAL"

    async def unlock(self, job_id: str) -> str:
        d = self._deposits.get(job_id)
        if d is None or d.status != DepositStatus.LOCKED:
            raise ValueError(f"Cannot unlock collateral: {job_id}")
        d.status = DepositStatus.REFUNDED
        return f"refund_tx:{job_id[:8]}:COLLATERAL"

    async def slash(self, job_id: str, recipient: str) -> str:
        d = self._deposits.get(job_id)
        if d is None or d.status != DepositStatus.LOCKED:
            raise ValueError(f"Cannot slash collateral: {job_id}")
        d.status = DepositStatus.SLASHED
        return f"slash_tx:{job_id[:8]}"

    async def get_status(self, job_id: str) -> Optional[DepositInfo]:
        return self._deposits.get(job_id)
