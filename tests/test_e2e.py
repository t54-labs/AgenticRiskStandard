"""End-to-end tests for ARS v1."""

from __future__ import annotations

from nacl.signing import SigningKey

from ars.crypto import compute_agreement_hash
from ars.models import EventType

from .conftest import (
    make_agreement_dict,
    make_create_request,
    make_envelope,
    make_fund_moving_agreement_dict,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _create_job(client, req_sk, req_pk, agent_pk, eval_pk):
    """Create a job and return (job_id, agreement_hash, agreement_dict)."""
    agr = make_agreement_dict(req_pk, agent_pk, eval_pk)
    req = make_create_request({"agreement": agr}, req_sk)
    resp = client.post("/jobs", json=req)
    assert resp.status_code == 201, resp.json()
    data = resp.json()
    return data["job_id"], data["agreement_hash"], agr


def _sign_both(client, job_id, agr_hash, req_sk, agent_sk):
    """Sign agreement with both requestor and business agent."""
    for sk in (req_sk, agent_sk):
        env = make_envelope(EventType.AGREEMENT_SIGNED, job_id, agr_hash, {}, sk)
        resp = client.post(f"/jobs/{job_id}/signatures", json=env)
        assert resp.status_code == 200, resp.json()
    return resp.json()


def _lock_fee(client, job_id, agr_hash, req_sk):
    env = make_envelope(EventType.FEE_ESCROW_LOCKED, job_id, agr_hash, {}, req_sk)
    resp = client.post(f"/jobs/{job_id}/fee/lock", json=env)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def _submit_deliverable(client, job_id, agr_hash, agent_sk, ref="artifact://hash123"):
    env = make_envelope(
        EventType.DELIVERABLE_SUBMITTED,
        job_id,
        agr_hash,
        {"deliverable_ref": ref},
        agent_sk,
    )
    resp = client.post(f"/jobs/{job_id}/deliverable", json=env)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def _evaluate(client, job_id, agr_hash, eval_sk, verdict="pass"):
    env = make_envelope(
        EventType.OUTCOME_EVALUATED,
        job_id,
        agr_hash,
        {"verdict": verdict, "evidence_ref": "evidence://abc"},
        eval_sk,
    )
    resp = client.post(f"/jobs/{job_id}/evaluate", json=env)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def _settle(client, job_id, agr_hash, req_sk, action="release"):
    env = make_envelope(
        EventType.FEE_SETTLED, job_id, agr_hash, {"action": action}, req_sk,
    )
    resp = client.post(f"/jobs/{job_id}/fee/settle", json=env)
    return resp


# ── Happy path ───────────────────────────────────────────────────────────────


def test_happy_path_pass_release(client, requestor_keys, agent_keys, evaluator_keys):
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    eval_sk, eval_pk = evaluator_keys

    # 1. Create job
    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)

    # 2. Both sign
    sign_resp = _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    assert sign_resp["phase"] == "TRANSACTION"

    # 3. Lock fee
    lock_resp = _lock_fee(client, job_id, agr_hash, req_sk)
    assert lock_resp["fee_track_state"] == "FEE_ESCROW_LOCKED"
    assert "lock_ref" in lock_resp

    # 4. Submit deliverable
    deliv_resp = _submit_deliverable(client, job_id, agr_hash, agent_sk)
    assert deliv_resp["fee_track_state"] == "FEE_DELIVERED"

    # 5. Evaluate pass
    eval_resp = _evaluate(client, job_id, agr_hash, eval_sk, "pass")
    assert eval_resp["phase"] == "EVALUATION"
    assert eval_resp["verdict"] == "pass"

    # 6. Settle release
    settle_resp = _settle(client, job_id, agr_hash, req_sk, "release")
    assert settle_resp.status_code == 200
    data = settle_resp.json()
    assert data["phase"] == "CLOSED"
    assert data["fee_track_state"] == "FEE_SETTLED_RELEASE"
    assert "settlement_ref" in data

    # 7. Verify final state via GET
    state = client.get(f"/jobs/{job_id}").json()
    assert state["phase"] == "CLOSED"
    assert state["fee_track_state"] == "FEE_SETTLED_RELEASE"
    assert (
        state["event_count"] == 7
    )  # created + 2 sigs + lock + deliverable + eval + settle

    # 8. Verify event log
    events_resp = client.get(f"/jobs/{job_id}/events").json()
    assert len(events_resp["events"]) == 7
    types = [e["event_type"] for e in events_resp["events"]]
    assert types == [
        "JOB_CREATED",
        "AGREEMENT_SIGNED",
        "AGREEMENT_SIGNED",
        "FEE_ESCROW_LOCKED",
        "DELIVERABLE_SUBMITTED",
        "OUTCOME_EVALUATED",
        "FEE_SETTLED",
    ]


