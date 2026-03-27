"""x402 payment rail: real (Coinbase SDK) and mock implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

# USDC contract addresses per network (CAIP-2 format)
USDC_ADDRESSES: dict[str, str] = {
    "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # Base Mainnet
    "eip155:84532": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Base Sepolia
    "eip155:1": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # Ethereum Mainnet
}


@dataclass
class PaymentRequirement:
    """x402 V2 PaymentRequired payload."""

    job_id: str
    x402_version: int = 2
    scheme: str = "exact"
    network: str = "eip155:84532"
    asset: str = ""
    amount: str = "0"
    pay_to: str = ""
    max_timeout_seconds: int = 900

    def to_dict(self) -> dict:
        return {
            "x402Version": self.x402_version,
            "accepts": [
                {
                    "scheme": self.scheme,
                    "network": self.network,
                    "asset": self.asset,
                    "amount": self.amount,
                    "payTo": self.pay_to,
                    "maxTimeoutSeconds": self.max_timeout_seconds,
                }
            ],
        }


@dataclass
class VerifyResult:
    valid: bool
    payer: Optional[str] = None
    invalid_reason: Optional[str] = None


@dataclass
class SettleResult:
    success: bool
    transaction: Optional[str] = None  # on-chain tx hash
    network: Optional[str] = None
    payer: Optional[str] = None


# ── Abstract interface ────────────────────────────────────────────────────────


class X402Settlement(ABC):
    """Abstract x402 payment rail interface."""

    @abstractmethod
    async def create_payment_requirement(
        self, job_id: str, amount: int, currency: str,
    ) -> PaymentRequirement:
        ...

    @abstractmethod
    async def verify(
        self, job_id: str, payment_payload: dict, payment_requirement: dict,
    ) -> VerifyResult:
        ...

    @abstractmethod
    async def settle(
        self, job_id: str, payment_payload: dict, payment_requirement: dict,
    ) -> SettleResult:
        ...


# ── Live implementation (Coinbase x402 SDK) ──────────────────────────────────


class LiveX402Settlement(X402Settlement):
    """Real x402 settlement via Coinbase CDP facilitator + on-chain EIP-3009.

    Requires ``pip install x402[fastapi,evm]``.

    Parameters
    ----------
    facilitator_url:
        Testnet: ``https://x402.org/facilitator``
        Production: ``https://api.developer.coinbase.com/x402/facilitator``
    pay_to:
        EVM address to receive payments (escrow contract or merchant).
    network:
        CAIP-2 network ID. Default is Base Sepolia testnet.
    """

    def __init__(
        self,
        facilitator_url: str = "https://x402.org/facilitator",
        pay_to: str = "",
        network: str = "eip155:84532",
    ) -> None:
        # Lazy import — only needed when actually doing on-chain settlement
        from x402.http import FacilitatorConfig, HTTPFacilitatorClient  # type: ignore[import-untyped]
        from x402.mechanisms.evm.exact import ExactEvmServerScheme  # type: ignore[import-untyped]
        from x402.server import x402ResourceServer  # type: ignore[import-untyped]

        self._facilitator = HTTPFacilitatorClient(
            FacilitatorConfig(url=facilitator_url)
        )
        self._resource_server = x402ResourceServer(self._facilitator)
        self._resource_server.register(network, ExactEvmServerScheme())
        self._pay_to = pay_to
        self._network = network
        self._asset = USDC_ADDRESSES.get(network, "")

    async def create_payment_requirement(
        self, job_id: str, amount: int, currency: str,
    ) -> PaymentRequirement:
        return PaymentRequirement(
            job_id=job_id,
            network=self._network,
            asset=self._asset,
            amount=str(amount),
            pay_to=self._pay_to,
        )

    async def verify(
        self, job_id: str, payment_payload: dict, payment_requirement: dict,
    ) -> VerifyResult:
        result = await self._resource_server.verify(
            payment_payload=payment_payload, payment_requirements=payment_requirement,
        )
        return VerifyResult(
            valid=result.is_valid,
            payer=getattr(result, "payer", None),
            invalid_reason=getattr(result, "invalid_reason", None),
        )

    async def settle(
        self, job_id: str, payment_payload: dict, payment_requirement: dict,
    ) -> SettleResult:
        result = await self._resource_server.settle(
            payment_payload=payment_payload, payment_requirements=payment_requirement,
        )
        return SettleResult(
            success=result.success,
            transaction=result.transaction,
            network=result.network,
            payer=result.payer,
        )


# ── Mock implementation (tests) ──────────────────────────────────────────────


class MockX402Settlement(X402Settlement):
    """In-memory mock for tests. Deterministic refs, no network calls."""

    def __init__(self) -> None:
        self._requirements: dict[str, PaymentRequirement] = {}
        self._verified: dict[str, bool] = {}
        self._settled: dict[str, SettleResult] = {}

    async def create_payment_requirement(
        self, job_id: str, amount: int, currency: str,
    ) -> PaymentRequirement:
        req = PaymentRequirement(
            job_id=job_id, amount=str(amount), pay_to=f"0xmock_{job_id[:8]}",
        )
        self._requirements[job_id] = req
        return req

    async def verify(
        self, job_id: str, payment_payload: dict, payment_requirement: dict,
    ) -> VerifyResult:
        self._verified[job_id] = True
        return VerifyResult(valid=True, payer=f"0xpayer_{job_id[:8]}")

    async def settle(
        self, job_id: str, payment_payload: dict, payment_requirement: dict,
    ) -> SettleResult:
        if job_id not in self._verified:
            return SettleResult(success=False)
        result = SettleResult(
            success=True,
            transaction=f"0xtx_{job_id[:8]}",
            network="eip155:84532",
            payer=f"0xpayer_{job_id[:8]}",
        )
        self._settled[job_id] = result
        return result
