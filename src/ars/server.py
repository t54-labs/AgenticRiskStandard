from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request

from .crypto import compute_agreement_hash, verify_envelope_signature
from .errors import AuthError, BadRequestError, ConflictError, NotFoundError
from .models import (
    AgreementDraft,
    CreateJobRequest,
    EventType,
    SignedActionEnvelope,
)
from .routes import create_shared_router, verify_sig
from .settlement import MockSettlementLayer, SettlementLayer
from .state import derive_job_state, validate_transition
from .store import EventStore


# ── App factory ──────────────────────────────────────────────────────────────


def create_app(
    db_path: str = "ars.db", settlement: Optional[SettlementLayer] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.store = EventStore(db_path=db_path)
        application.state.settlement = settlement or MockSettlementLayer()
        yield

    application = FastAPI(title="ARS v1", version="0.1.0", lifespan=lifespan)

    # Shared routes (proposals, signatures, deliverable, evaluate, UW, GET, etc.)
    shared = create_shared_router(
        derive_state=derive_job_state,
        validate_transition=validate_transition,
        validate_agreement_draft=lambda d: AgreementDraft(**d),
        get_store=_store,
        event_types={et.name: et.value for et in EventType},
    )
    application.include_router(shared)

    # Override routes (create_job, fee lock/settle, collateral lock, principal release)
    _register_override_routes(application)

    return application


def _store(request: Request) -> EventStore:
    return request.app.state.store


def _settlement(request: Request) -> SettlementLayer:
    return request.app.state.settlement


# ── Override routes (server-specific) ────────────────────────────────────────


def _register_override_routes(application: FastAPI) -> None:
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

    @application.post("/jobs/{job_id}/fee/lock")
    async def lock_fee(job_id: str, envelope: SignedActionEnvelope, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != EventType.FEE_ESCROW_LOCKED:
            raise BadRequestError("Expected type FEE_ESCROW_LOCKED")

        verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_job_state(events)
        validate_transition(state, envelope)

        assert state.agreement is not None
        agr = AgreementDraft(**state.agreement)

        sl = _settlement(request)
        lock_result = await sl.lock_fee(
            job_id,
            agr.fee.amount,
            agr.fee.currency,
            payer_addr=agr.requestor_pubkey,
            payee_addr=agr.business_agent_pubkey,
        )

        payload = {**envelope.payload, "lock_ref": lock_result.ref}
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)

        return {
            "job_id": job_id,
            "fee_track_state": "FEE_ESCROW_LOCKED",
            "lock_ref": lock_result.ref,
        }

    @application.post("/jobs/{job_id}/fee/settle")
    async def settle_fee(job_id: str, envelope: SignedActionEnvelope, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != EventType.FEE_SETTLED:
            raise BadRequestError("Expected type FEE_SETTLED")

        if "action" not in envelope.payload:
            raise BadRequestError("payload.action is required")

        verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_job_state(events)
        validate_transition(state, envelope)

        sl = _settlement(request)
        action = envelope.payload["action"]
        if action == "release":
            result = await sl.release_fee(job_id)
        else:
            result = await sl.refund_fee(job_id)

        # Auto-handle collateral based on verdict
        collateral_result = None
        if state.collateral_ref:
            if action == "release":
                collateral_result = await sl.unlock_collateral(job_id)
            else:
                collateral_result = await sl.slash_collateral(job_id, "treasury")

        payload = {**envelope.payload, "settlement_ref": result.ref}
        if collateral_result:
            payload["collateral_settlement_ref"] = collateral_result.ref
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)

        events = store.get_events(job_id)
        new_state = derive_job_state(events)
        resp = {
            "job_id": job_id,
            "phase": new_state.phase.value,
            "fee_track_state": new_state.fee_track_state.value
            if new_state.fee_track_state
            else None,
            "settlement_ref": result.ref,
        }
        if collateral_result:
            resp["collateral_settlement_ref"] = collateral_result.ref
        return resp

    @application.post("/jobs/{job_id}/uw/collateral/lock")
    async def lock_collateral(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if envelope.type != EventType.COLLATERAL_LOCKED:
            raise BadRequestError("Expected type COLLATERAL_LOCKED")

        verify_sig(envelope)
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

        sl = _settlement(request)
        lock_result = await sl.lock_collateral(
            job_id, amt, agr.principal.currency, payer_addr=agr.business_agent_pubkey,
        )

        payload = {**envelope.payload, "amount": amt, "collateral_ref": lock_result.ref}
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)
        return {"job_id": job_id, "collateral_ref": lock_result.ref}

    @application.post("/jobs/{job_id}/principal/release")
    async def release_principal(
        job_id: str, envelope: SignedActionEnvelope, request: Request
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if envelope.type != EventType.PRINCIPAL_RELEASED:
            raise BadRequestError("Expected type PRINCIPAL_RELEASED")

        verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_job_state(events)
        validate_transition(state, envelope)

        assert state.agreement
        agr = AgreementDraft(**state.agreement)
        assert agr.principal

        sl = _settlement(request)
        result = await sl.release_principal(
            job_id,
            agr.principal.amount,
            agr.principal.currency,
            agr.principal.destination,
        )

        payload = {
            **envelope.payload,
            "transfer_ref": result.ref,
            "approvals": state.release_approvals,
        }
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)
        return {"job_id": job_id, "transfer_ref": result.ref}


# Default app instance for `uvicorn ars.server:app`
app = create_app()
