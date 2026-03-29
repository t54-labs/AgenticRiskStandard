"""Settlement layer abstraction: ABC + mock for development/testing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from .vaults import MockCollateralVault, MockFeeEscrow


@dataclass
class LockResult:
    escrow_tx: str
    ref: str  # lock_ref or collateral_ref


@dataclass
class SettleActionResult:
    tx_hash: str
    ref: str  # settlement_ref


# ── Abstract interface ────────────────────────────────────────────────────────


class SettlementLayer(ABC):
    """Unified settlement: fee escrow + collateral vault + premium + principal."""

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
    async def slash_collateral(self, job_id: str, recipient: str) -> SettleActionResult:
        """Seize collateral to recipient (the harmed party, typically the requestor)."""
        ...

    @abstractmethod
    async def unlock_collateral(self, job_id: str) -> SettleActionResult:
        ...

    # Premium (insurance payment from requestor to underwriter)
    @abstractmethod
    async def pay_premium(
        self, job_id: str, amount: int, currency: str, payer_addr: str, payee_addr: str,
    ) -> SettleActionResult:
        """Transfer premium from requestor to underwriter."""
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
        self._fee_escrow = MockFeeEscrow()
        self._collateral_vault = MockCollateralVault()

    async def lock_fee(
        self,
        job_id: str,
        amount: int,
        currency: str,
        payer_addr: str,
        payee_addr: str,
        payment_payload: Optional[dict] = None,
    ) -> LockResult:
        escrow_tx = await self._fee_escrow.lock(job_id, payer_addr, payee_addr, amount)
        return LockResult(escrow_tx=escrow_tx, ref=f"lock:{job_id}")

    async def release_fee(self, job_id: str) -> SettleActionResult:
        tx = await self._fee_escrow.release(job_id)
        return SettleActionResult(tx_hash=tx, ref=f"settle:{job_id}:release")

    async def refund_fee(self, job_id: str) -> SettleActionResult:
        tx = await self._fee_escrow.refund(job_id)
        return SettleActionResult(tx_hash=tx, ref=f"settle:{job_id}:refund")

    async def lock_collateral(
        self,
        job_id: str,
        amount: int,
        currency: str,
        payer_addr: str,
        payment_payload: Optional[dict] = None,
    ) -> LockResult:
        escrow_tx = await self._collateral_vault.lock(job_id, payer_addr, amount)
        return LockResult(escrow_tx=escrow_tx, ref=f"collateral:{job_id}")

    async def slash_collateral(self, job_id: str, recipient: str) -> SettleActionResult:
        tx = await self._collateral_vault.slash(job_id, recipient)
        return SettleActionResult(tx_hash=tx, ref=f"slashed:{job_id}")

    async def unlock_collateral(self, job_id: str) -> SettleActionResult:
        tx = await self._collateral_vault.unlock(job_id)
        return SettleActionResult(tx_hash=tx, ref=f"collateral_unlocked:{job_id}")

    async def pay_premium(
        self, job_id: str, amount: int, currency: str, payer_addr: str, payee_addr: str,
    ) -> SettleActionResult:
        return SettleActionResult(
            tx_hash=f"premium_tx:{job_id[:8]}", ref=f"premium:{job_id}",
        )

    async def release_principal(
        self,
        job_id: str,
        amount: int,
        currency: str,
        destination: Optional[str],
        payment_payload: Optional[dict] = None,
    ) -> SettleActionResult:
        principal_key = f"principal:{job_id}"
        await self._fee_escrow.lock(principal_key, "", destination or "", amount)
        release_tx = await self._fee_escrow.release(principal_key)
        return SettleActionResult(tx_hash=release_tx, ref=f"transfer:{job_id}")
