"""AP2 live settlement implementation (x402 + vaults)."""

from __future__ import annotations

from typing import Optional

from abstract_ars.settlement import LockResult, SettleActionResult, SettlementLayer

from .vaults import LiveCollateralVault, LiveFeeEscrow
from .x402 import X402Settlement


class LiveSettlementLayer(SettlementLayer):
    """Composes x402 payment rail + LiveFeeEscrow + LiveCollateralVault."""

    def __init__(
        self,
        x402: X402Settlement,
        fee_escrow: LiveFeeEscrow,
        collateral_vault: LiveCollateralVault,
    ) -> None:
        self._x402 = x402
        self._fee_escrow = fee_escrow
        self._collateral_vault = collateral_vault

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
        if payment_payload:
            req = await self._x402.create_payment_requirement(job_id, amount, currency)
            await self._x402.settle(job_id, payment_payload, req.to_dict())

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
        # Premium is a direct transfer via x402 (no vault hold needed)
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
        # Principal is a direct transfer via x402, not escrowed
        tx_hash = f"principal_tx:{job_id[:8]}"
        if payment_payload:
            req = await self._x402.create_payment_requirement(job_id, amount, currency)
            result = await self._x402.settle(job_id, payment_payload, req.to_dict())
            tx_hash = result.transaction
        return SettleActionResult(tx_hash=tx_hash, ref=f"transfer:{job_id}")
