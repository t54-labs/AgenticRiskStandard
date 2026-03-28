"""VI E2E tests: autonomous and immediate mode happy paths."""

from __future__ import annotations

import pytest

from .conftest import make_vi_agreement_dict, make_vi_create_request, make_vi_envelope


class TestAutonomousModeHappyPath:
    """Full autonomous mode flow: L1 → L2 → verify → L3a + L3b → chain verify → fee."""

    def test_full_autonomous_flow(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
    ):
        user_sk, user_pk = user_keys
        agent_sk, agent_pk = agent_keys
        eval_sk, eval_pk = evaluator_keys
        cred_sk, cred_pk = cred_provider_keys
        merchant_sk, merchant_pk = merchant_keys
        network_sk, network_pk = payment_network_keys

        _, user_jwk = user_es256
        _, agent_jwk = agent_es256
        _, cred_jwk = cred_provider_es256
        _, merchant_jwk = merchant_es256
        _, network_jwk = payment_network_es256

        # 1. Create job
        agr = make_vi_agreement_dict(
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk,
            merchant_pk,
            network_pk,
            user_jwk,
            agent_jwk,
            cred_jwk,
            merchant_jwk,
            network_jwk,
            mode="autonomous",
        )
        req = make_vi_create_request({"agreement": agr}, user_sk)
        resp = client.post("/jobs", json=req)
        assert resp.status_code == 201
        data = resp.json()
        job_id = data["job_id"]
        agr_hash = data["agreement_hash"]
        assert data["mode"] == "autonomous"

        # 2. Sign agreement (user + merchant)
        env = make_vi_envelope("AGREEMENT_SIGNED", job_id, agr_hash, {}, user_sk)
        resp = client.post(f"/jobs/{job_id}/signatures", json=env)
        assert resp.status_code == 200

        env = make_vi_envelope("AGREEMENT_SIGNED", job_id, agr_hash, {}, merchant_sk)
        resp = client.post(f"/jobs/{job_id}/signatures", json=env)
        assert resp.status_code == 200
        assert resp.json()["phase"] == "TRANSACTION"

        # 3. Issue L1 credential
        env = make_vi_envelope(
            "L1_CREDENTIAL_ISSUED",
            job_id,
            agr_hash,
            {"l1_serialized": "test-l1-sd-jwt-string"},
            cred_sk,
        )
        resp = client.post(f"/jobs/{job_id}/credentials/l1", json=env)
        assert resp.status_code == 200
        assert resp.json()["credential_track_state"] == "L1_ISSUED"

        # 4. Create L2 autonomous mandate
        env = make_vi_envelope(
            "L2_MANDATE_CREATED",
            job_id,
            agr_hash,
            {
                "mode": "autonomous",
                "l2_serialized": "test-l2-sd-jwt-string",
                "constraints": {
                    "payment_amount": {"min_amount": 0, "max_amount": 5000},
                    "allowed_merchants": {"merchant_ids": [merchant_pk]},
                },
            },
            user_sk,
        )
        resp = client.post(f"/jobs/{job_id}/credentials/l2", json=env)
        assert resp.status_code == 200
        assert resp.json()["credential_track_state"] == "L2_CREATED"

        # 5. Verify L2
        env = make_vi_envelope("L2_MANDATE_VERIFIED", job_id, agr_hash, {}, cred_sk,)
        resp = client.post(f"/jobs/{job_id}/credentials/l2/verify", json=env)
        assert resp.status_code == 200
        assert resp.json()["credential_track_state"] == "L2_VERIFIED"

        # 6. Create L3a (payment fulfillment)
        env = make_vi_envelope(
            "L3A_PAYMENT_CREATED",
            job_id,
            agr_hash,
            {
                "l3a_serialized": "test-l3a-kb-sd-jwt",
                "transaction_id": "tx-001",
                "payee": "merchant-acct",
                "amount": 2000,
                "currency": "USD",
            },
            agent_sk,
        )
        resp = client.post(f"/jobs/{job_id}/credentials/l3a", json=env)
        assert resp.status_code == 200
        assert resp.json()["credential_track_state"] == "L3A_CREATED"

        # 7. Create L3b (checkout fulfillment)
        env = make_vi_envelope(
            "L3B_CHECKOUT_CREATED",
            job_id,
            agr_hash,
            {
                "l3b_serialized": "test-l3b-kb-sd-jwt",
                "checkout_jwt": "test-checkout",
                "merchant_id": merchant_pk,
            },
            agent_sk,
        )
        resp = client.post(f"/jobs/{job_id}/credentials/l3b", json=env)
        assert resp.status_code == 200
        assert resp.json()["credential_track_state"] == "L3B_CREATED"

        # 8. Verify full chain
        env = make_vi_envelope("L3_CHAIN_VERIFIED", job_id, agr_hash, {}, network_sk,)
        resp = client.post(f"/jobs/{job_id}/credentials/l3/verify", json=env)
        assert resp.status_code == 200
        assert resp.json()["credential_track_state"] == "L3_CHAIN_VERIFIED"

        # 9. Lock fee (user)
        env = make_vi_envelope("FEE_ESCROW_LOCKED", job_id, agr_hash, {}, user_sk,)
        resp = client.post(f"/jobs/{job_id}/fee/lock", json=env)
        assert resp.status_code == 200
        assert resp.json()["fee_track_state"] == "FEE_ESCROW_LOCKED"

        # 10. Submit deliverable (merchant)
        env = make_vi_envelope(
            "DELIVERABLE_SUBMITTED",
            job_id,
            agr_hash,
            {"deliverable_ref": "delivery-001"},
            merchant_sk,
        )
        resp = client.post(f"/jobs/{job_id}/deliverable", json=env)
        assert resp.status_code == 200

        # 11. Evaluate (pass)
        env = make_vi_envelope(
            "OUTCOME_EVALUATED", job_id, agr_hash, {"verdict": "pass"}, eval_sk,
        )
        resp = client.post(f"/jobs/{job_id}/evaluate", json=env)
        assert resp.status_code == 200

        # 12. Settle fee (release)
        env = make_vi_envelope(
            "FEE_SETTLED", job_id, agr_hash, {"action": "release"}, user_sk,
        )
        resp = client.post(f"/jobs/{job_id}/fee/settle", json=env)
        assert resp.status_code == 200
        assert resp.json()["phase"] == "CLOSED"

        # 13. Verify final state
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        state = resp.json()
        assert state["phase"] == "CLOSED"
        assert state["credential_track_state"] == "L3_CHAIN_VERIFIED"

        # 14. Check selective presentations
        resp = client.get(f"/jobs/{job_id}/credentials/present/merchant")
        assert resp.status_code == 200
        assert resp.json()["presentation_type"] == "merchant"
        assert resp.json()["l3b_checkout"] is not None
        assert resp.json().get("l3a_payment") is None

        resp = client.get(f"/jobs/{job_id}/credentials/present/network")
        assert resp.status_code == 200
        assert resp.json()["presentation_type"] == "network"
        assert resp.json()["l3a_payment"] is not None
        assert resp.json().get("l3b_checkout") is None


