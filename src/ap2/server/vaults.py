"""AP2 live vault implementations (web3.py) for ARSEscrow.sol on-chain contract."""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from abstract_ars.vaults import CollateralVault, DepositInfo, DepositStatus, FeeEscrow


class DepositType(IntEnum):
    """On-chain deposit type for the ARSEscrow.sol contract."""

    FEE = 0
    COLLATERAL = 1


# ── Shared web3 boilerplate ─────────────────────────────────────────────────


class _LiveEscrowBase:
    """Shared web3.py setup for ARSEscrow.sol contract interaction.

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


# ── Fee Escrow (on-chain) ────────────────────────────────────────────────────


class LiveFeeEscrow(_LiveEscrowBase, FeeEscrow):
    """On-chain fee escrow via ARSEscrow.sol. Also handles principal deposits."""

    async def lock(self, job_id: str, payer: str, payee: str, amount: int) -> str:
        fn = self._contract.functions.recordDeposit(
            self._job_id_bytes(job_id), int(DepositType.FEE), payer, payee, amount,
        )
        return self._build_and_send(fn)

    async def release(self, job_id: str) -> str:
        fn = self._contract.functions.release(
            self._job_id_bytes(job_id), int(DepositType.FEE),
        )
        return self._build_and_send(fn)

    async def refund(self, job_id: str) -> str:
        fn = self._contract.functions.refund(
            self._job_id_bytes(job_id), int(DepositType.FEE),
        )
        return self._build_and_send(fn)

    async def get_status(self, job_id: str) -> Optional[DepositInfo]:
        result = self._contract.functions.getDeposit(
            self._job_id_bytes(job_id), int(DepositType.FEE),
        ).call()
        if result[3] == 0:
            return None
        return DepositInfo(
            job_id=job_id,
            payer=result[1],
            payee=result[2],
            amount=result[3],
            status=DepositStatus(result[5]),
        )


# ── Collateral Vault (on-chain) ─────────────────────────────────────────────


class LiveCollateralVault(_LiveEscrowBase, CollateralVault):
    """On-chain collateral vault via ARSEscrow.sol."""

    async def lock(self, job_id: str, payer: str, amount: int) -> str:
        fn = self._contract.functions.recordDeposit(
            self._job_id_bytes(job_id), int(DepositType.COLLATERAL), payer, "", amount,
        )
        return self._build_and_send(fn)

    async def unlock(self, job_id: str) -> str:
        fn = self._contract.functions.refund(
            self._job_id_bytes(job_id), int(DepositType.COLLATERAL),
        )
        return self._build_and_send(fn)

    async def slash(self, job_id: str, recipient: str) -> str:
        fn = self._contract.functions.slash(self._job_id_bytes(job_id), recipient)
        return self._build_and_send(fn)

    async def get_status(self, job_id: str) -> Optional[DepositInfo]:
        result = self._contract.functions.getDeposit(
            self._job_id_bytes(job_id), int(DepositType.COLLATERAL),
        ).call()
        if result[3] == 0:
            return None
        return DepositInfo(
            job_id=job_id,
            payer=result[1],
            payee="",
            amount=result[3],
            status=DepositStatus(result[5]),
        )
