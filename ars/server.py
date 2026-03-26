from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request

from .crypto import (
    compute_agreement_hash,
    envelope_body,
    verify_envelope_signature,
)
from .errors import AuthError, BadRequestError, ConflictError, NotFoundError
from .models import (
    AgreementDraft,
    CreateJobRequest,
    EventType,
    SignedActionEnvelope,
)
from .state import derive_job_state, validate_transition
from .store import EventStore
from .vault import MockCollateralVault, MockEscrowVault, MockPrincipalVault


# ── App factory ──────────────────────────────────────────────────────────────


def create_app(db_path: str = "ars.db") -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.store = EventStore(db_path=db_path)
        application.state.vault = MockEscrowVault()
        application.state.collateral_vault = MockCollateralVault()
        application.state.principal_vault = MockPrincipalVault()
        yield

    application = FastAPI(title="ARS v1", version="0.1.0", lifespan=lifespan)
    _register_routes(application)
    return application


def _store(request: Request) -> EventStore:
    return request.app.state.store


def _vault(request: Request) -> MockEscrowVault:
    return request.app.state.vault


def _collateral_vault(request: Request) -> MockCollateralVault:
    return request.app.state.collateral_vault


def _principal_vault(request: Request) -> MockPrincipalVault:
    return request.app.state.principal_vault


# ── Signature verification helper ────────────────────────────────────────────


def _verify_sig(envelope: SignedActionEnvelope) -> None:
    body = envelope_body(envelope.model_dump())
    if not verify_envelope_signature(envelope.actor, body, envelope.signature):
        raise AuthError()


# ── Generic event-append helper ──────────────────────────────────────────────


def _append_validated(
    store: EventStore,
    job_id: str,
    envelope: SignedActionEnvelope,
    expected_type: EventType,
    extra_payload: dict | None = None,
) -> dict:
    """Verify sig, validate transition, append event. Returns re-derived state dict."""
    if envelope.type != expected_type:
        raise BadRequestError(f"Expected type {expected_type.value}")

    _verify_sig(envelope)
    envelope = envelope.model_copy(update={"job_id": job_id})

    events = store.get_events(job_id)
    state = derive_job_state(events)
    validate_transition(state, envelope)

    if extra_payload:
        payload = {**envelope.payload, **extra_payload}
        envelope = envelope.model_copy(update={"payload": payload})

    store.append_event(envelope)

    events = store.get_events(job_id)
    new_state = derive_job_state(events)
    return new_state


# ── Route registration ───────────────────────────────────────────────────────