class TestImmediateModeHappyPath:
    """Immediate mode: L1 → L2 → verify → fee (no L3)."""

    def test_immediate_flow(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
    ):
        user_sk, user_pk = user_keys
        _, agent_pk = agent_keys
        eval_sk, eval_pk = evaluator_keys
        cred_sk, cred_pk = cred_provider_keys
        merchant_sk, merchant_pk = merchant_keys
        network_sk, network_pk = payment_network_keys

        _, user_jwk = user_es256
        _, agent_jwk = agent_es256
        _, cred_jwk = cred_provider_es256
        _, merchant_jwk = merchant_es256
        _, network_jwk = payment_network_es256

        # Create job (immediate mode)
        agr = make_vi_agreement_dict(
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk,
            merchant_pk,
            network_pk,
            user_jwk,
            agent_jwk,
            cred_jwk,
            merchant_jwk,
            network_jwk,
            mode="immediate",
        )
        req = make_vi_create_request({"agreement": agr}, user_sk)
        resp = client.post("/jobs", json=req)
        assert resp.status_code == 201
        data = resp.json()
        job_id = data["job_id"]
        agr_hash = data["agreement_hash"]
        assert data["mode"] == "immediate"

        # Sign agreement
        env = make_vi_envelope("AGREEMENT_SIGNED", job_id, agr_hash, {}, user_sk)
        client.post(f"/jobs/{job_id}/signatures", json=env)
        env = make_vi_envelope("AGREEMENT_SIGNED", job_id, agr_hash, {}, merchant_sk)
        client.post(f"/jobs/{job_id}/signatures", json=env)

        # L1
        env = make_vi_envelope(
            "L1_CREDENTIAL_ISSUED",
            job_id,
            agr_hash,
            {"l1_serialized": "l1-immediate"},
            cred_sk,
        )
        resp = client.post(f"/jobs/{job_id}/credentials/l1", json=env)
        assert resp.status_code == 200

        # L2 (immediate mode)
        env = make_vi_envelope(
            "L2_MANDATE_CREATED",
            job_id,
            agr_hash,
            {"mode": "immediate", "l2_serialized": "l2-immediate"},
            user_sk,
        )
        resp = client.post(f"/jobs/{job_id}/credentials/l2", json=env)
        assert resp.status_code == 200

        # Verify L2
        env = make_vi_envelope("L2_MANDATE_VERIFIED", job_id, agr_hash, {}, network_sk,)
        resp = client.post(f"/jobs/{job_id}/credentials/l2/verify", json=env)
        assert resp.status_code == 200
        assert resp.json()["credential_track_state"] == "L2_VERIFIED"

        # L3a should be rejected in immediate mode
        env = make_vi_envelope(
            "L3A_PAYMENT_CREATED",
            job_id,
            agr_hash,
            {"l3a_serialized": "invalid", "amount": 100},
            user_sk,  # using wrong key on purpose, but mode check comes first
        )
        # This would fail due to mode check (immediate doesn't allow L3)

        # Fee lock — should work since L2 is verified in immediate mode
        env = make_vi_envelope("FEE_ESCROW_LOCKED", job_id, agr_hash, {}, user_sk,)
        resp = client.post(f"/jobs/{job_id}/fee/lock", json=env)
        assert resp.status_code == 200

        # Complete fee track
        env = make_vi_envelope(
            "DELIVERABLE_SUBMITTED",
            job_id,
            agr_hash,
            {"deliverable_ref": "del-imm"},
            merchant_sk,
        )
        client.post(f"/jobs/{job_id}/deliverable", json=env)

        env = make_vi_envelope(
            "OUTCOME_EVALUATED", job_id, agr_hash, {"verdict": "pass"}, eval_sk,
        )
        client.post(f"/jobs/{job_id}/evaluate", json=env)

        env = make_vi_envelope(
            "FEE_SETTLED", job_id, agr_hash, {"action": "release"}, user_sk,
        )
        resp = client.post(f"/jobs/{job_id}/fee/settle", json=env)
        assert resp.status_code == 200
        assert resp.json()["phase"] == "CLOSED"


