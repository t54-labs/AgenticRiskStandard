from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VaultEntry:
    job_id: str
    amount: int
    currency: str
    locked: bool = True
    settled: bool = False
    settlement_action: Optional[str] = None


class MockEscrowVault:
    """In-memory fee escrow vault. Issues deterministic refs and tracks balances."""

    def __init__(self) -> None:
        self._entries: dict[str, VaultEntry] = {}

    def lock(self, job_id: str, amount: int, currency: str) -> str:
        lock_ref = f"lock:{job_id}"
        if lock_ref in self._entries:
            raise ValueError(f"Already locked for job {job_id}")
        self._entries[lock_ref] = VaultEntry(
            job_id=job_id, amount=amount, currency=currency
        )
        return lock_ref

    def settle(self, lock_ref: str, action: str) -> str:
        entry = self._entries.get(lock_ref)
        if entry is None:
            raise ValueError(f"No lock found: {lock_ref}")
        if entry.settled:
            raise ValueError(f"Already settled: {lock_ref}")
        entry.settled = True
        entry.locked = False
        entry.settlement_action = action
        return f"settle:{entry.job_id}:{action}"

    def get_entry(self, lock_ref: str) -> Optional[VaultEntry]:
        return self._entries.get(lock_ref)


@dataclass
class CollateralEntry:
    job_id: str
    amount: int
    currency: str
    locked: bool = True


class MockCollateralVault:
    def __init__(self) -> None:
        self._entries: dict[str, CollateralEntry] = {}

    def lock(self, job_id: str, amount: int, currency: str) -> str:
        ref = f"collateral:{job_id}"
        if ref in self._entries:
            raise ValueError(f"Collateral already locked for job {job_id}")
        self._entries[ref] = CollateralEntry(
            job_id=job_id, amount=amount, currency=currency
        )
        return ref

    def unlock(self, collateral_ref: str) -> str:
        e = self._entries.get(collateral_ref)
        if e is None:
            raise ValueError(f"No collateral found: {collateral_ref}")
        if not e.locked:
            raise ValueError(f"Collateral already unlocked: {collateral_ref}")
        e.locked = False
        return f"collateral_unlocked:{e.job_id}"

    def get_entry(self, collateral_ref: str) -> Optional[CollateralEntry]:
        return self._entries.get(collateral_ref)


@dataclass
class PrincipalTransfer:
    job_id: str
    amount: int
    currency: str
    destination: Optional[str] = None


class MockPrincipalVault:
    def __init__(self) -> None:
        self._transfers: dict[str, PrincipalTransfer] = {}

    def release(
        self, job_id: str, amount: int, currency: str, destination: Optional[str]
    ) -> str:
        ref = f"transfer:{job_id}"
        if ref in self._transfers:
            raise ValueError(f"Principal already released for job {job_id}")
        self._transfers[ref] = PrincipalTransfer(
            job_id=job_id, amount=amount, currency=currency, destination=destination
        )
        return ref
