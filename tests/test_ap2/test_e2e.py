"""End-to-end tests for AP2-ARS server."""

from __future__ import annotations

import pytest

from .conftest import (
    make_ap2_agreement_dict,
    make_ap2_create_request,
    make_ap2_envelope,
    make_cart_mandate_payload,
    make_fund_moving_ap2_agreement_dict,
    make_intent_mandate_payload,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _create_job(
    client,
    user_sk,
    user_pk,
    agent_pk,
    eval_pk,
    cred_pk,
    merchant_pk,
    processor_pk,
    **kw,
):
    agr = make_ap2_agreement_dict(
        user_pk, agent_pk, eval_pk, cred_pk, merchant_pk, processor_pk, **kw
    )
    req = make_ap2_create_request({"agreement": agr}, user_sk)
    r = client.post("/jobs", json=req)
    assert r.status_code == 201, r.text
    return r.json()["job_id"], r.json()["agreement_hash"]


def _sign_both(client, job_id, agr_hash, user_sk, agent_sk):
    for sk in (user_sk, agent_sk):
        env = make_ap2_envelope("AGREEMENT_SIGNED", job_id, agr_hash, {}, sk)
        r = client.post(f"/jobs/{job_id}/signatures", json=env)
        assert r.status_code == 200, r.text


def _lock_fee(client, job_id, agr_hash, user_sk):
    env = make_ap2_envelope("FEE_ESCROW_LOCKED", job_id, agr_hash, {}, user_sk)
    r = client.post(f"/jobs/{job_id}/fee/lock", json=env)
    assert r.status_code == 200, r.text
    return r.json()


def _submit_deliverable(client, job_id, agr_hash, agent_sk):
    env = make_ap2_envelope(
        "DELIVERABLE_SUBMITTED",
        job_id,
        agr_hash,
        {"deliverable_ref": "ipfs://deliverable123"},
        agent_sk,
    )
    r = client.post(f"/jobs/{job_id}/deliverable", json=env)
    assert r.status_code == 200, r.text


def _evaluate(client, job_id, agr_hash, eval_sk, verdict="pass"):
    env = make_ap2_envelope(
        "OUTCOME_EVALUATED", job_id, agr_hash, {"verdict": verdict}, eval_sk,
    )
    r = client.post(f"/jobs/{job_id}/evaluate", json=env)
    assert r.status_code == 200, r.text


def _settle_fee(client, job_id, agr_hash, user_sk, action="release"):
    env = make_ap2_envelope(
        "FEE_SETTLED", job_id, agr_hash, {"action": action}, user_sk,
    )
    r = client.post(f"/jobs/{job_id}/fee/settle", json=env)
    assert r.status_code == 200, r.text
    return r.json()


# ── Fee track happy path ─────────────────────────────────────────────────────


class TestFeeTrack:
    def test_happy_path_pass_release(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        processor_keys,
    ):
        user_sk, user_pk = user_keys
        agent_sk, agent_pk = agent_keys
        eval_sk, eval_pk = evaluator_keys
        _, cred_pk = cred_provider_keys
        _, merchant_pk = merchant_keys
        _, processor_pk = processor_keys

        job_id, agr_hash = _create_job(
            client,
            user_sk,
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk,
            merchant_pk,
            processor_pk,
        )
        _sign_both(client, job_id, agr_hash, user_sk, agent_sk)
        lock = _lock_fee(client, job_id, agr_hash, user_sk)
        assert "lock_ref" in lock

        _submit_deliverable(client, job_id, agr_hash, agent_sk)
        _evaluate(client, job_id, agr_hash, eval_sk, "pass")
        result = _settle_fee(client, job_id, agr_hash, user_sk, "release")
        assert result["phase"] == "CLOSED"
        assert result["fee_track_state"] == "FEE_SETTLED_RELEASE"

    def test_unhappy_path_fail_refund(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        processor_keys,
    ):
        user_sk, user_pk = user_keys
        agent_sk, agent_pk = agent_keys
        eval_sk, eval_pk = evaluator_keys
        _, cred_pk = cred_provider_keys
        _, merchant_pk = merchant_keys
        _, processor_pk = processor_keys

        job_id, agr_hash = _create_job(
            client,
            user_sk,
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk,
            merchant_pk,
            processor_pk,
        )
        _sign_both(client, job_id, agr_hash, user_sk, agent_sk)
        _lock_fee(client, job_id, agr_hash, user_sk)
        _submit_deliverable(client, job_id, agr_hash, agent_sk)
        _evaluate(client, job_id, agr_hash, eval_sk, "fail")
        result = _settle_fee(client, job_id, agr_hash, user_sk, "refund")
        assert result["phase"] == "CLOSED"
        assert result["fee_track_state"] == "FEE_SETTLED_REFUND"


# ── Mandate track: human-present ──────────────────────────────────────────────


class TestMandateHumanPresent:
    def test_full_mandate_flow(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        processor_keys,
    ):
        user_sk, user_pk = user_keys
        agent_sk, agent_pk = agent_keys
        _, eval_pk = evaluator_keys
        cred_sk, cred_pk = cred_provider_keys
        merchant_sk, merchant_pk = merchant_keys
        processor_sk, processor_pk = processor_keys

        # Create job
        job_id, agr_hash = _create_job(
            client,
            user_sk,
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk,
            merchant_pk,
            processor_pk,
            modality="human-present",
        )
        _sign_both(client, job_id, agr_hash, user_sk, agent_sk)

        # Intent mandate
        intent_payload = make_intent_mandate_payload(
            user_pk, job_id, budget=5000, allowed_merchants=[merchant_pk],
        )
        env = make_ap2_envelope(
            "INTENT_MANDATE_CREATED", job_id, agr_hash, intent_payload, user_sk,
        )
        r = client.post(f"/jobs/{job_id}/mandates/intent", json=env)
        assert r.status_code == 200
        assert r.json()["mandate_track_state"] == "INTENT_CREATED"

        # Cart mandate proposed
        cart_payload = make_cart_mandate_payload(merchant_pk, job_id, total=2000)
        env = make_ap2_envelope(
            "CART_MANDATE_PROPOSED", job_id, agr_hash, cart_payload, merchant_sk,
        )
        r = client.post(f"/jobs/{job_id}/mandates/cart", json=env)
        assert r.status_code == 200
        assert r.json()["mandate_track_state"] == "CART_PROPOSED"

        # Cart signed by merchant
        env = make_ap2_envelope(
            "CART_MANDATE_SIGNED", job_id, agr_hash, {}, merchant_sk,
        )
        r = client.post(f"/jobs/{job_id}/mandates/cart/sign", json=env)
        assert r.status_code == 200
        assert r.json()["mandate_track_state"] == "CART_SIGNED"

        # Cart approved by user (human-present)
        env = make_ap2_envelope("CART_APPROVED_BY_USER", job_id, agr_hash, {}, user_sk,)
        r = client.post(f"/jobs/{job_id}/mandates/cart/approve", json=env)
        assert r.status_code == 200
        assert r.json()["mandate_track_state"] == "CART_APPROVED"

        # Payment mandate created by credentials provider
        env = make_ap2_envelope(
            "PAYMENT_MANDATE_CREATED",
            job_id,
            agr_hash,
            {"payment_token_hash": "hash_xyz"},
            cred_sk,
        )
        r = client.post(f"/jobs/{job_id}/mandates/payment", json=env)
        assert r.status_code == 200
        assert r.json()["mandate_track_state"] == "PAYMENT_CREATED"

        # Payment signed by user
        env = make_ap2_envelope(
            "PAYMENT_MANDATE_SIGNED", job_id, agr_hash, {}, user_sk,
        )
        r = client.post(f"/jobs/{job_id}/mandates/payment/sign", json=env)
        assert r.status_code == 200
        assert r.json()["mandate_track_state"] == "PAYMENT_SIGNED"

        # x402 initiate
        env = make_ap2_envelope(
            "SETTLEMENT_402_INITIATED",
            job_id,
            agr_hash,
            {"payment_payload": {}, "payment_requirement": {}},
            processor_sk,
        )
        r = client.post(f"/jobs/{job_id}/settlement/x402/initiate", json=env)
        assert r.status_code == 200
        assert r.json()["mandate_track_state"] == "SETTLEMENT_INITIATED"
        assert "x402_transaction" in r.json()

        # x402 confirm
        env = make_ap2_envelope(
            "SETTLEMENT_402_CONFIRMED", job_id, agr_hash, {}, processor_sk,
        )
        r = client.post(f"/jobs/{job_id}/settlement/x402/confirm", json=env)
        assert r.status_code == 200
        assert r.json()["mandate_track_state"] == "SETTLEMENT_CONFIRMED"
        assert "x402_settlement_ref" in r.json()


# ── Mandate track: human-NOT-present ──────────────────────────────────────────


class TestMandateHumanNotPresent:
    def test_autonomous_flow_with_constraint_check(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        processor_keys,
    ):
        user_sk, user_pk = user_keys
        agent_sk, agent_pk = agent_keys
        _, eval_pk = evaluator_keys
        cred_sk, cred_pk = cred_provider_keys
        merchant_sk, merchant_pk = merchant_keys
        processor_sk, processor_pk = processor_keys

        # Create with human-not-present modality
        job_id, agr_hash = _create_job(
            client,
            user_sk,
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk,
            merchant_pk,
            processor_pk,
            modality="human-not-present",
        )
        _sign_both(client, job_id, agr_hash, user_sk, agent_sk)

        # Intent mandate
        intent_payload = make_intent_mandate_payload(
            user_pk, job_id, budget=5000, allowed_merchants=[merchant_pk],
        )
        env = make_ap2_envelope(
            "INTENT_MANDATE_CREATED", job_id, agr_hash, intent_payload, user_sk,
        )
        r = client.post(f"/jobs/{job_id}/mandates/intent", json=env)
        assert r.status_code == 200

        # Cart proposed
        cart_payload = make_cart_mandate_payload(merchant_pk, job_id, total=2000)
        env = make_ap2_envelope(
            "CART_MANDATE_PROPOSED", job_id, agr_hash, cart_payload, merchant_sk,
        )
        r = client.post(f"/jobs/{job_id}/mandates/cart", json=env)
        assert r.status_code == 200

        # Cart signed — should include constraint check
        env = make_ap2_envelope(
            "CART_MANDATE_SIGNED", job_id, agr_hash, {}, merchant_sk,
        )
        r = client.post(f"/jobs/{job_id}/mandates/cart/sign", json=env)
        assert r.status_code == 200
        assert r.json()["mandate_track_state"] == "CART_SIGNED"
        assert r.json().get("constraint_check", {}).get("allowed") is True

        # Skip CART_APPROVED — go directly to payment (human-not-present)
        env = make_ap2_envelope(
            "PAYMENT_MANDATE_CREATED",
            job_id,
            agr_hash,
            {"payment_token_hash": "hash_auto"},
            cred_sk,
        )
        r = client.post(f"/jobs/{job_id}/mandates/payment", json=env)
        assert r.status_code == 200

        # Credentials provider auto-signs in not-present mode
        env = make_ap2_envelope(
            "PAYMENT_MANDATE_SIGNED", job_id, agr_hash, {}, cred_sk,
        )
        r = client.post(f"/jobs/{job_id}/mandates/payment/sign", json=env)
        assert r.status_code == 200

        # Settlement
        env = make_ap2_envelope(
            "SETTLEMENT_402_INITIATED",
            job_id,
            agr_hash,
            {"payment_payload": {}, "payment_requirement": {}},
            processor_sk,
        )
        r = client.post(f"/jobs/{job_id}/settlement/x402/initiate", json=env)
        assert r.status_code == 200

        env = make_ap2_envelope(
            "SETTLEMENT_402_CONFIRMED", job_id, agr_hash, {}, processor_sk,
        )
        r = client.post(f"/jobs/{job_id}/settlement/x402/confirm", json=env)
        assert r.status_code == 200
        assert r.json()["mandate_track_state"] == "SETTLEMENT_CONFIRMED"


# ── Firewall enforcement ─────────────────────────────────────────────────────


class TestFirewall:
    def test_agent_equals_credentials_provider_rejected(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        merchant_keys,
        processor_keys,
    ):
        user_sk, user_pk = user_keys
        _, agent_pk = agent_keys
        _, eval_pk = evaluator_keys
        _, merchant_pk = merchant_keys
        _, processor_pk = processor_keys

        # Use agent key as credentials provider key — should fail
        agr = make_ap2_agreement_dict(
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk=agent_pk,  # SAME as agent
            merchant_pk=merchant_pk,
            processor_pk=processor_pk,
        )
        req = make_ap2_create_request({"agreement": agr}, user_sk)
        r = client.post("/jobs", json=req)
        assert r.status_code == 400
        assert "firewall" in r.json()["detail"].lower()


# ── Guardrails ────────────────────────────────────────────────────────────────


class TestGuardrails:
    def test_cart_approval_rejected_in_not_present_mode(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        processor_keys,
    ):
        """CART_APPROVED_BY_USER should be rejected in human-not-present mode."""
        user_sk, user_pk = user_keys
        agent_sk, agent_pk = agent_keys
        _, eval_pk = evaluator_keys
        _, cred_pk = cred_provider_keys
        merchant_sk, merchant_pk = merchant_keys
        _, processor_pk = processor_keys

        job_id, agr_hash = _create_job(
            client,
            user_sk,
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk,
            merchant_pk,
            processor_pk,
            modality="human-not-present",
        )
        _sign_both(client, job_id, agr_hash, user_sk, agent_sk)

        # Create intent + cart + sign
        intent = make_intent_mandate_payload(
            user_pk, job_id, budget=5000, allowed_merchants=[merchant_pk]
        )
        env = make_ap2_envelope(
            "INTENT_MANDATE_CREATED", job_id, agr_hash, intent, user_sk
        )
        client.post(f"/jobs/{job_id}/mandates/intent", json=env)

        cart = make_cart_mandate_payload(merchant_pk, job_id)
        env = make_ap2_envelope(
            "CART_MANDATE_PROPOSED", job_id, agr_hash, cart, merchant_sk
        )
        client.post(f"/jobs/{job_id}/mandates/cart", json=env)

        env = make_ap2_envelope(
            "CART_MANDATE_SIGNED", job_id, agr_hash, {}, merchant_sk
        )
        client.post(f"/jobs/{job_id}/mandates/cart/sign", json=env)

        # Try to approve cart in not-present mode — should fail
        env = make_ap2_envelope("CART_APPROVED_BY_USER", job_id, agr_hash, {}, user_sk)
        r = client.post(f"/jobs/{job_id}/mandates/cart/approve", json=env)
        assert r.status_code == 409
        assert "human-present" in r.json()["detail"].lower()

    def test_nonexistent_job_404(self, client):
        r = client.get("/jobs/nonexistent-id")
        assert r.status_code == 404

    def test_get_job_state(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        processor_keys,
    ):
        user_sk, user_pk = user_keys
        _, agent_pk = agent_keys
        _, eval_pk = evaluator_keys
        _, cred_pk = cred_provider_keys
        _, merchant_pk = merchant_keys
        _, processor_pk = processor_keys

        job_id, agr_hash = _create_job(
            client,
            user_sk,
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk,
            merchant_pk,
            processor_pk,
        )
        r = client.get(f"/jobs/{job_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["phase"] == "NEGOTIATION"
        assert data["modality"] == "human-present"
        assert data["mandate_track_state"] == "MANDATE_NONE"

    def test_get_events(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        processor_keys,
    ):
        user_sk, user_pk = user_keys
        _, agent_pk = agent_keys
        _, eval_pk = evaluator_keys
        _, cred_pk = cred_provider_keys
        _, merchant_pk = merchant_keys
        _, processor_pk = processor_keys

        job_id, agr_hash = _create_job(
            client,
            user_sk,
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk,
            merchant_pk,
            processor_pk,
        )
        r = client.get(f"/jobs/{job_id}/events")
        assert r.status_code == 200
        assert len(r.json()["events"]) == 1
        assert r.json()["events"][0]["event_type"] == "JOB_CREATED"

    def test_get_mandates_empty(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        processor_keys,
    ):
        user_sk, user_pk = user_keys
        _, agent_pk = agent_keys
        _, eval_pk = evaluator_keys
        _, cred_pk = cred_provider_keys
        _, merchant_pk = merchant_keys
        _, processor_pk = processor_keys

        job_id, _ = _create_job(
            client,
            user_sk,
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk,
            merchant_pk,
            processor_pk,
        )
        r = client.get(f"/jobs/{job_id}/mandates")
        assert r.status_code == 200
        assert r.json()["intent_mandate"] is None