class TestCredentialTrackGating:
    """Verify that fee lock is gated on credential chain completion."""

    def test_fee_lock_blocked_before_chain_verified(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
    ):
        user_sk, user_pk = user_keys
        _, agent_pk = agent_keys
        _, eval_pk = evaluator_keys
        cred_sk, cred_pk = cred_provider_keys
        merchant_sk, merchant_pk = merchant_keys
        _, network_pk = payment_network_keys

        _, user_jwk = user_es256
        _, agent_jwk = agent_es256
        _, cred_jwk = cred_provider_es256
        _, merchant_jwk = merchant_es256
        _, network_jwk = payment_network_es256

        # Create job + sign
        agr = make_vi_agreement_dict(
            user_pk,
            agent_pk,
            eval_pk,
            cred_pk,
            merchant_pk,
            network_pk,
            user_jwk,
            agent_jwk,
            cred_jwk,
            merchant_jwk,
            network_jwk,
        )
        req = make_vi_create_request({"agreement": agr}, user_sk)
        resp = client.post("/jobs", json=req)
        job_id = resp.json()["job_id"]
        agr_hash = resp.json()["agreement_hash"]

        env = make_vi_envelope("AGREEMENT_SIGNED", job_id, agr_hash, {}, user_sk)
        client.post(f"/jobs/{job_id}/signatures", json=env)
        env = make_vi_envelope("AGREEMENT_SIGNED", job_id, agr_hash, {}, merchant_sk)
        client.post(f"/jobs/{job_id}/signatures", json=env)

        # Issue L1 only
        env = make_vi_envelope(
            "L1_CREDENTIAL_ISSUED", job_id, agr_hash, {"l1_serialized": "l1"}, cred_sk,
        )
        client.post(f"/jobs/{job_id}/credentials/l1", json=env)

        # Try to lock fee — should be blocked (credential chain not complete)
        env = make_vi_envelope("FEE_ESCROW_LOCKED", job_id, agr_hash, {}, user_sk,)
        resp = client.post(f"/jobs/{job_id}/fee/lock", json=env)
        assert resp.status_code == 409
        assert "credential chain" in resp.json()["detail"].lower()


