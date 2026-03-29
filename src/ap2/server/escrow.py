"""AP2 live escrow implementation (web3.py) + re-exports from abstract_ars.escrow."""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from abstract_ars.vaults import (  # noqa: F401 — re-export for backward compat
    CollateralVault,
    DepositInfo,
    DepositStatus,
    FeeEscrow,
    MockCollateralVault,
    MockFeeEscrow,
)


class DepositType(IntEnum):
    """On-chain deposit type for the ARSEscrow.sol contract."""

    FEE = 0
    COLLATERAL = 1
    PRINCIPAL = 2


class LiveEscrowClient:
    """Calls the ARSEscrow contract on-chain via web3.py.

    This is the AP2-specific on-chain implementation that maps to the
    ARSEscrow.sol contract's DepositType enum. It implements both
    FeeEscrow and CollateralVault operations via a unified contract.

    Requires ``pip install web3``.
    """

    def __init__(
        self, rpc_url: str, contract_address: str, abi: list, operator_key: str,
    ) -> None:
        from eth_account import Account  # type: ignore[import-untyped]
        from web3 import Web3  # type: ignore[import-untyped]

        self._w3 = Web3(Web3.HTTPProvider(rpc_url))
        self._contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(contract_address), abi=abi,
        )
        self._operator = Account.from_key(operator_key)
        self._chain_id = self._w3.eth.chain_id

    def _job_id_bytes(self, job_id: str) -> bytes:
        from web3 import Web3  # type: ignore[import-untyped]

        return Web3.keccak(text=job_id)

    def _build_and_send(self, fn) -> str:
        tx = fn.build_transaction(
            {
                "from": self._operator.address,
                "nonce": self._w3.eth.get_transaction_count(self._operator.address),
                "chainId": self._chain_id,
            }
        )
        signed = self._operator.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()

    # Fee operations
    async def lock_fee(self, job_id: str, payer: str, payee: str, amount: int,) -> str:
        fn = self._contract.functions.recordDeposit(
            self._job_id_bytes(job_id), int(DepositType.FEE), payer, payee, amount,
        )
        return self._build_and_send(fn)

    async def release_fee(self, job_id: str) -> str:
        fn = self._contract.functions.release(
            self._job_id_bytes(job_id), int(DepositType.FEE),
        )
        return self._build_and_send(fn)

    async def refund_fee(self, job_id: str) -> str:
        fn = self._contract.functions.refund(
            self._job_id_bytes(job_id), int(DepositType.FEE),
        )
        return self._build_and_send(fn)

    # Collateral operations
    async def lock_collateral(self, job_id: str, payer: str, amount: int) -> str:
        fn = self._contract.functions.recordDeposit(
            self._job_id_bytes(job_id), int(DepositType.COLLATERAL), payer, "", amount,
        )
        return self._build_and_send(fn)

    async def unlock_collateral(self, job_id: str) -> str:
        fn = self._contract.functions.refund(
            self._job_id_bytes(job_id), int(DepositType.COLLATERAL),
        )
        return self._build_and_send(fn)

    async def slash(self, job_id: str, recipient: str) -> str:
        fn = self._contract.functions.slash(self._job_id_bytes(job_id), recipient)
        return self._build_and_send(fn)

    # Principal operations
    async def record_principal(
        self, job_id: str, payer: str, payee: str, amount: int,
    ) -> str:
        fn = self._contract.functions.recordDeposit(
            self._job_id_bytes(job_id),
            int(DepositType.PRINCIPAL),
            payer,
            payee,
            amount,
        )
        return self._build_and_send(fn)

    async def release_principal(self, job_id: str) -> str:
        fn = self._contract.functions.release(
            self._job_id_bytes(job_id), int(DepositType.PRINCIPAL),
        )
        return self._build_and_send(fn)