# ── Unhappy path ─────────────────────────────────────────────────────────────


def test_unhappy_path_fail_refund(client, requestor_keys, agent_keys, evaluator_keys):
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    eval_sk, eval_pk = evaluator_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)
    _submit_deliverable(client, job_id, agr_hash, agent_sk)

    # Evaluate fail
    eval_resp = _evaluate(client, job_id, agr_hash, eval_sk, "fail")
    assert eval_resp["verdict"] == "fail"

    # Settle refund
    settle_resp = _settle(client, job_id, agr_hash, req_sk, "refund")
    assert settle_resp.status_code == 200
    data = settle_resp.json()
    assert data["phase"] == "CLOSED"
    assert data["fee_track_state"] == "FEE_SETTLED_REFUND"


# ── Guardrail tests ──────────────────────────────────────────────────────────


def test_cannot_lock_before_both_signatures(
    client, requestor_keys, agent_keys, evaluator_keys
):
    req_sk, req_pk = requestor_keys
    _, agent_pk = agent_keys
    _, eval_pk = evaluator_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)

    # Only requestor signs
    env = make_envelope(EventType.AGREEMENT_SIGNED, job_id, agr_hash, {}, req_sk)
    client.post(f"/jobs/{job_id}/signatures", json=env)

    # Try to lock fee — should fail (only 1 signature)
    env = make_envelope(EventType.FEE_ESCROW_LOCKED, job_id, agr_hash, {}, req_sk)
    resp = client.post(f"/jobs/{job_id}/fee/lock", json=env)
    assert resp.status_code == 409


def test_cannot_submit_deliverable_before_lock(
    client, requestor_keys, agent_keys, evaluator_keys
):
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    _, eval_pk = evaluator_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)

    # Skip lock, try deliverable
    env = make_envelope(
        EventType.DELIVERABLE_SUBMITTED,
        job_id,
        agr_hash,
        {"deliverable_ref": "x"},
        agent_sk,
    )
    resp = client.post(f"/jobs/{job_id}/deliverable", json=env)
    assert resp.status_code == 409


def test_cannot_evaluate_before_deliverable(
    client, requestor_keys, agent_keys, evaluator_keys
):
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    eval_sk, eval_pk = evaluator_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)

    # Skip deliverable, try evaluate
    env = make_envelope(
        EventType.OUTCOME_EVALUATED, job_id, agr_hash, {"verdict": "pass"}, eval_sk,
    )
    resp = client.post(f"/jobs/{job_id}/evaluate", json=env)
    assert resp.status_code == 409


def test_cannot_settle_twice(client, requestor_keys, agent_keys, evaluator_keys):
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    eval_sk, eval_pk = evaluator_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)
    _submit_deliverable(client, job_id, agr_hash, agent_sk)
    _evaluate(client, job_id, agr_hash, eval_sk, "pass")

    # First settle — should succeed
    resp1 = _settle(client, job_id, agr_hash, req_sk, "release")
    assert resp1.status_code == 200

    # Second settle — should fail
    resp2 = _settle(client, job_id, agr_hash, req_sk, "release")
    assert resp2.status_code == 409


