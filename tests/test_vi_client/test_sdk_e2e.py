"""VI Client SDK E2E tests — mirrors tests/test_client/test_sdk_e2e.py for AP2."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from abstract_ars_client._transport import Transport
from abstract_ars_client.evaluator import EvaluatorClient
from abstract_ars_client.underwriter import UnderwriterClient
from vi.client.agent import VIAgentClient
from vi.client.credential_provider import VICredentialProviderClient
from vi.client.merchant import VIMerchantClient
from vi.client.payment_network import VIPaymentNetworkClient
from vi.client.user import VIUserClient
from vi.server.crypto import generate_es256_keypair
from vi.server.server import create_app


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_client(cls, tc, es256_key=None):
    sk = SigningKey.generate()
    c = cls.__new__(cls)
    c._sk = sk
    t = Transport.__new__(Transport)
    t._client = tc
    c._transport = t
    if es256_key is not None and hasattr(cls, "_es256_key"):
        c._es256_key = es256_key
    return c


@pytest.fixture()
def tc():
    app = create_app(db_path=":memory:")
    with TestClient(app) as c:
        yield c


def _create_agreement(user, agent, evaluator, cred, merchant, network, **overrides):
    _, user_jwk = generate_es256_keypair()
    _, agent_jwk = generate_es256_keypair()
    _, cred_jwk = generate_es256_keypair()
    _, merchant_jwk = generate_es256_keypair()
    _, network_jwk = generate_es256_keypair()
    base = {
        "version": "vi_ars/0.1",
        "job_type": "purchase",
        "description": "SDK test",
        "mode": "autonomous",
        "user_pubkey": user.pubkey,
        "agent_pubkey": agent.pubkey,
        "evaluator_pubkey": evaluator.pubkey,
        "credential_provider_pubkey": cred.pubkey,
        "merchant_pubkey": merchant.pubkey,
        "payment_network_pubkey": network.pubkey,
        "user_jwk": user_jwk,
        "agent_jwk": agent_jwk,
        "credential_provider_jwk": cred_jwk,
        "merchant_jwk": merchant_jwk,
        "payment_network_jwk": network_jwk,
        "fee": {"amount": 2000, "currency": "USD"},
    }
    base.update(overrides)
    return base


# ── Tests ────────────────────────────────────────────────────────────────────


class TestFeeTrackE2E:
    def test_happy_path_via_sdk(self, tc):
        user = _make_client(VIUserClient, tc)
        agent_es256, _ = generate_es256_keypair()
        agent = _make_client(VIAgentClient, tc, es256_key=agent_es256)
        merchant = _make_client(VIMerchantClient, tc)
        cred_es256, _ = generate_es256_keypair()
        cred = _make_client(VICredentialProviderClient, tc, es256_key=cred_es256)
        net_es256, _ = generate_es256_keypair()
        network = _make_client(VIPaymentNetworkClient, tc, es256_key=net_es256)
        evaluator = _make_client(EvaluatorClient, tc)

        agr = _create_agreement(user, agent, evaluator, cred, merchant, network)
        resp = user.create_job(agr)
        job_id, agr_hash = resp.job_id, resp.agreement_hash

        user.sign_agreement(job_id, agr_hash)
        merchant.sign_agreement(job_id, agr_hash)

        # Credential chain
        cred.issue_l1(job_id, agr_hash, l1_serialized="l1")
        user.create_l2_mandate(
            job_id,
            agr_hash,
            "autonomous",
            "l2",
            constraints={"payment_amount": {"max_amount": 5000}},
        )
        cred.verify_l2(job_id, agr_hash)
        agent.create_l3a_payment(job_id, agr_hash, "l3a", "tx-1", "vendor", 2000)
        agent.create_l3b_checkout(
            job_id, agr_hash, "l3b", "checkout-1", merchant_id=merchant.pubkey
        )
        network.verify_chain(job_id, agr_hash)

        # Fee track
        user.lock_fee(job_id, agr_hash)
        merchant.submit_deliverable(job_id, agr_hash, "del-1")
        evaluator.evaluate(job_id, agr_hash, "pass")
        resp = user.settle_fee(job_id, agr_hash, "release")
        assert resp.phase == "CLOSED"


class TestCredentialThenFeeTrack:
    def test_credential_flow_via_sdk(self, tc):
        user = _make_client(VIUserClient, tc)
        agent_es256, _ = generate_es256_keypair()
        agent = _make_client(VIAgentClient, tc, es256_key=agent_es256)
        merchant = _make_client(VIMerchantClient, tc)
        cred_es256, _ = generate_es256_keypair()
        cred = _make_client(VICredentialProviderClient, tc, es256_key=cred_es256)
        net_es256, _ = generate_es256_keypair()
        network = _make_client(VIPaymentNetworkClient, tc, es256_key=net_es256)
        evaluator = _make_client(EvaluatorClient, tc)

        agr = _create_agreement(user, agent, evaluator, cred, merchant, network)
        resp = user.create_job(agr)
        job_id, agr_hash = resp.job_id, resp.agreement_hash

        user.sign_agreement(job_id, agr_hash)
        merchant.sign_agreement(job_id, agr_hash)

        # L1
        resp = cred.issue_l1(job_id, agr_hash, "l1-sdk")
        assert resp.credential_track_state == "L1_ISSUED"

        # L2
        resp = user.create_l2_mandate(job_id, agr_hash, "autonomous", "l2-sdk")
        assert resp.credential_track_state == "L2_CREATED"

        # Verify L2
        resp = cred.verify_l2(job_id, agr_hash)
        assert resp.credential_track_state == "L2_VERIFIED"

        # L3a + L3b
        resp = agent.create_l3a_payment(job_id, agr_hash, "l3a", "tx", "v", 1000)
        assert resp.credential_track_state == "L3A_CREATED"

        resp = agent.create_l3b_checkout(job_id, agr_hash, "l3b", "co")
        assert resp.credential_track_state == "L3B_CREATED"

        # Chain verify
        resp = network.verify_chain(job_id, agr_hash)
        assert resp.credential_track_state == "L3_CHAIN_VERIFIED"

        # Check credential state via agent
        creds = agent.get_credentials(job_id)
        assert creds["credential_track_state"] == "L3_CHAIN_VERIFIED"
        assert creds["l3_chain_verified"] is True


class TestUWFlowViaSdk:
    def test_uw_decide_via_sdk(self, tc):
        user = _make_client(VIUserClient, tc)
        agent_es256, _ = generate_es256_keypair()
        agent = _make_client(VIAgentClient, tc, es256_key=agent_es256)
        merchant = _make_client(VIMerchantClient, tc)
        cred_es256, _ = generate_es256_keypair()
        cred = _make_client(VICredentialProviderClient, tc, es256_key=cred_es256)
        net_es256, _ = generate_es256_keypair()
        network = _make_client(VIPaymentNetworkClient, tc, es256_key=net_es256)
        evaluator = _make_client(EvaluatorClient, tc)
        underwriter = _make_client(UnderwriterClient, tc)

        agr = _create_agreement(
            user,
            agent,
            evaluator,
            cred,
            merchant,
            network,
            requires_principal=True,
            max_premium=500,
            allow_uw_override=True,
            underwriter_pubkey=underwriter.pubkey,
            principal={"amount": 50000, "currency": "USD", "destination": "acct"},
        )
        resp = user.create_job(agr)
        job_id, agr_hash = resp.job_id, resp.agreement_hash

        user.sign_agreement(job_id, agr_hash)
        merchant.sign_agreement(job_id, agr_hash)

        # Complete credential chain
        cred.issue_l1(job_id, agr_hash, "l1")
        user.create_l2_mandate(job_id, agr_hash, "autonomous", "l2")
        cred.verify_l2(job_id, agr_hash)
        agent.create_l3a_payment(job_id, agr_hash, "l3a", "tx", "v", 1000)
        agent.create_l3b_checkout(job_id, agr_hash, "l3b", "co")
        network.verify_chain(job_id, agr_hash)

        # UW flow
        merchant.request_uw(job_id, agr_hash)
        resp = underwriter.uw_decide(job_id, agr_hash, approve=True, premium=200)
        assert resp.principal_track_state == "PREMIUM_PENDING"
