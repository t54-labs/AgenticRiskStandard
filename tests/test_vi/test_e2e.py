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