def test_invalid_signature_rejected(client, requestor_keys, agent_keys, evaluator_keys):
    req_sk, req_pk = requestor_keys
    _, agent_pk = agent_keys
    _, eval_pk = evaluator_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)

    # Build valid envelope then tamper with signature
    env = make_envelope(EventType.AGREEMENT_SIGNED, job_id, agr_hash, {}, req_sk)
    env["signature"] = "00" * 64  # bogus 64-byte signature

    resp = client.post(f"/jobs/{job_id}/signatures", json=env)
    assert resp.status_code == 401


def test_wrong_role_rejected(client, requestor_keys, agent_keys, evaluator_keys):
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    eval_sk, eval_pk = evaluator_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)

    # Evaluator tries to lock fee (should be requestor only)
    env = make_envelope(EventType.FEE_ESCROW_LOCKED, job_id, agr_hash, {}, eval_sk)
    resp = client.post(f"/jobs/{job_id}/fee/lock", json=env)
    assert resp.status_code == 403


def test_agreement_hash_mismatch(client, requestor_keys, agent_keys, evaluator_keys):
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    _, eval_pk = evaluator_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)

    # Sign with a wrong agreement_hash
    wrong_hash = "0" * 64
    env = make_envelope(EventType.AGREEMENT_SIGNED, job_id, wrong_hash, {}, req_sk)
    resp = client.post(f"/jobs/{job_id}/signatures", json=env)
    assert resp.status_code == 400


def test_settle_action_must_match_verdict_pass(
    client, requestor_keys, agent_keys, evaluator_keys
):
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    eval_sk, eval_pk = evaluator_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)
    _submit_deliverable(client, job_id, agr_hash, agent_sk)
    _evaluate(client, job_id, agr_hash, eval_sk, "pass")

    # Try refund after pass — should fail
    resp = _settle(client, job_id, agr_hash, req_sk, "refund")
    assert resp.status_code == 400


def test_settle_action_must_match_verdict_fail(
    client, requestor_keys, agent_keys, evaluator_keys
):
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    eval_sk, eval_pk = evaluator_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)
    _submit_deliverable(client, job_id, agr_hash, agent_sk)
    _evaluate(client, job_id, agr_hash, eval_sk, "fail")

    # Try release after fail — should fail
    resp = _settle(client, job_id, agr_hash, req_sk, "release")
    assert resp.status_code == 400


def test_evaluator_cannot_propose_agreement(
    client, requestor_keys, agent_keys, evaluator_keys
):
    """Evaluator should not be able to submit agreement proposals."""
    req_sk, req_pk = requestor_keys
    eval_sk, eval_pk = evaluator_keys
    _, agent_pk = agent_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)

    # Evaluator tries to propose — should be rejected
    agr = make_agreement_dict(req_pk, agent_pk, eval_pk)
    env = make_envelope(
        EventType.PROPOSAL_SUBMITTED, job_id, agr_hash, {"agreement": agr}, eval_sk,
    )
    resp = client.post(f"/jobs/{job_id}/proposals", json=env)
    assert resp.status_code == 403


def test_evaluator_cannot_sign_agreement(
    client, requestor_keys, agent_keys, evaluator_keys
):
    """Evaluator signing should NOT count as a valid agreement signature."""
    req_sk, req_pk = requestor_keys
    eval_sk, eval_pk = evaluator_keys
    _, agent_pk = agent_keys

    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)

    # Requestor signs (valid)
    env = make_envelope(EventType.AGREEMENT_SIGNED, job_id, agr_hash, {}, req_sk)
    resp = client.post(f"/jobs/{job_id}/signatures", json=env)
    assert resp.status_code == 200

    # Evaluator tries to sign (should be rejected)
    env = make_envelope(EventType.AGREEMENT_SIGNED, job_id, agr_hash, {}, eval_sk)
    resp = client.post(f"/jobs/{job_id}/signatures", json=env)
    assert resp.status_code == 403


def test_get_nonexistent_job(client):
    resp = client.get("/jobs/nonexistent")
    assert resp.status_code == 404


# ── UW / Principal track helpers ────────────────────────────────────────────


