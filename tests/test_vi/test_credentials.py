"""VI credential creation, signing, and chain verification tests."""

import pytest

from vi.server.crypto import (
    compute_sd_hash,
    decode_sd_jwt,
    generate_es256_keypair,
    public_key_to_jwk,
    verify_sd_jwt_signature,
)
from vi.server.credentials import (
    create_l1_credential,
    create_l2_autonomous,
    create_l2_immediate,
    create_l3a_payment,
    create_l3b_checkout,
    verify_chain,
    verify_l1,
    verify_l2_binding,
    verify_l3_binding,
)


@pytest.fixture()
def issuer_keys():
    return generate_es256_keypair()


@pytest.fixture()
def user_keys():
    return generate_es256_keypair()


@pytest.fixture()
def agent_keys():
    return generate_es256_keypair()


def test_l1_create_and_verify(issuer_keys, user_keys):
    issuer_sk, _ = issuer_keys
    _, user_jwk = user_keys

    l1 = create_l1_credential(issuer_sk, user_jwk, pan_last_four="1234", scheme="visa")
    assert isinstance(l1, str)
    assert "~" in l1  # SD-JWT format

    # Verify signature
    assert verify_l1(l1, issuer_sk.public_key())

    # Decode and check payload
    decoded = decode_sd_jwt(l1)
    assert decoded["payload"]["vct"] == "VerifiedIdentity"
    assert decoded["payload"]["cnf"]["jwk"] == user_jwk


def test_l2_immediate_create(user_keys, issuer_keys):
    issuer_sk, _ = issuer_keys
    user_sk, user_jwk = user_keys

    l1 = create_l1_credential(issuer_sk, user_jwk)
    l2 = create_l2_immediate(user_sk, l1, checkout_jwt="checkout-1", amount=5000)

    decoded = decode_sd_jwt(l2)
    assert decoded["payload"]["mode"] == "immediate"
    assert decoded["payload"]["sd_hash"] == compute_sd_hash(l1)
    assert decoded["payload"]["payment_mandate"]["amount"] == 5000


def test_l2_autonomous_create_with_constraints(user_keys, agent_keys, issuer_keys):
    issuer_sk, _ = issuer_keys
    user_sk, user_jwk = user_keys
    _, agent_jwk = agent_keys

    l1 = create_l1_credential(issuer_sk, user_jwk)
    constraints = {
        "payment_amount": {"max_amount": 10000},
        "allowed_merchants": {"merchant_ids": ["m1"]},
    }
    l2 = create_l2_autonomous(user_sk, l1, agent_jwk, constraints)

    decoded = decode_sd_jwt(l2)
    assert decoded["payload"]["mode"] == "autonomous"
    assert decoded["payload"]["cnf"]["jwk"] == agent_jwk
    assert decoded["payload"]["constraints"] == constraints


def test_l3a_payment_create(agent_keys, user_keys, issuer_keys):
    issuer_sk, _ = issuer_keys
    user_sk, user_jwk = user_keys
    agent_sk, agent_jwk = agent_keys

    l1 = create_l1_credential(issuer_sk, user_jwk)
    l2 = create_l2_autonomous(user_sk, l1, agent_jwk, {})
    l3a = create_l3a_payment(agent_sk, l2, "tx-001", "vendor", 5000)

    decoded = decode_sd_jwt(l3a)
    assert decoded["payload"]["vct"] == "AgentPaymentFulfillment"
    assert decoded["payload"]["sd_hash"] == compute_sd_hash(l2)
    assert decoded["payload"]["amount"] == 5000


def test_l3b_checkout_create(agent_keys, user_keys, issuer_keys):
    issuer_sk, _ = issuer_keys
    user_sk, user_jwk = user_keys
    agent_sk, agent_jwk = agent_keys

    l1 = create_l1_credential(issuer_sk, user_jwk)
    l2 = create_l2_autonomous(user_sk, l1, agent_jwk, {})
    l3b = create_l3b_checkout(agent_sk, l2, "checkout-1", merchant_id="m1")

    decoded = decode_sd_jwt(l3b)
    assert decoded["payload"]["vct"] == "AgentCheckoutFulfillment"
    assert decoded["payload"]["sd_hash"] == compute_sd_hash(l2)
    assert decoded["payload"]["merchant_id"] == "m1"


def test_chain_verification_valid(issuer_keys, user_keys, agent_keys):
    issuer_sk, _ = issuer_keys
    user_sk, user_jwk = user_keys
    agent_sk, agent_jwk = agent_keys

    l1 = create_l1_credential(issuer_sk, user_jwk)
    l2 = create_l2_autonomous(user_sk, l1, agent_jwk, {})
    l3a = create_l3a_payment(agent_sk, l2, "tx", "vendor", 1000)
    l3b = create_l3b_checkout(agent_sk, l2, "checkout", merchant_id="m1")

    result = verify_chain(l1, l2, issuer_sk.public_key(), l3a, l3b)
    assert result["verified"] is True
    assert result["errors"] == []


def test_chain_verification_bad_binding(issuer_keys, user_keys, agent_keys):
    issuer_sk, _ = issuer_keys
    user_sk, user_jwk = user_keys
    agent_sk, agent_jwk = agent_keys

    l1 = create_l1_credential(issuer_sk, user_jwk)
    l2 = create_l2_autonomous(user_sk, l1, agent_jwk, {})

    # Create L3a referencing a DIFFERENT L2
    fake_l2 = create_l2_autonomous(user_sk, l1, agent_jwk, {"fake": True})
    l3a = create_l3a_payment(agent_sk, fake_l2, "tx", "vendor", 1000)
    l3b = create_l3b_checkout(agent_sk, l2, "checkout")

    result = verify_chain(l1, l2, issuer_sk.public_key(), l3a, l3b)
    assert result["verified"] is False
    assert any("L3a sd_hash" in e for e in result["errors"])


def test_sd_jwt_signature_verification(issuer_keys, user_keys):
    issuer_sk, _ = issuer_keys
    _, user_jwk = user_keys

    l1 = create_l1_credential(issuer_sk, user_jwk)
    assert verify_sd_jwt_signature(l1, issuer_sk.public_key()) is True

    # Wrong key should fail
    other_sk, _ = generate_es256_keypair()
    assert verify_sd_jwt_signature(l1, other_sk.public_key()) is False
