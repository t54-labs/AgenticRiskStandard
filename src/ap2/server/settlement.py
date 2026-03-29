"""AP2 live settlement implementation (x402 + escrow) + re-exports from abstract_ars.settlement."""

from __future__ import annotations

from typing import Optional

from abstract_ars.settlement import (  # noqa: F401 — re-export for backward compat
    LockResult,
    MockSettlementLayer,
    SettleActionResult,
    SettlementLayer,
)

from .escrow import LiveEscrowClient
from .x402 import X402Settlement


class LiveSettlementLayer(SettlementLayer):
    """Composes LiveX402Settlement + LiveEscrowClient for on-chain operations."""

    def __init__(self, x402: X402Settlement, escrow: LiveEscrowClient) -> None:
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
        if payment_payload:
            req = await self._x402.create_payment_requirement(job_id, amount, currency)
            await self._x402.settle(job_id, payment_payload, req.to_dict())

        escrow_tx = await self._escrow.lock_fee(job_id, payer_addr, payee_addr, amount)
        return LockResult(escrow_tx=escrow_tx, ref=f"lock:{job_id}")

    async def release_fee(self, job_id: str) -> SettleActionResult:
        tx = await self._escrow.release_fee(job_id)
        return SettleActionResult(tx_hash=tx, ref=f"settle:{job_id}:release")

    async def refund_fee(self, job_id: str) -> SettleActionResult:
        tx = await self._escrow.refund_fee(job_id)
        return SettleActionResult(tx_hash=tx, ref=f"settle:{job_id}:refund")

    async def lock_collateral(
        self,
        job_id: str,
        amount: int,
        currency: str,
        payer_addr: str,
        payment_payload: Optional[dict] = None,
    ) -> LockResult:
        if payment_payload:
            req = await self._x402.create_payment_requirement(job_id, amount, currency)
            await self._x402.settle(job_id, payment_payload, req.to_dict())

        escrow_tx = await self._escrow.lock_collateral(job_id, payer_addr, amount)
        return LockResult(escrow_tx=escrow_tx, ref=f"collateral:{job_id}")

    async def slash_collateral(self, job_id: str, recipient: str) -> SettleActionResult:
        tx = await self._escrow.slash(job_id, recipient)
        return SettleActionResult(tx_hash=tx, ref=f"slashed:{job_id}")

    async def unlock_collateral(self, job_id: str) -> SettleActionResult:
        tx = await self._escrow.unlock_collateral(job_id)
        return SettleActionResult(tx_hash=tx, ref=f"collateral_unlocked:{job_id}")

    async def pay_premium(
        self, job_id: str, amount: int, currency: str, payer_addr: str, payee_addr: str,
    ) -> SettleActionResult:
        # Premium is a direct transfer via x402 (no escrow hold needed)
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
        if payment_payload:
            req = await self._x402.create_payment_requirement(job_id, amount, currency)
            await self._x402.settle(job_id, payment_payload, req.to_dict())

        await self._escrow.record_principal(job_id, "", destination or "", amount)
        release_tx = await self._escrow.release_principal(job_id)
        return SettleActionResult(tx_hash=release_tx, ref=f"transfer:{job_id}")