def _create_fund_moving_job(
    client, req_sk, req_pk, agent_pk, eval_pk, uw_pk, settle_pk
):
    """Create a fund-moving job and return (job_id, agr_hash, agr_dict)."""
    agr = make_fund_moving_agreement_dict(req_pk, agent_pk, eval_pk, uw_pk, settle_pk)
    req = make_create_request({"agreement": agr}, req_sk)
    resp = client.post("/jobs", json=req)
    assert resp.status_code == 201, resp.json()
    data = resp.json()
    return data["job_id"], data["agreement_hash"], agr


def _uw_request(client, job_id, agr_hash, agent_sk):
    env = make_envelope(EventType.UW_REQUESTED, job_id, agr_hash, {}, agent_sk)
    resp = client.post(f"/jobs/{job_id}/uw/request", json=env)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def _uw_decide(client, job_id, agr_hash, uw_sk, approve=True, premium=0, collateral=0):
    payload = {
        "approve": approve,
        "premium": premium,
        "collateral_required": collateral,
    }
    env = make_envelope(EventType.UW_DECIDED, job_id, agr_hash, payload, uw_sk)
    resp = client.post(f"/jobs/{job_id}/uw/decide", json=env)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def _pay_premium(client, job_id, agr_hash, req_sk, ref="premium://paid"):
    env = make_envelope(
        EventType.PREMIUM_PAID, job_id, agr_hash, {"premium_ref": ref}, req_sk
    )
    resp = client.post(f"/jobs/{job_id}/uw/premium", json=env)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def _approve_release(client, job_id, agr_hash, req_sk):
    env = make_envelope(EventType.RELEASE_APPROVED, job_id, agr_hash, {}, req_sk)
    resp = client.post(f"/jobs/{job_id}/release/approve", json=env)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def _release_principal(client, job_id, agr_hash, settle_sk):
    env = make_envelope(EventType.PRINCIPAL_RELEASED, job_id, agr_hash, {}, settle_sk)
    resp = client.post(f"/jobs/{job_id}/principal/release", json=env)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def _submit_exec_evidence(client, job_id, agr_hash, agent_sk, ref="exec://ev1"):
    env = make_envelope(
        EventType.EXECUTION_EVIDENCE_SUBMITTED,
        job_id,
        agr_hash,
        {"exec_evidence_ref": ref},
        agent_sk,
    )
    resp = client.post(f"/jobs/{job_id}/execution-evidence", json=env)
    assert resp.status_code == 200, resp.json()
    return resp.json()


# ── UW / Principal track happy paths ────────────────────────────────────────


def test_uw_happy_approve_no_collateral(
    client,
    requestor_keys,
    agent_keys,
    evaluator_keys,
    underwriter_keys,
    settlement_keys,
):
    """Full UW flow: approve with premium, no collateral → release → evidence."""
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    _, eval_pk = evaluator_keys
    uw_sk, uw_pk = underwriter_keys
    settle_sk, settle_pk = settlement_keys

    # Create fund-moving job, sign, lock fee
    job_id, agr_hash, _ = _create_fund_moving_job(
        client, req_sk, req_pk, agent_pk, eval_pk, uw_pk, settle_pk
    )
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)

    # Verify principal track starts at UW_AWAIT_REQUEST
    state = client.get(f"/jobs/{job_id}").json()
    assert state["principal_track_state"] == "UW_AWAIT_REQUEST"

    # UW request
    uw_req = _uw_request(client, job_id, agr_hash, agent_sk)
    assert uw_req["principal_track_state"] == "UW_REVIEW"

    # UW approves with premium=50, no collateral
    uw_dec = _uw_decide(client, job_id, agr_hash, uw_sk, approve=True, premium=50)
    assert uw_dec["principal_track_state"] == "PREMIUM_PENDING"

    # Pay premium
    prem = _pay_premium(client, job_id, agr_hash, req_sk)
    assert prem["principal_track_state"] == "APPROVAL_PENDING"

    # Requestor approves release
    rel = _approve_release(client, job_id, agr_hash, req_sk)
    assert rel["principal_track_state"] == "RELEASABLE"

    # Settlement layer releases principal
    xfer = _release_principal(client, job_id, agr_hash, settle_sk)
    assert "transfer_ref" in xfer

    # Business agent submits execution evidence
    ev = _submit_exec_evidence(client, job_id, agr_hash, agent_sk)
    assert ev["principal_track_state"] == "EXECUTION_EVIDENCE_SUBMITTED"

    # Verify final state
    state = client.get(f"/jobs/{job_id}").json()
    assert state["principal_track_state"] == "EXECUTION_EVIDENCE_SUBMITTED"
    assert state["transfer_ref"] is not None
    assert state["exec_evidence_ref"] is not None


