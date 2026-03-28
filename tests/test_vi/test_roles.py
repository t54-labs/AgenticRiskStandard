"""VI role registry and firewall tests."""

import pytest

from ars.errors import BadRequestError, ForbiddenError
from vi.server.models import VIAgreementDraft
from vi.server.roles import VIRole, VIRoleRegistry


def _make_agreement(**overrides) -> VIAgreementDraft:
    base = {
        "job_type": "purchase",
        "description": "test",
        "mode": "autonomous",
        "user_pubkey": "user-pk",
        "agent_pubkey": "agent-pk",
        "evaluator_pubkey": "eval-pk",
        "credential_provider_pubkey": "cred-pk",
        "merchant_pubkey": "merchant-pk",
        "payment_network_pubkey": "network-pk",
        "user_jwk": {"kty": "EC"},
        "credential_provider_jwk": {"kty": "EC"},
        "merchant_jwk": {"kty": "EC"},
        "payment_network_jwk": {"kty": "EC"},
        "fee": {"amount": 1000},
    }
    base.update(overrides)
    return VIAgreementDraft(**base)


def test_role_mapping():
    agr = _make_agreement()
    reg = VIRoleRegistry(agr)
    assert reg.get_role("user-pk") == VIRole.USER
    assert reg.get_role("agent-pk") == VIRole.AGENT
    assert reg.get_role("eval-pk") == VIRole.EVALUATOR
    assert reg.get_role("cred-pk") == VIRole.CREDENTIAL_PROVIDER
    assert reg.get_role("merchant-pk") == VIRole.MERCHANT
    assert reg.get_role("network-pk") == VIRole.PAYMENT_NETWORK


def test_optional_roles():
    # No agent, no underwriter
    agr = _make_agreement(agent_pubkey=None, underwriter_pubkey=None)
    reg = VIRoleRegistry(agr)
    assert reg.get_role("agent-pk") is None
    assert reg.get_role("uw-pk") is None

    # With underwriter
    agr = _make_agreement(underwriter_pubkey="uw-pk")
    reg = VIRoleRegistry(agr)
    assert reg.get_role("uw-pk") == VIRole.UNDERWRITER


def test_assert_role_success():
    agr = _make_agreement()
    reg = VIRoleRegistry(agr)
    reg.assert_role("user-pk", VIRole.USER)  # should not raise


def test_assert_role_failure():
    agr = _make_agreement()
    reg = VIRoleRegistry(agr)
    with pytest.raises(ForbiddenError):
        reg.assert_role("user-pk", VIRole.MERCHANT)


def test_firewall_pass():
    agr = _make_agreement()
    reg = VIRoleRegistry(agr)
    reg.validate_firewall()  # should not raise


def test_firewall_agent_equals_cred_provider():
    agr = _make_agreement(agent_pubkey="cred-pk")
    reg = VIRoleRegistry(agr)
    with pytest.raises(BadRequestError, match="[Ff]irewall"):
        reg.validate_firewall()


def test_firewall_agent_equals_payment_network():
    agr = _make_agreement(agent_pubkey="network-pk")
    reg = VIRoleRegistry(agr)
    with pytest.raises(BadRequestError, match="[Ff]irewall"):
        reg.validate_firewall()
