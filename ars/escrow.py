"""Escrow abstraction: ABC + mock for development/testing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


class DepositType(IntEnum):
    FEE = 0
    COLLATERAL = 1
    PRINCIPAL = 2


class DepositStatus(IntEnum):
    LOCKED = 0
    RELEASED = 1
    REFUNDED = 2
    SLASHED = 3


@dataclass
class DepositInfo:
    job_id: str
    deposit_type: DepositType
    payer: str
    payee: str
    amount: int
    status: DepositStatus


# ── Abstract interface ────────────────────────────────────────────────────────


class EscrowClient(ABC):
    """Abstract escrow contract interface."""

    @abstractmethod
    async def record_deposit(
        self,
        job_id: str,
        deposit_type: DepositType,
        payer: str,
        payee: str,
        amount: int,
    ) -> str:
        """Tag a deposit. Returns tx hash."""
        ...

    @abstractmethod
    async def release(self, job_id: str, deposit_type: DepositType) -> str:
        """Release funds to payee. Returns tx hash."""
        ...

    @abstractmethod
    async def refund(self, job_id: str, deposit_type: DepositType) -> str:
        """Refund funds to payer. Returns tx hash."""
        ...

    @abstractmethod
    async def slash(self, job_id: str, treasury: str) -> str:
        """Slash collateral to treasury. Returns tx hash."""
        ...

    @abstractmethod
    async def get_deposit(
        self, job_id: str, deposit_type: DepositType,
    ) -> Optional[DepositInfo]:
        """Query deposit status."""
        ...


# ── Mock implementation ──────────────────────────────────────────────────────


class MockEscrowClient(EscrowClient):
    """In-memory mock for tests. Same interface, no blockchain."""

    def __init__(self) -> None:
        self._deposits: dict[str, DepositInfo] = {}

    def _key(self, job_id: str, deposit_type: DepositType) -> str:
        return f"{job_id}:{deposit_type.name}"

    async def record_deposit(
        self,
        job_id: str,
        deposit_type: DepositType,
        payer: str,
        payee: str,
        amount: int,
    ) -> str:
        key = self._key(job_id, deposit_type)
        if key in self._deposits:
            raise ValueError(f"Already deposited: {key}")
        self._deposits[key] = DepositInfo(
            job_id=job_id,
            deposit_type=deposit_type,
            payer=payer,
            payee=payee,
            amount=amount,
            status=DepositStatus.LOCKED,
        )
        return f"escrow_tx:{job_id[:8]}:{deposit_type.name}"

    async def release(self, job_id: str, deposit_type: DepositType) -> str:
        key = self._key(job_id, deposit_type)
        d = self._deposits.get(key)
        if d is None or d.status != DepositStatus.LOCKED:
            raise ValueError(f"Cannot release: {key}")
        d.status = DepositStatus.RELEASED
        return f"release_tx:{job_id[:8]}:{deposit_type.name}"

    async def refund(self, job_id: str, deposit_type: DepositType) -> str:
        key = self._key(job_id, deposit_type)
        d = self._deposits.get(key)
        if d is None or d.status != DepositStatus.LOCKED:
            raise ValueError(f"Cannot refund: {key}")
        d.status = DepositStatus.REFUNDED
        return f"refund_tx:{job_id[:8]}:{deposit_type.name}"

    async def slash(self, job_id: str, treasury: str) -> str:
        key = self._key(job_id, DepositType.COLLATERAL)
        d = self._deposits.get(key)
        if d is None or d.status != DepositStatus.LOCKED:
            raise ValueError(f"Cannot slash: {key}")
        d.status = DepositStatus.SLASHED
        return f"slash_tx:{job_id[:8]}"

    async def get_deposit(
        self, job_id: str, deposit_type: DepositType,
    ) -> Optional[DepositInfo]:
        return self._deposits.get(self._key(job_id, deposit_type))