def test_uw_happy_approve_with_collateral(
    client,
    requestor_keys,
    agent_keys,
    evaluator_keys,
    underwriter_keys,
    settlement_keys,
):
    """UW approves with collateral → lock collateral → release."""
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    _, eval_pk = evaluator_keys
    uw_sk, uw_pk = underwriter_keys
    settle_sk, settle_pk = settlement_keys

    job_id, agr_hash, _ = _create_fund_moving_job(
        client, req_sk, req_pk, agent_pk, eval_pk, uw_pk, settle_pk
    )
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)
    _uw_request(client, job_id, agr_hash, agent_sk)
    _uw_decide(client, job_id, agr_hash, uw_sk, approve=True, collateral=2000)

    # State should be COLLATERAL_REQUESTED
    state = client.get(f"/jobs/{job_id}").json()
    assert state["principal_track_state"] == "COLLATERAL_REQUESTED"

    # Lock collateral (business agent locks their own money as guarantee)
    env = make_envelope(EventType.COLLATERAL_LOCKED, job_id, agr_hash, {}, agent_sk)
    resp = client.post(f"/jobs/{job_id}/uw/collateral/lock", json=env)
    assert resp.status_code == 200, resp.json()
    assert "collateral_ref" in resp.json()

    # State should be APPROVAL_PENDING
    state = client.get(f"/jobs/{job_id}").json()
    assert state["principal_track_state"] == "APPROVAL_PENDING"

    # Approve + release
    _approve_release(client, job_id, agr_hash, req_sk)
    xfer = _release_principal(client, job_id, agr_hash, settle_sk)
    assert "transfer_ref" in xfer


# ── UW override paths ───────────────────────────────────────────────────────


def test_uw_reject_override_proceed(
    client,
    requestor_keys,
    agent_keys,
    evaluator_keys,
    underwriter_keys,
    settlement_keys,
):
    """UW rejects → requestor overrides with proceed → release."""
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    _, eval_pk = evaluator_keys
    uw_sk, uw_pk = underwriter_keys
    settle_sk, settle_pk = settlement_keys

    job_id, agr_hash, _ = _create_fund_moving_job(
        client, req_sk, req_pk, agent_pk, eval_pk, uw_pk, settle_pk
    )
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)
    _uw_request(client, job_id, agr_hash, agent_sk)

    # UW rejects
    _uw_decide(client, job_id, agr_hash, uw_sk, approve=False)

    state = client.get(f"/jobs/{job_id}").json()
    assert state["principal_track_state"] == "OVERRIDE_PENDING"

    # Requestor overrides with "proceed"
    env = make_envelope(
        EventType.OVERRIDE_DECIDED, job_id, agr_hash, {"decision": "proceed"}, req_sk,
    )
    resp = client.post(f"/jobs/{job_id}/uw/override", json=env)
    assert resp.status_code == 200
    assert resp.json()["principal_track_state"] == "APPROVAL_PENDING"

    # Approve + release
    _approve_release(client, job_id, agr_hash, req_sk)
    xfer = _release_principal(client, job_id, agr_hash, settle_sk)
    assert "transfer_ref" in xfer