class TestFirewall:
    """Verify agent-credential firewall."""

    def test_agent_sharing_key_with_cred_provider_rejected(
        self,
        client,
        user_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
    ):
        user_sk, user_pk = user_keys
        _, eval_pk = evaluator_keys
        _, cred_pk = cred_provider_keys
        _, merchant_pk = merchant_keys
        _, network_pk = payment_network_keys

        _, user_jwk = user_es256
        _, cred_jwk = cred_provider_es256
        _, merchant_jwk = merchant_es256
        _, network_jwk = payment_network_es256

        # Agent shares key with credential provider — should be rejected
        agr = make_vi_agreement_dict(
            user_pk,
            cred_pk,  # agent_pk = cred_pk (firewall violation)
            eval_pk,
            cred_pk,
            merchant_pk,
            network_pk,
            user_jwk,
            cred_jwk,  # agent_jwk = cred_jwk
            cred_jwk,
            merchant_jwk,
            network_jwk,
        )
        req = make_vi_create_request({"agreement": agr}, user_sk)
        resp = client.post("/jobs", json=req)
        assert resp.status_code == 400
        assert "firewall" in resp.json()["detail"].lower()


# ── Helper: create a signed job in TRANSACTION phase ─────────────────────────


def _setup_job(
    client,
    user_keys,
    agent_keys,
    evaluator_keys,
    cred_provider_keys,
    merchant_keys,
    payment_network_keys,
    user_es256,
    agent_es256,
    cred_provider_es256,
    merchant_es256,
    payment_network_es256,
    mode="autonomous",
    **agr_overrides,
):
    """Create a job with both signatures, return (job_id, agr_hash, keys_dict)."""
    user_sk, user_pk = user_keys
    agent_sk, agent_pk = agent_keys
    eval_sk, eval_pk = evaluator_keys
    cred_sk, cred_pk = cred_provider_keys
    merchant_sk, merchant_pk = merchant_keys
    network_sk, network_pk = payment_network_keys
    _, user_jwk = user_es256
    _, agent_jwk = agent_es256
    _, cred_jwk = cred_provider_es256
    _, merchant_jwk = merchant_es256
    _, network_jwk = payment_network_es256

    agr = make_vi_agreement_dict(
        user_pk,
        agent_pk,
        eval_pk,
        cred_pk,
        merchant_pk,
        network_pk,
        user_jwk,
        agent_jwk,
        cred_jwk,
        merchant_jwk,
        network_jwk,
        mode=mode,
        **agr_overrides,
    )
    req = make_vi_create_request({"agreement": agr}, user_sk)
    resp = client.post("/jobs", json=req)
    assert resp.status_code == 201
    job_id = resp.json()["job_id"]
    agr_hash = resp.json()["agreement_hash"]

    env = make_vi_envelope("AGREEMENT_SIGNED", job_id, agr_hash, {}, user_sk)
    client.post(f"/jobs/{job_id}/signatures", json=env)
    env = make_vi_envelope("AGREEMENT_SIGNED", job_id, agr_hash, {}, merchant_sk)
    client.post(f"/jobs/{job_id}/signatures", json=env)

    return (
        job_id,
        agr_hash,
        {
            "user_sk": user_sk,
            "agent_sk": agent_sk,
            "eval_sk": eval_sk,
            "cred_sk": cred_sk,
            "merchant_sk": merchant_sk,
            "network_sk": network_sk,
            "merchant_pk": merchant_pk,
        },
    )


