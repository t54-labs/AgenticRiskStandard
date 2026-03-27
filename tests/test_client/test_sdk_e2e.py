"""End-to-end tests for the client SDK against the AP2-ARS server."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from ap2.server.server import create_app
from ap2.client.merchant import MerchantClient
from ap2.client.user import UserClient
from ars_client._transport import Transport
from ars_client.evaluator import EvaluatorClient
from ars_client.underwriter import UnderwriterClient


@pytest.fixture()
def app():
    return create_app(db_path=":memory:")


@pytest.fixture()
def transport(app):
    """Inject FastAPI TestClient as the transport backend."""
    with TestClient(app) as tc:
        t = Transport.__new__(Transport)
        t._client = tc
        yield t


def _make_client(cls, transport):
    sk = SigningKey.generate()
    client = cls.__new__(cls)
    client._sk = sk
    client._transport = transport
    return client


class TestFeeTrackE2E:
    def test_happy_path_via_sdk(self, transport):
        user = _make_client(UserClient, transport)
        merchant = _make_client(MerchantClient, transport)
        evaluator = _make_client(EvaluatorClient, transport)

        # Create job
        agreement = {
            "version": "ap2_ars/0.1",
            "job_type": "purchase",
            "description": "SDK test",
            "modality": "human-present",
            "user_pubkey": user.pubkey,
            "shopping_agent_pubkey": SigningKey.generate().verify_key.encode().hex(),
            "evaluator_pubkey": evaluator.pubkey,
            "credentials_provider_pubkey": SigningKey.generate()
            .verify_key.encode()
            .hex(),
            "merchant_pubkey": merchant.pubkey,
            "payment_processor_pubkey": SigningKey.generate().verify_key.encode().hex(),
            "fee": {"amount": 1000, "currency": "USD"},
        }
        job = user.create_job(agreement)
        assert job.phase == "NEGOTIATION"

        # Sign agreement
        user.sign_agreement(job.job_id, job.agreement_hash)
        sig_resp = merchant.sign_agreement(job.job_id, job.agreement_hash)
        assert sig_resp.phase == "TRANSACTION"

        # Lock fee
        lock = user.lock_fee(job.job_id, job.agreement_hash)
        assert lock.lock_ref is not None

        # Deliver
        merchant.submit_deliverable(job.job_id, job.agreement_hash, "ipfs://test")

        # Evaluate
        evaluator.evaluate(job.job_id, job.agreement_hash, "pass")

        # Settle
        result = user.settle_fee(job.job_id, job.agreement_hash, "release")
        assert result.phase == "CLOSED"
        assert result.fee_track_state == "FEE_SETTLED_RELEASE"


class TestMandateThenFeeTrack:
    def test_mandate_flow_via_sdk(self, transport):
        user = _make_client(UserClient, transport)
        merchant = _make_client(MerchantClient, transport)
        evaluator = _make_client(EvaluatorClient, transport)
        cred_sk = SigningKey.generate()

        agreement = {
            "version": "ap2_ars/0.1",
            "job_type": "purchase",
            "description": "Mandate SDK test",
            "modality": "human-present",
            "user_pubkey": user.pubkey,
            "shopping_agent_pubkey": SigningKey.generate().verify_key.encode().hex(),
            "evaluator_pubkey": evaluator.pubkey,
            "credentials_provider_pubkey": cred_sk.verify_key.encode().hex(),
            "merchant_pubkey": merchant.pubkey,
            "payment_processor_pubkey": SigningKey.generate().verify_key.encode().hex(),
            "fee": {"amount": 5000, "currency": "USD"},
        }
        job = user.create_job(agreement)
        user.sign_agreement(job.job_id, job.agreement_hash)
        merchant.sign_agreement(job.job_id, job.agreement_hash)

        # Intent mandate
        intent = user.create_intent_mandate(
            job.job_id,
            job.agreement_hash,
            budget=5000,
            allowed_merchants=[merchant.pubkey],
            description="Buy widgets",
        )
        assert intent.mandate_track_state == "INTENT_CREATED"

        # Cart mandate
        line_items = [
            {"sku": "W-001", "description": "Widget", "quantity": 2, "unit_price": 1000}
        ]
        cart = merchant.propose_cart(
            job.job_id, job.agreement_hash, line_items, total=2000
        )
        assert cart.mandate_track_state == "CART_PROPOSED"

        # Sign cart
        merchant.sign_cart(job.job_id, job.agreement_hash)

        # Approve cart (human-present)
        user.approve_cart(job.job_id, job.agreement_hash)

        # Payment mandate (credentials provider creates it — done via envelope)
        cred_transport = transport
        cred_client = UserClient.__new__(UserClient)
        cred_client._sk = cred_sk
        cred_client._transport = cred_transport
        cred_client._post_envelope(
            f"/jobs/{job.job_id}/mandates/payment",
            "PAYMENT_MANDATE_CREATED",
            job.job_id,
            job.agreement_hash,
            payload={"payment_token_hash": "tok_hash"},
        )

        # User signs payment
        user.sign_payment(job.job_id, job.agreement_hash)

        # Now fee track: lock → deliver → evaluate → settle
        lock = user.lock_fee(job.job_id, job.agreement_hash)
        assert lock.lock_ref is not None

        merchant.submit_deliverable(job.job_id, job.agreement_hash, "ipfs://widgets")
        evaluator.evaluate(job.job_id, job.agreement_hash, "pass")
        result = user.settle_fee(job.job_id, job.agreement_hash, "release")
        assert result.phase == "CLOSED"


class TestUWFlowViaSdk:
    def test_uw_decide_via_sdk(self, transport):
        user = _make_client(UserClient, transport)
        merchant = _make_client(MerchantClient, transport)
        evaluator = _make_client(EvaluatorClient, transport)
        underwriter = _make_client(UnderwriterClient, transport)

        agreement = {
            "version": "ap2_ars/0.1",
            "job_type": "fund-moving",
            "description": "UW SDK test",
            "modality": "human-present",
            "user_pubkey": user.pubkey,
            "shopping_agent_pubkey": SigningKey.generate().verify_key.encode().hex(),
            "evaluator_pubkey": evaluator.pubkey,
            "credentials_provider_pubkey": SigningKey.generate()
            .verify_key.encode()
            .hex(),
            "merchant_pubkey": merchant.pubkey,
            "payment_processor_pubkey": SigningKey.generate().verify_key.encode().hex(),
            "underwriter_pubkey": underwriter.pubkey,
            "principal": {
                "amount": 50000,
                "currency": "USD",
                "destination": "acct_123",
            },
            "fee": {"amount": 1000, "currency": "USD"},
        }
        job = user.create_job(agreement)
        user.sign_agreement(job.job_id, job.agreement_hash)
        merchant.sign_agreement(job.job_id, job.agreement_hash)
        user.lock_fee(job.job_id, job.agreement_hash)

        # UW request (from merchant = business agent)
        merchant.request_uw(job.job_id, job.agreement_hash)

        # UW decides
        uw_resp = underwriter.uw_decide(
            job.job_id, job.agreement_hash, approve=True, premium=50,
        )
        assert uw_resp.principal_track_state == "PREMIUM_PENDING"

        # User pays premium
        user.pay_premium(job.job_id, job.agreement_hash, "premium_ref_123")

        # Check state
        state = user.get_job(job.job_id)
        assert state["principal_track_state"] == "APPROVAL_PENDING"