def test_uw_collateral_refused_override(
    client,
    requestor_keys,
    agent_keys,
    evaluator_keys,
    underwriter_keys,
    settlement_keys,
):
    """UW approves with collateral → requestor refuses → override → release."""
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    _, eval_pk = evaluator_keys
    uw_sk, uw_pk = underwriter_keys
    settle_sk, settle_pk = settlement_keys

    job_id, agr_hash, _ = _create_fund_moving_job(
        client, req_sk, req_pk, agent_pk, eval_pk, uw_pk, settle_pk
    )
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)
    _uw_request(client, job_id, agr_hash, agent_sk)
    _uw_decide(client, job_id, agr_hash, uw_sk, approve=True, collateral=5000)

    # Refuse collateral
    env = make_envelope(EventType.COLLATERAL_REFUSED, job_id, agr_hash, {}, req_sk)
    resp = client.post(f"/jobs/{job_id}/uw/collateral/refuse", json=env)
    assert resp.status_code == 200
    assert resp.json()["principal_track_state"] == "OVERRIDE_PENDING"

    # Requestor overrides
    env = make_envelope(
        EventType.OVERRIDE_DECIDED, job_id, agr_hash, {"decision": "proceed"}, req_sk,
    )
    resp = client.post(f"/jobs/{job_id}/uw/override", json=env)
    assert resp.status_code == 200

    _approve_release(client, job_id, agr_hash, req_sk)
    xfer = _release_principal(client, job_id, agr_hash, settle_sk)
    assert "transfer_ref" in xfer


# ── UW guardrail tests ──────────────────────────────────────────────────────


def test_uw_request_requires_fund_moving(
    client, requestor_keys, agent_keys, evaluator_keys,
):
    """UW_REQUESTED should fail on a non-fund-moving job."""
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    _, eval_pk = evaluator_keys

    # Regular (non-fund-moving) job
    job_id, agr_hash, _ = _create_job(client, req_sk, req_pk, agent_pk, eval_pk)
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)

    # Try to request UW — no principal track, should fail
    env = make_envelope(EventType.UW_REQUESTED, job_id, agr_hash, {}, agent_sk)
    resp = client.post(f"/jobs/{job_id}/uw/request", json=env)
    assert resp.status_code == 409


def test_wrong_role_uw_decide(
    client,
    requestor_keys,
    agent_keys,
    evaluator_keys,
    underwriter_keys,
    settlement_keys,
):
    """Requestor cannot submit UW decision (only underwriter)."""
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    _, eval_pk = evaluator_keys
    _, uw_pk = underwriter_keys
    _, settle_pk = settlement_keys

    job_id, agr_hash, _ = _create_fund_moving_job(
        client, req_sk, req_pk, agent_pk, eval_pk, uw_pk, settle_pk
    )
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)
    _uw_request(client, job_id, agr_hash, agent_sk)

    # Requestor tries to submit UW decision
    env = make_envelope(
        EventType.UW_DECIDED, job_id, agr_hash, {"approve": True}, req_sk,
    )
    resp = client.post(f"/jobs/{job_id}/uw/decide", json=env)
    assert resp.status_code == 403


def test_cannot_release_before_approval(
    client,
    requestor_keys,
    agent_keys,
    evaluator_keys,
    underwriter_keys,
    settlement_keys,
):
    """PRINCIPAL_RELEASED requires RELEASABLE state."""
    req_sk, req_pk = requestor_keys
    agent_sk, agent_pk = agent_keys
    _, eval_pk = evaluator_keys
    uw_sk, uw_pk = underwriter_keys
    settle_sk, settle_pk = settlement_keys

    job_id, agr_hash, _ = _create_fund_moving_job(
        client, req_sk, req_pk, agent_pk, eval_pk, uw_pk, settle_pk
    )
    _sign_both(client, job_id, agr_hash, req_sk, agent_sk)
    _lock_fee(client, job_id, agr_hash, req_sk)
    _uw_request(client, job_id, agr_hash, agent_sk)
    _uw_decide(client, job_id, agr_hash, uw_sk, approve=True)

    # Try to release without requestor approval — should fail
    env = make_envelope(EventType.PRINCIPAL_RELEASED, job_id, agr_hash, {}, settle_sk)
    resp = client.post(f"/jobs/{job_id}/principal/release", json=env)
    assert resp.status_code == 409