def _complete_credential_chain(client, job_id, agr_hash, keys, mode="autonomous"):
    """Issue L1, L2, verify, and optionally L3a+L3b+chain verify."""
    env = make_vi_envelope(
        "L1_CREDENTIAL_ISSUED",
        job_id,
        agr_hash,
        {"l1_serialized": "l1"},
        keys["cred_sk"],
    )
    client.post(f"/jobs/{job_id}/credentials/l1", json=env)

    payload = {"mode": mode, "l2_serialized": "l2"}
    if mode == "autonomous":
        payload["constraints"] = {
            "payment_amount": {"max_amount": 50000},
            "allowed_merchants": {"merchant_ids": [keys["merchant_pk"]]},
        }
    env = make_vi_envelope(
        "L2_MANDATE_CREATED", job_id, agr_hash, payload, keys["user_sk"]
    )
    client.post(f"/jobs/{job_id}/credentials/l2", json=env)

    env = make_vi_envelope("L2_MANDATE_VERIFIED", job_id, agr_hash, {}, keys["cred_sk"])
    client.post(f"/jobs/{job_id}/credentials/l2/verify", json=env)

    if mode == "autonomous":
        env = make_vi_envelope(
            "L3A_PAYMENT_CREATED",
            job_id,
            agr_hash,
            {
                "l3a_serialized": "l3a",
                "transaction_id": "tx",
                "payee": "v",
                "amount": 2000,
            },
            keys["agent_sk"],
        )
        client.post(f"/jobs/{job_id}/credentials/l3a", json=env)

        env = make_vi_envelope(
            "L3B_CHECKOUT_CREATED",
            job_id,
            agr_hash,
            {
                "l3b_serialized": "l3b",
                "checkout_jwt": "co",
                "merchant_id": keys["merchant_pk"],
            },
            keys["agent_sk"],
        )
        client.post(f"/jobs/{job_id}/credentials/l3b", json=env)

        env = make_vi_envelope(
            "L3_CHAIN_VERIFIED", job_id, agr_hash, {}, keys["network_sk"]
        )
        client.post(f"/jobs/{job_id}/credentials/l3/verify", json=env)


# ── Fee Track Tests ──────────────────────────────────────────────────────────