def _register_routes(application: FastAPI) -> None:

    # POST /jobs  –  SubmitRequest
    @application.post("/jobs", status_code=201)
    async def create_job(req: CreateJobRequest, request: Request):
        if req.type != "JOB_CREATED":
            raise BadRequestError("Expected type JOB_CREATED")

        agreement_dict = req.payload.get("agreement")
        if not agreement_dict:
            raise BadRequestError("payload.agreement is required")

        agreement = AgreementDraft(**agreement_dict)

        if req.actor != agreement.requestor_pubkey:
            raise BadRequestError("Actor must be the requestor")

        body = {
            "type": req.type,
            "payload": req.payload,
            "actor": req.actor,
            "timestamp": req.timestamp,
        }
        if not verify_envelope_signature(req.actor, body, req.signature):
            raise AuthError()

        agr_hash = compute_agreement_hash(agreement_dict)
        job_id = str(uuid.uuid4())

        storage_envelope = SignedActionEnvelope(
            type=EventType.JOB_CREATED,
            job_id=job_id,
            agreement_hash=agr_hash,
            payload=req.payload,
            actor=req.actor,
            signature=req.signature,
            timestamp=req.timestamp,
        )

        store = _store(request)
        store.create_job(job_id, req.timestamp)
        store.append_event(storage_envelope)

        return {"job_id": job_id, "agreement_hash": agr_hash, "phase": "NEGOTIATION"}

    # POST /jobs/{job_id}/proposals  –  ProposeAgreement
    @application.post("/jobs/{job_id}/proposals")
    async def propose_agreement(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != EventType.PROPOSAL_SUBMITTED:
            raise BadRequestError("Expected type PROPOSAL_SUBMITTED")

        agreement_dict = envelope.payload.get("agreement")
        if not agreement_dict:
            raise BadRequestError("payload.agreement is required")
        AgreementDraft(**agreement_dict)

        _verify_sig(envelope)

        agr_hash = compute_agreement_hash(agreement_dict)
        envelope = envelope.model_copy(
            update={"job_id": job_id, "agreement_hash": agr_hash}
        )

        events = store.get_events(job_id)
        state = derive_job_state(events)
        validate_transition(state, envelope)

        store.append_event(envelope)
        return {"job_id": job_id, "agreement_hash": agr_hash}

    # POST /jobs/{job_id}/signatures  –  SignAgreement
    @application.post("/jobs/{job_id}/signatures")
    async def sign_agreement(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != EventType.AGREEMENT_SIGNED:
            raise BadRequestError("Expected type AGREEMENT_SIGNED")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_job_state(events)
        validate_transition(state, envelope)

        store.append_event(envelope)

        events = store.get_events(job_id)
        new_state = derive_job_state(events)
        return {
            "job_id": job_id,
            "phase": new_state.phase.value,
            "signatures": new_state.signatures,
        }

    # POST /jobs/{job_id}/fee/lock  –  LockFeeEscrow
    @application.post("/jobs/{job_id}/fee/lock")
    async def lock_fee(job_id: str, envelope: SignedActionEnvelope, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != EventType.FEE_ESCROW_LOCKED:
            raise BadRequestError("Expected type FEE_ESCROW_LOCKED")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_job_state(events)
        validate_transition(state, envelope)

        vault = _vault(request)
        assert state.agreement is not None
        agr = AgreementDraft(**state.agreement)
        lock_ref = vault.lock(job_id, agr.fee.amount, agr.fee.currency)

        payload = {**envelope.payload, "lock_ref": lock_ref}
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)

        return {
            "job_id": job_id,
            "fee_track_state": "FEE_ESCROW_LOCKED",
            "lock_ref": lock_ref,
        }

    # POST /jobs/{job_id}/deliverable  –  SubmitDeliverable
    @application.post("/jobs/{job_id}/deliverable")
    async def submit_deliverable(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != EventType.DELIVERABLE_SUBMITTED:
            raise BadRequestError("Expected type DELIVERABLE_SUBMITTED")

        if not envelope.payload.get("deliverable_ref"):
            raise BadRequestError("payload.deliverable_ref is required")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_job_state(events)
        validate_transition(state, envelope)

        store.append_event(envelope)
        return {
            "job_id": job_id,
            "fee_track_state": "FEE_DELIVERED",
            "deliverable_ref": envelope.payload["deliverable_ref"],
        }

    # POST /jobs/{job_id}/evaluate  –  EvaluateOutcome
    @application.post("/jobs/{job_id}/evaluate")
    async def evaluate_outcome(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != EventType.OUTCOME_EVALUATED:
            raise BadRequestError("Expected type OUTCOME_EVALUATED")

        if "verdict" not in envelope.payload:
            raise BadRequestError("payload.verdict is required")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_job_state(events)
        validate_transition(state, envelope)

        store.append_event(envelope)
        return {
            "job_id": job_id,
            "phase": "EVALUATION",
            "verdict": envelope.payload["verdict"],
        }

    # POST /jobs/{job_id}/fee/settle  –  SettleFeeEscrow
    @application.post("/jobs/{job_id}/fee/settle")
    async def settle_fee(job_id: str, envelope: SignedActionEnvelope, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != EventType.FEE_SETTLED:
            raise BadRequestError("Expected type FEE_SETTLED")

        if "action" not in envelope.payload:
            raise BadRequestError("payload.action is required")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_job_state(events)
        validate_transition(state, envelope)

        vault = _vault(request)
        assert state.fee_lock_ref is not None
        settlement_ref = vault.settle(state.fee_lock_ref, envelope.payload["action"])

        payload = {**envelope.payload, "settlement_ref": settlement_ref}
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)

        events = store.get_events(job_id)
        new_state = derive_job_state(events)
        return {
            "job_id": job_id,
            "phase": new_state.phase.value,
            "fee_track_state": new_state.fee_track_state.value
            if new_state.fee_track_state
            else None,
            "settlement_ref": settlement_ref,
        }

    # GET /jobs/{job_id}  –  GetJobState
    @application.get("/jobs/{job_id}")
    async def get_job(job_id: str, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        state = derive_job_state(events)
        return state.model_dump()

    # GET /jobs/{job_id}/events  –  GetEventLog
    @application.get("/jobs/{job_id}/events")
    async def get_events(job_id: str, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        return {"job_id": job_id, "events": [e.model_dump() for e in events]}

    # ── UW / Principal track endpoints ───────────────────────────────────

    # POST /jobs/{job_id}/uw/request  –  RequestUW
    @application.post("/jobs/{job_id}/uw/request")
    async def request_uw(job_id: str, envelope: SignedActionEnvelope, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        new_state = _append_validated(store, job_id, envelope, EventType.UW_REQUESTED)
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

    # POST /jobs/{job_id}/uw/decide  –  UWDecision
    @application.post("/jobs/{job_id}/uw/decide")
    async def uw_decide(job_id: str, envelope: SignedActionEnvelope, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if "approve" not in envelope.payload:
            raise BadRequestError("payload.approve is required")

        new_state = _append_validated(store, job_id, envelope, EventType.UW_DECIDED)
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "approve": envelope.payload["approve"],
        }

    # POST /jobs/{job_id}/uw/premium  –  PayPremium
    @application.post("/jobs/{job_id}/uw/premium")
    async def pay_premium(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        premium_ref = envelope.payload.get("premium_ref")
        if not premium_ref:
            raise BadRequestError("payload.premium_ref is required")

        new_state = _append_validated(store, job_id, envelope, EventType.PREMIUM_PAID)
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "premium_ref": premium_ref,
        }

    # POST /jobs/{job_id}/uw/collateral/lock  –  LockCollateral
    @application.post("/jobs/{job_id}/uw/collateral/lock")
    async def lock_collateral(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if envelope.type != EventType.COLLATERAL_LOCKED:
            raise BadRequestError("Expected type COLLATERAL_LOCKED")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_job_state(events)
        validate_transition(state, envelope)

        if not state.uw_decision:
            raise ConflictError("No UW decision recorded")
        amt = int(state.uw_decision.get("collateral_required") or 0)
        if amt <= 0:
            raise BadRequestError("No collateral required for this job")
        assert state.agreement
        agr = AgreementDraft(**state.agreement)
        assert agr.principal
        cv = _collateral_vault(request)
        collateral_ref = cv.lock(job_id, amt, agr.principal.currency)

        payload = {**envelope.payload, "amount": amt, "collateral_ref": collateral_ref}
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)
        return {"job_id": job_id, "collateral_ref": collateral_ref}

    # POST /jobs/{job_id}/uw/collateral/refuse  –  RefuseCollateral
    @application.post("/jobs/{job_id}/uw/collateral/refuse")
    async def refuse_collateral(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        new_state = _append_validated(
            store, job_id, envelope, EventType.COLLATERAL_REFUSED
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

    # POST /jobs/{job_id}/uw/override  –  OverrideDecision
    @application.post("/jobs/{job_id}/uw/override")
    async def override_decision(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if "decision" not in envelope.payload:
            raise BadRequestError("payload.decision is required")

        new_state = _append_validated(
            store, job_id, envelope, EventType.OVERRIDE_DECIDED
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "decision": envelope.payload["decision"],
        }

    # POST /jobs/{job_id}/release/approve  –  ApproveRelease
    @application.post("/jobs/{job_id}/release/approve")
    async def approve_release(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        new_state = _append_validated(
            store, job_id, envelope, EventType.RELEASE_APPROVED
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

    # POST /jobs/{job_id}/principal/release  –  ReleasePrincipal
    @application.post("/jobs/{job_id}/principal/release")
    async def release_principal(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if envelope.type != EventType.PRINCIPAL_RELEASED:
            raise BadRequestError("Expected type PRINCIPAL_RELEASED")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_job_state(events)
        validate_transition(state, envelope)

        assert state.agreement
        agr = AgreementDraft(**state.agreement)
        assert agr.principal
        pv = _principal_vault(request)
        transfer_ref = pv.release(
            job_id,
            agr.principal.amount,
            agr.principal.currency,
            agr.principal.destination,
        )

        payload = {
            **envelope.payload,
            "transfer_ref": transfer_ref,
            "approvals": state.release_approvals,
        }
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)
        return {"job_id": job_id, "transfer_ref": transfer_ref}

    # POST /jobs/{job_id}/execution-evidence  –  SubmitExecutionEvidence
    @application.post("/jobs/{job_id}/execution-evidence")
    async def submit_execution_evidence(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if not envelope.payload.get("exec_evidence_ref"):
            raise BadRequestError("payload.exec_evidence_ref is required")

        new_state = _append_validated(
            store, job_id, envelope, EventType.EXECUTION_EVIDENCE_SUBMITTED
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "exec_evidence_ref": envelope.payload["exec_evidence_ref"],
        }


# Default app instance for `uvicorn ars.server:app`
app = create_app()
