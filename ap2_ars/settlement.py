"""Unified settlement layer: x402 (payment rail) + escrow (hold/release)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from .escrow import DepositType, EscrowClient, MockEscrowClient
from .x402 import MockX402Settlement, X402Settlement


@dataclass
class LockResult:
    x402_tx: Optional[str]
    escrow_tx: str
    ref: str  # lock_ref or collateral_ref


@dataclass
class SettleActionResult:
    tx_hash: str
    ref: str  # settlement_ref


@dataclass
class MandateSettleResult:
    x402_tx: str
    network: str
    payer: str


# ── Abstract interface ────────────────────────────────────────────────────────


class SettlementLayer(ABC):
    """Unified settlement: x402 for transfers, escrow contract for holding."""

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

    # Direct mandate payment (no escrow)
    @abstractmethod
    async def settle_mandate(
        self,
        job_id: str,
        amount: int,
        currency: str,
        payment_payload: dict,
        payment_requirement: dict,
    ) -> MandateSettleResult:
        ...


# ── Live implementation ──────────────────────────────────────────────────────


class LiveSettlementLayer(SettlementLayer):
    """Composes LiveX402Settlement + LiveEscrowClient for on-chain operations."""

    def __init__(self, x402: X402Settlement, escrow: EscrowClient) -> None:
        self._x402 = x402
        self._escrow = escrow

    async def lock_fee(
        self,
        job_id: str,
        amount: int,
        currency: str,
        payer_addr: str,
        payee_addr: str,
        payment_payload: Optional[dict] = None,
    ) -> LockResult:
        # Step 1: x402 settles USDC from user to escrow contract
        x402_tx = None
        if payment_payload:
            req = await self._x402.create_payment_requirement(job_id, amount, currency)
            result = await self._x402.settle(job_id, payment_payload, req.to_dict())
            x402_tx = result.transaction

        # Step 2: Tag the deposit in the escrow contract
        escrow_tx = await self._escrow.record_deposit(
            job_id, DepositType.FEE, payer_addr, payee_addr, amount,
        )
        return LockResult(x402_tx=x402_tx, escrow_tx=escrow_tx, ref=f"lock:{job_id}")

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
        x402_tx = None
        if payment_payload:
            req = await self._x402.create_payment_requirement(job_id, amount, currency)
            result = await self._x402.settle(job_id, payment_payload, req.to_dict())
            x402_tx = result.transaction

        escrow_tx = await self._escrow.record_deposit(
            job_id, DepositType.COLLATERAL, payer_addr, "", amount,
        )
        return LockResult(
            x402_tx=x402_tx, escrow_tx=escrow_tx, ref=f"collateral:{job_id}"
        )

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
        # x402 transfer from escrow to destination, then record as PRINCIPAL deposit
        x402_tx = None
        if payment_payload:
            req = await self._x402.create_payment_requirement(job_id, amount, currency)
            result = await self._x402.settle(job_id, payment_payload, req.to_dict())
            x402_tx = result.transaction

        escrow_tx = await self._escrow.record_deposit(
            job_id, DepositType.PRINCIPAL, "", destination or "", amount,
        )
        # Release immediately (principal goes straight to destination)
        release_tx = await self._escrow.release(job_id, DepositType.PRINCIPAL)
        return SettleActionResult(tx_hash=release_tx, ref=f"transfer:{job_id}")

    async def settle_mandate(
        self,
        job_id: str,
        amount: int,
        currency: str,
        payment_payload: dict,
        payment_requirement: dict,
    ) -> MandateSettleResult:
        # Direct x402 payment — no escrow, one-shot to merchant
        verify = await self._x402.verify(job_id, payment_payload, payment_requirement)
        if not verify.valid:
            raise ValueError(f"Payment verification failed: {verify.invalid_reason}")
        result = await self._x402.settle(job_id, payment_payload, payment_requirement)
        if not result.success:
            raise ValueError("x402 settlement failed")
        return MandateSettleResult(
            x402_tx=result.transaction or "",
            network=result.network or "",
            payer=result.payer or "",
        )


# ── Mock implementation (tests) ──────────────────────────────────────────────


class MockSettlementLayer(SettlementLayer):
    """In-memory mock for tests. Same interface, deterministic refs."""

    def __init__(self) -> None:
        self._x402 = MockX402Settlement()
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

    async def settle_mandate(
        self,
        job_id: str,
        amount: int,
        currency: str,
        payment_payload: dict,
        payment_requirement: dict,
    ) -> MandateSettleResult:
        await self._x402.verify(job_id, payment_payload, payment_requirement)
        result = await self._x402.settle(job_id, payment_payload, payment_requirement)
        return MandateSettleResult(
            x402_tx=result.transaction or "",
            network=result.network or "",
            payer=result.payer or "",
        )