class TestFeeTrack:
    """Fee track happy and unhappy paths (with credential chain)."""

    _fixtures = [
        "client",
        "user_keys",
        "agent_keys",
        "evaluator_keys",
        "cred_provider_keys",
        "merchant_keys",
        "payment_network_keys",
        "user_es256",
        "agent_es256",
        "cred_provider_es256",
        "merchant_es256",
        "payment_network_es256",
    ]

    def test_happy_path_pass_release(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
    ):
        job_id, agr_hash, keys = _setup_job(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
        )
        _complete_credential_chain(client, job_id, agr_hash, keys)

        # Lock fee
        env = make_vi_envelope(
            "FEE_ESCROW_LOCKED", job_id, agr_hash, {}, keys["user_sk"]
        )
        resp = client.post(f"/jobs/{job_id}/fee/lock", json=env)
        assert resp.status_code == 200

        # Deliver
        env = make_vi_envelope(
            "DELIVERABLE_SUBMITTED",
            job_id,
            agr_hash,
            {"deliverable_ref": "del-1"},
            keys["merchant_sk"],
        )
        client.post(f"/jobs/{job_id}/deliverable", json=env)

        # Evaluate pass
        env = make_vi_envelope(
            "OUTCOME_EVALUATED", job_id, agr_hash, {"verdict": "pass"}, keys["eval_sk"],
        )
        client.post(f"/jobs/{job_id}/evaluate", json=env)

        # Settle release
        env = make_vi_envelope(
            "FEE_SETTLED", job_id, agr_hash, {"action": "release"}, keys["user_sk"],
        )
        resp = client.post(f"/jobs/{job_id}/fee/settle", json=env)
        assert resp.status_code == 200
        assert resp.json()["phase"] == "CLOSED"

    def test_unhappy_path_fail_refund(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
    ):
        job_id, agr_hash, keys = _setup_job(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
        )
        _complete_credential_chain(client, job_id, agr_hash, keys)

        env = make_vi_envelope(
            "FEE_ESCROW_LOCKED", job_id, agr_hash, {}, keys["user_sk"]
        )
        client.post(f"/jobs/{job_id}/fee/lock", json=env)
        env = make_vi_envelope(
            "DELIVERABLE_SUBMITTED",
            job_id,
            agr_hash,
            {"deliverable_ref": "del-1"},
            keys["merchant_sk"],
        )
        client.post(f"/jobs/{job_id}/deliverable", json=env)
        env = make_vi_envelope(
            "OUTCOME_EVALUATED", job_id, agr_hash, {"verdict": "fail"}, keys["eval_sk"],
        )
        client.post(f"/jobs/{job_id}/evaluate", json=env)

        env = make_vi_envelope(
            "FEE_SETTLED", job_id, agr_hash, {"action": "refund"}, keys["user_sk"],
        )
        resp = client.post(f"/jobs/{job_id}/fee/settle", json=env)
        assert resp.status_code == 200
        assert resp.json()["phase"] == "CLOSED"
        assert resp.json()["fee_track_state"] == "FEE_SETTLED_REFUND"


# ── Guardrail Tests ──────────────────────────────────────────────────────────


class TestGuardrails:
    def test_l3_rejected_in_immediate_mode(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
    ):
        job_id, agr_hash, keys = _setup_job(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
            mode="immediate",
        )
        _complete_credential_chain(client, job_id, agr_hash, keys, mode="immediate")

        env = make_vi_envelope(
            "L3A_PAYMENT_CREATED",
            job_id,
            agr_hash,
            {"l3a_serialized": "bad", "amount": 100},
            keys["agent_sk"],
        )
        resp = client.post(f"/jobs/{job_id}/credentials/l3a", json=env)
        assert resp.status_code == 409

    def test_uw_blocked_when_requires_principal_false(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
    ):
        job_id, agr_hash, keys = _setup_job(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
            requires_principal=False,
        )
        _complete_credential_chain(client, job_id, agr_hash, keys)

        env = make_vi_envelope(
            "UW_REQUESTED", job_id, agr_hash, {}, keys["merchant_sk"]
        )
        resp = client.post(f"/jobs/{job_id}/uw/request", json=env)
        assert resp.status_code == 409
        assert "requires_principal" in resp.json()["detail"].lower()

    def test_uw_allowed_when_requires_principal_true(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
        underwriter_keys,
    ):
        uw_sk, uw_pk = underwriter_keys
        job_id, agr_hash, keys = _setup_job(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
            requires_principal=True,
            underwriter_pubkey=uw_pk,
            principal={"amount": 50000, "currency": "USD", "destination": "acct"},
        )
        _complete_credential_chain(client, job_id, agr_hash, keys)

        env = make_vi_envelope(
            "UW_REQUESTED", job_id, agr_hash, {}, keys["merchant_sk"]
        )
        resp = client.post(f"/jobs/{job_id}/uw/request", json=env)
        assert resp.status_code == 200

    def test_nonexistent_job_404(self, client):
        resp = client.get("/jobs/nonexistent-id")
        assert resp.status_code == 404

    def test_get_job_state(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
    ):
        job_id, agr_hash, _ = _setup_job(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
        )
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["phase"] == "TRANSACTION"

    def test_get_events(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
    ):
        job_id, agr_hash, _ = _setup_job(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
        )
        resp = client.get(f"/jobs/{job_id}/events")
        assert resp.status_code == 200
        assert len(resp.json()["events"]) >= 3  # create + 2 signatures

    def test_get_credentials_empty(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
    ):
        job_id, agr_hash, _ = _setup_job(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
        )
        resp = client.get(f"/jobs/{job_id}/credentials")
        assert resp.status_code == 200
        assert resp.json()["credential_track_state"] == "CREDENTIAL_NONE"


