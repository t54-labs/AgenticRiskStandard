"""Tests for 6-actor role registry and firewall."""

from __future__ import annotations

import pytest
from nacl.signing import SigningKey

from ars.errors import BadRequestError, ForbiddenError

from ap2_ars.models import AP2AgreementDraft, FeeTerms, Modality
from ap2_ars.roles import AP2Role, RoleRegistry


def _make_agreement(**overrides) -> AP2AgreementDraft:
    defaults = {
        "job_type": "purchase",
        "description": "test",
        "modality": Modality.HUMAN_PRESENT,
        "user_pubkey": "user_pk",
        "shopping_agent_pubkey": "agent_pk",
        "evaluator_pubkey": "eval_pk",
        "credentials_provider_pubkey": "cred_pk",
        "merchant_pubkey": "merchant_pk",
        "payment_processor_pubkey": "processor_pk",
        "fee": FeeTerms(amount=1000),
    }
    defaults.update(overrides)
    return AP2AgreementDraft(**defaults)


def test_role_mapping():
    agr = _make_agreement()
    reg = RoleRegistry(agr)
    assert reg.get_role("user_pk") == AP2Role.USER
    assert reg.get_role("agent_pk") == AP2Role.SHOPPING_AGENT
    assert reg.get_role("eval_pk") == AP2Role.EVALUATOR
    assert reg.get_role("cred_pk") == AP2Role.CREDENTIALS_PROVIDER
    assert reg.get_role("merchant_pk") == AP2Role.MERCHANT
    assert reg.get_role("processor_pk") == AP2Role.PAYMENT_PROCESSOR
    assert reg.get_role("unknown") is None


def test_optional_roles():
    agr = _make_agreement(underwriter_pubkey="uw_pk")
    reg = RoleRegistry(agr)
    assert reg.get_role("uw_pk") == AP2Role.UNDERWRITER


def test_assert_role_success():
    agr = _make_agreement()
    reg = RoleRegistry(agr)
    reg.assert_role("user_pk", AP2Role.USER)  # should not raise


def test_assert_role_failure():
    agr = _make_agreement()
    reg = RoleRegistry(agr)
    with pytest.raises(ForbiddenError):
        reg.assert_role("user_pk", AP2Role.MERCHANT)


def test_firewall_pass():
    agr = _make_agreement()
    reg = RoleRegistry(agr)
    reg.validate_firewall()  # should not raise


def test_firewall_agent_equals_cred_provider():
    agr = _make_agreement(
        shopping_agent_pubkey="same_key", credentials_provider_pubkey="same_key",
    )
    reg = RoleRegistry(agr)
    with pytest.raises(BadRequestError, match="(?i)firewall"):
        reg.validate_firewall()


def test_firewall_agent_equals_processor():
    agr = _make_agreement(
        shopping_agent_pubkey="same_key", payment_processor_pubkey="same_key",
    )
    reg = RoleRegistry(agr)
    with pytest.raises(BadRequestError, match="(?i)firewall"):
        reg.validate_firewall()
