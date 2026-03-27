"""AP2 live settlement implementation (x402 + escrow) + re-exports from ars.settlement."""

from __future__ import annotations

from typing import Optional

from ars.escrow import DepositType, EscrowClient
from ars.settlement import (  # noqa: F401 — re-export for backward compat
    LockResult,
    MockSettlementLayer,
    SettleActionResult,
    SettlementLayer,
)

from .x402 import X402Settlement


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
        x402_tx = None
        if payment_payload:
            req = await self._x402.create_payment_requirement(job_id, amount, currency)
            result = await self._x402.settle(job_id, payment_payload, req.to_dict())
            x402_tx = result.transaction

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
        x402_tx = None
        if payment_payload:
            req = await self._x402.create_payment_requirement(job_id, amount, currency)
            result = await self._x402.settle(job_id, payment_payload, req.to_dict())
            x402_tx = result.transaction

        escrow_tx = await self._escrow.record_deposit(
            job_id, DepositType.PRINCIPAL, "", destination or "", amount,
        )
        release_tx = await self._escrow.release(job_id, DepositType.PRINCIPAL)
        return SettleActionResult(tx_hash=release_tx, ref=f"transfer:{job_id}")
