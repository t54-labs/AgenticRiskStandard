"""6-actor role registry with cryptographic agent-payment firewall."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from ars.errors import BadRequestError, ForbiddenError

from .models import AP2AgreementDraft


class AP2Role(str, Enum):
    USER = "user"
    SHOPPING_AGENT = "shopping_agent"
    EVALUATOR = "evaluator"
    CREDENTIALS_PROVIDER = "credentials_provider"
    MERCHANT = "merchant"
    PAYMENT_PROCESSOR = "payment_processor"
    UNDERWRITER = "underwriter"


class RoleRegistry:
    """Maps public keys to AP2 roles. Enforces the agent-payment firewall."""

    def __init__(self, agreement: AP2AgreementDraft) -> None:
        self._agreement = agreement
        self._map: dict[str, AP2Role] = {
            agreement.user_pubkey: AP2Role.USER,
            agreement.shopping_agent_pubkey: AP2Role.SHOPPING_AGENT,
            agreement.evaluator_pubkey: AP2Role.EVALUATOR,
            agreement.credentials_provider_pubkey: AP2Role.CREDENTIALS_PROVIDER,
            agreement.merchant_pubkey: AP2Role.MERCHANT,
            agreement.payment_processor_pubkey: AP2Role.PAYMENT_PROCESSOR,
        }
        if agreement.underwriter_pubkey:
            self._map[agreement.underwriter_pubkey] = AP2Role.UNDERWRITER

    def get_role(self, pubkey: str) -> Optional[AP2Role]:
        return self._map.get(pubkey)

    def assert_role(self, pubkey: str, expected: AP2Role) -> None:
        """Raise ForbiddenError if the pubkey does not hold the expected role."""
        role = self.get_role(pubkey)
        if role != expected:
            raise ForbiddenError(
                f"Expected role {expected.value}, actor has {role.value if role else 'unknown'}"
            )

    def validate_firewall(self) -> None:
        """Enforce: shopping agent must NOT share a key with credentials provider
        or payment processor. This is the AP2 cryptographic firewall — the agent
        can orchestrate but never touch payment data."""
        agr = self._agreement
        if agr.shopping_agent_pubkey == agr.credentials_provider_pubkey:
            raise BadRequestError(
                "Firewall violation: shopping_agent and credentials_provider share a key"
            )
        if agr.shopping_agent_pubkey == agr.payment_processor_pubkey:
            raise BadRequestError(
                "Firewall violation: shopping_agent and payment_processor share a key"
            )
