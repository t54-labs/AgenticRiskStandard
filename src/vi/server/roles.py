"""7-role registry with cryptographic agent-payment firewall."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from abstract_ars.errors import BadRequestError, ForbiddenError

from .models import VIAgreementDraft


class VIRole(str, Enum):
    # Decision-making actors (humans or agents making choices)
    USER = "user"
    AGENT = "agent"  # optional; user's AI proxy, creates L3 credentials
    EVALUATOR = "evaluator"
    MERCHANT = "merchant"
    UNDERWRITER = "underwriter"  # optional; only for fund-moving jobs
    # Server-side infrastructure (executes operations, doesn't make decisions;
    # listed here for signature verification and firewall enforcement)
    CREDENTIAL_PROVIDER = "credential_provider"  # issues L1, verifies chains
    PAYMENT_NETWORK = "payment_network"  # verifies chains, settles


class VIRoleRegistry:
    """Maps public keys to VI roles. Enforces the agent-credential firewall."""

    def __init__(self, agreement: VIAgreementDraft) -> None:
        self._agreement = agreement
        self._map: dict[str, VIRole] = {
            agreement.user_pubkey: VIRole.USER,
            agreement.evaluator_pubkey: VIRole.EVALUATOR,
            agreement.credential_provider_pubkey: VIRole.CREDENTIAL_PROVIDER,
            agreement.merchant_pubkey: VIRole.MERCHANT,
            agreement.payment_network_pubkey: VIRole.PAYMENT_NETWORK,
        }
        if agreement.agent_pubkey:
            self._map[agreement.agent_pubkey] = VIRole.AGENT
        if agreement.underwriter_pubkey:
            self._map[agreement.underwriter_pubkey] = VIRole.UNDERWRITER

    def get_role(self, pubkey: str) -> Optional[VIRole]:
        return self._map.get(pubkey)

    def assert_role(self, pubkey: str, expected: VIRole) -> None:
        """Raise ForbiddenError if the pubkey does not hold the expected role."""
        role = self.get_role(pubkey)
        if role != expected:
            raise ForbiddenError(
                f"Expected role {expected.value}, "
                f"actor has {role.value if role else 'unknown'}"
            )

    def validate_firewall(self) -> None:
        """Enforce: agent must NOT share a key with credential provider
        or payment network. Only checked when agent_pubkey is provided."""
        agr = self._agreement
        if not agr.agent_pubkey:
            return  # no separate agent, no firewall needed
        if agr.agent_pubkey == agr.credential_provider_pubkey:
            raise BadRequestError(
                "Firewall violation: agent and credential_provider share a key"
            )
        if agr.agent_pubkey == agr.payment_network_pubkey:
            raise BadRequestError(
                "Firewall violation: agent and payment_network share a key"
            )
