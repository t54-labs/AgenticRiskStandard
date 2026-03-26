"""Python interface to the ARSEscrow Solidity contract (+ mock for tests)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
    """Abstract interface for the ARSEscrow contract."""

    @abstractmethod
    async def record_deposit(
        self,
        job_id: str,
        deposit_type: DepositType,
        payer: str,
        payee: str,
        amount: int,
    ) -> str:
        """Tag a deposit after x402 transfer. Returns tx hash."""
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


# ── Live implementation (web3.py) ────────────────────────────────────────────


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
        fn = self._contract.functions.slash(self._job_id_bytes(job_id), treasury,)
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


# ── Mock implementation (tests) ──────────────────────────────────────────────


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
