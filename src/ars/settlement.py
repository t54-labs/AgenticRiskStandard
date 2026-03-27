"""Settlement layer abstraction: ABC + mock for development/testing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from .escrow import DepositType, MockEscrowClient


@dataclass
class LockResult:
    x402_tx: Optional[str]
    escrow_tx: str
    ref: str  # lock_ref or collateral_ref


@dataclass
class SettleActionResult:
    tx_hash: str
    ref: str  # settlement_ref


# ── Abstract interface ────────────────────────────────────────────────────────


class SettlementLayer(ABC):
    """Unified settlement: payment rail for transfers, escrow for holding."""

    # Fee escrow
    @abstractmethod
    async def lock_fee(
        self,
        job_id: str,
        amount: int,
        currency: str,
        payer_addr: str,
        payee_addr: str,
        payment_payload: Optional[dict] = None,
    ) -> LockResult:
        ...

    @abstractmethod
    async def release_fee(self, job_id: str) -> SettleActionResult:
        ...

    @abstractmethod
    async def refund_fee(self, job_id: str) -> SettleActionResult:
        ...

    # Collateral
    @abstractmethod
    async def lock_collateral(
        self,
        job_id: str,
        amount: int,
        currency: str,
        payer_addr: str,
        payment_payload: Optional[dict] = None,
    ) -> LockResult:
        ...

    @abstractmethod
    async def slash_collateral(self, job_id: str, treasury: str) -> SettleActionResult:
        ...

    @abstractmethod
    async def unlock_collateral(self, job_id: str) -> SettleActionResult:
        ...

    # Principal release
    @abstractmethod
    async def release_principal(
        self,
        job_id: str,
        amount: int,
        currency: str,
        destination: Optional[str],
        payment_payload: Optional[dict] = None,
    ) -> SettleActionResult:
        ...


# ── Mock implementation ──────────────────────────────────────────────────────


class MockSettlementLayer(SettlementLayer):
    """In-memory mock for tests. Same interface, deterministic refs."""

    def __init__(self) -> None:
        self._escrow = MockEscrowClient()

    async def lock_fee(
        self,
        job_id: str,
        amount: int,
        currency: str,
        payer_addr: str,
        payee_addr: str,
        payment_payload: Optional[dict] = None,
    ) -> LockResult:
        escrow_tx = await self._escrow.record_deposit(
            job_id, DepositType.FEE, payer_addr, payee_addr, amount,
        )
        return LockResult(x402_tx=None, escrow_tx=escrow_tx, ref=f"lock:{job_id}")

    async def release_fee(self, job_id: str) -> SettleActionResult:
        tx = await self._escrow.release(job_id, DepositType.FEE)
        return SettleActionResult(tx_hash=tx, ref=f"settle:{job_id}:release")

    async def refund_fee(self, job_id: str) -> SettleActionResult:
        tx = await self._escrow.refund(job_id, DepositType.FEE)
        return SettleActionResult(tx_hash=tx, ref=f"settle:{job_id}:refund")

    async def lock_collateral(
        self,
        job_id: str,
        amount: int,
        currency: str,
        payer_addr: str,
        payment_payload: Optional[dict] = None,
    ) -> LockResult:
        escrow_tx = await self._escrow.record_deposit(
            job_id, DepositType.COLLATERAL, payer_addr, "", amount,
        )
        return LockResult(x402_tx=None, escrow_tx=escrow_tx, ref=f"collateral:{job_id}")

    async def slash_collateral(self, job_id: str, treasury: str) -> SettleActionResult:
        tx = await self._escrow.slash(job_id, treasury)
        return SettleActionResult(tx_hash=tx, ref=f"slashed:{job_id}")

    async def unlock_collateral(self, job_id: str) -> SettleActionResult:
        tx = await self._escrow.refund(job_id, DepositType.COLLATERAL)
        return SettleActionResult(tx_hash=tx, ref=f"collateral_unlocked:{job_id}")

    async def release_principal(
        self,
        job_id: str,
        amount: int,
        currency: str,
        destination: Optional[str],
        payment_payload: Optional[dict] = None,
    ) -> SettleActionResult:
        escrow_tx = await self._escrow.record_deposit(
            job_id, DepositType.PRINCIPAL, "", destination or "", amount,
        )
        release_tx = await self._escrow.release(job_id, DepositType.PRINCIPAL)
        return SettleActionResult(tx_hash=release_tx, ref=f"transfer:{job_id}")