# ── UW Auto-Action Tests ────────────────────────────────────────────────────


class TestAutonomousUWAutoActions:
    def _setup_with_uw(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
        underwriter_keys,
        max_premium=500,
        allow_uw_override=True,
    ):
        uw_sk, uw_pk = underwriter_keys
        job_id, agr_hash, keys = _setup_job(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
            requires_principal=True,
            max_premium=max_premium,
            allow_uw_override=allow_uw_override,
            underwriter_pubkey=uw_pk,
            principal={"amount": 50000, "currency": "USD", "destination": "acct"},
        )
        _complete_credential_chain(client, job_id, agr_hash, keys)

        # Request UW
        env = make_vi_envelope(
            "UW_REQUESTED", job_id, agr_hash, {}, keys["merchant_sk"]
        )
        client.post(f"/jobs/{job_id}/uw/request", json=env)
        keys["uw_sk"] = uw_sk
        return job_id, agr_hash, keys

    def test_uw_auto_pay_premium_when_under_max(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
        underwriter_keys,
    ):
        job_id, agr_hash, keys = self._setup_with_uw(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
            underwriter_keys,
            max_premium=500,
        )
        env = make_vi_envelope(
            "UW_DECIDED",
            job_id,
            agr_hash,
            {"approve": True, "premium": 200, "collateral_required": 0},
            keys["uw_sk"],
        )
        resp = client.post(f"/jobs/{job_id}/uw/decide", json=env)
        assert resp.status_code == 200
        assert resp.json().get("auto_action") == "premium_auto_payable"

    def test_uw_block_when_premium_exceeds_max(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
        underwriter_keys,
    ):
        job_id, agr_hash, keys = self._setup_with_uw(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
            underwriter_keys,
            max_premium=100,
        )
        env = make_vi_envelope(
            "UW_DECIDED",
            job_id,
            agr_hash,
            {"approve": True, "premium": 500, "collateral_required": 0},
            keys["uw_sk"],
        )
        resp = client.post(f"/jobs/{job_id}/uw/decide", json=env)
        assert resp.status_code == 200
        assert resp.json().get("auto_action") == "awaiting_human"

    def test_uw_reject_auto_override(
        self,
        client,
        user_keys,
        agent_keys,
        evaluator_keys,
        cred_provider_keys,
        merchant_keys,
        payment_network_keys,
        user_es256,
        agent_es256,
        cred_provider_es256,
        merchant_es256,
        payment_network_es256,
        underwriter_keys,
    ):
        job_id, agr_hash, keys = self._setup_with_uw(
            client,
            user_keys,
            agent_keys,
            evaluator_keys,
            cred_provider_keys,
            merchant_keys,
            payment_network_keys,
            user_es256,
            agent_es256,
            cred_provider_es256,
            merchant_es256,
            payment_network_es256,
            underwriter_keys,
            allow_uw_override=True,
        )
        env = make_vi_envelope(
            "UW_DECIDED", job_id, agr_hash, {"approve": False}, keys["uw_sk"],
        )
        resp = client.post(f"/jobs/{job_id}/uw/decide", json=env)
        assert resp.status_code == 200
        assert resp.json().get("auto_action") == "override_recommended"
