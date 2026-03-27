"""AP2 live escrow implementation (web3.py) + re-exports from ars.escrow."""

from __future__ import annotations

from typing import Optional

from ars.escrow import (  # noqa: F401 — re-export for backward compat
    DepositInfo,
    DepositStatus,
    DepositType,
    EscrowClient,
    MockEscrowClient,
)


class LiveEscrowClient(EscrowClient):
    """Calls the ARSEscrow contract on-chain via web3.py.

    Requires ``pip install web3``.

    Parameters
    ----------
    rpc_url:
        JSON-RPC URL (e.g. ``https://sepolia.base.org``).
    contract_address:
        Deployed ARSEscrow contract address.
    abi:
        Contract ABI (list of dicts).
    operator_key:
        Private key hex of the OPERATOR_ROLE account.
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

    async def record_deposit(
        self,
        job_id: str,
        deposit_type: DepositType,
        payer: str,
        payee: str,
        amount: int,
    ) -> str:
        fn = self._contract.functions.recordDeposit(
            self._job_id_bytes(job_id), int(deposit_type), payer, payee, amount,
        )
        return self._build_and_send(fn)

    async def release(self, job_id: str, deposit_type: DepositType) -> str:
        fn = self._contract.functions.release(
            self._job_id_bytes(job_id), int(deposit_type),
        )
        return self._build_and_send(fn)

    async def refund(self, job_id: str, deposit_type: DepositType) -> str:
        fn = self._contract.functions.refund(
            self._job_id_bytes(job_id), int(deposit_type),
        )
        return self._build_and_send(fn)

    async def slash(self, job_id: str, treasury: str) -> str:
        fn = self._contract.functions.slash(self._job_id_bytes(job_id), treasury)
        return self._build_and_send(fn)

    async def get_deposit(
        self, job_id: str, deposit_type: DepositType,
    ) -> Optional[DepositInfo]:
        result = self._contract.functions.getDeposit(
            self._job_id_bytes(job_id), int(deposit_type),
        ).call()
        if result[3] == 0:  # amount == 0 means no deposit
            return None
        return DepositInfo(
            job_id=job_id,
            deposit_type=deposit_type,
            payer=result[1],
            payee=result[2],
            amount=result[3],
            status=DepositStatus(result[5]),
        )
