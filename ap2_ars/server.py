"""AP2-ARS FastAPI application: base ARS endpoints + AP2 mandate + x402."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request

from ars.crypto import (
    compute_agreement_hash,
    envelope_body,
    verify_envelope_signature,
)
from ars.errors import AuthError, BadRequestError, ConflictError, NotFoundError
from ars.models import CreateJobRequest, SignedActionEnvelope
from ars.store import EventStore

from .constraints import ConstraintEngine
from .models import (
    AP2AgreementDraft,
    AP2EventType,
    CartMandate,
    IntentMandate,
    Modality,
)
from .roles import RoleRegistry
from .settlement import MockSettlementLayer, SettlementLayer
from .state import derive_ap2_job_state, validate_ap2_transition


# ── App factory ──────────────────────────────────────────────────────────────


def create_app(
    db_path: str = "ap2_ars.db", settlement: Optional[SettlementLayer] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.store = EventStore(db_path=db_path)
        application.state.settlement = settlement or MockSettlementLayer()
        application.state.constraint_engine = ConstraintEngine()
        yield

    application = FastAPI(title="AP2-ARS", version="0.1.0", lifespan=lifespan)
    _register_base_routes(application)
    _register_mandate_routes(application)
    return application


def _store(request: Request) -> EventStore:
    return request.app.state.store


def _settlement(request: Request) -> SettlementLayer:
    return request.app.state.settlement


def _constraint_engine(request: Request) -> ConstraintEngine:
    return request.app.state.constraint_engine


# ── Sig verification ─────────────────────────────────────────────────────────


def _verify_sig(envelope: SignedActionEnvelope) -> None:
    body = envelope_body(envelope.model_dump())
    if not verify_envelope_signature(envelope.actor, body, envelope.signature):
        raise AuthError()


# ── Generic append helper ────────────────────────────────────────────────────


def _append_validated(
    store: EventStore,
    job_id: str,
    envelope: SignedActionEnvelope,
    expected_type: str,
    extra_payload: dict | None = None,
) -> dict:
    """Verify sig -> validate transition -> append event -> re-derive state."""
    if envelope.type != expected_type:
        raise BadRequestError(f"Expected type {expected_type}")

    _verify_sig(envelope)
    envelope = envelope.model_copy(update={"job_id": job_id})

    events = store.get_events(job_id)
    state = derive_ap2_job_state(events)
    validate_ap2_transition(state, envelope)

    if extra_payload:
        payload = {**envelope.payload, **extra_payload}
        envelope = envelope.model_copy(update={"payload": payload})

    store.append_event(envelope)

    events = store.get_events(job_id)
    new_state = derive_ap2_job_state(events)
    return new_state


# ── Base ARS routes (fee track + principal track) ─────────────────────────────


def _register_base_routes(application: FastAPI) -> None:
    @application.post("/jobs", status_code=201)
    async def create_job(req: CreateJobRequest, request: Request):
        if req.type != "JOB_CREATED":
            raise BadRequestError("Expected type JOB_CREATED")

        agreement_dict = req.payload.get("agreement")
        if not agreement_dict:
            raise BadRequestError("payload.agreement is required")

        agreement = AP2AgreementDraft(**agreement_dict)

        if req.actor != agreement.user_pubkey:
            raise BadRequestError("Actor must be the user (requestor)")

        # Enforce agent-payment firewall at creation
        registry = RoleRegistry(agreement)
        registry.validate_firewall()

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
            type=AP2EventType.JOB_CREATED.value,
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

        return {
            "job_id": job_id,
            "agreement_hash": agr_hash,
            "phase": "NEGOTIATION",
            "modality": agreement.modality.value,
        }

    @application.post("/jobs/{job_id}/proposals")
    async def propose_agreement(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != AP2EventType.PROPOSAL_SUBMITTED.value:
            raise BadRequestError("Expected type PROPOSAL_SUBMITTED")

        agreement_dict = envelope.payload.get("agreement")
        if not agreement_dict:
            raise BadRequestError("payload.agreement is required")
        AP2AgreementDraft(**agreement_dict)

        _verify_sig(envelope)

        agr_hash = compute_agreement_hash(agreement_dict)
        envelope = envelope.model_copy(
            update={"job_id": job_id, "agreement_hash": agr_hash},
        )

        events = store.get_events(job_id)
        state = derive_ap2_job_state(events)
        validate_ap2_transition(state, envelope)

        store.append_event(envelope)
        return {"job_id": job_id, "agreement_hash": agr_hash}

    @application.post("/jobs/{job_id}/signatures")
    async def sign_agreement(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.AGREEMENT_SIGNED.value,
        )
        return {
            "job_id": job_id,
            "phase": new_state.phase.value,
            "signatures": new_state.signatures,
        }

    @application.post("/jobs/{job_id}/fee/lock")
    async def lock_fee(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != AP2EventType.FEE_ESCROW_LOCKED.value:
            raise BadRequestError("Expected type FEE_ESCROW_LOCKED")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_ap2_job_state(events)
        validate_ap2_transition(state, envelope)

        assert state.agreement is not None
        sl = _settlement(request)

        # Use cart total from mandate if available, otherwise agreement fee
        fee_amount = state.agreement.fee.amount
        fee_currency = state.agreement.fee.currency
        if state.cart_mandate:
            from .models import CartMandate as _CM

            _cart = _CM(**state.cart_mandate)
            fee_amount = _cart.total

        lock_result = await sl.lock_fee(
            job_id,
            fee_amount,
            fee_currency,
            payer_addr=state.agreement.user_pubkey,
            payee_addr=state.agreement.merchant_pubkey,
        )

        payload = {**envelope.payload, "lock_ref": lock_result.ref}
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)

        return {
            "job_id": job_id,
            "fee_track_state": "FEE_ESCROW_LOCKED",
            "lock_ref": lock_result.ref,
        }

    @application.post("/jobs/{job_id}/deliverable")
    async def submit_deliverable(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != AP2EventType.DELIVERABLE_SUBMITTED.value:
            raise BadRequestError("Expected type DELIVERABLE_SUBMITTED")
        if not envelope.payload.get("deliverable_ref"):
            raise BadRequestError("payload.deliverable_ref is required")

        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.DELIVERABLE_SUBMITTED.value,
        )
        return {
            "job_id": job_id,
            "fee_track_state": "FEE_DELIVERED",
            "deliverable_ref": envelope.payload["deliverable_ref"],
        }

    @application.post("/jobs/{job_id}/evaluate")
    async def evaluate_outcome(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != AP2EventType.OUTCOME_EVALUATED.value:
            raise BadRequestError("Expected type OUTCOME_EVALUATED")
        if "verdict" not in envelope.payload:
            raise BadRequestError("payload.verdict is required")

        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.OUTCOME_EVALUATED.value,
        )
        return {
            "job_id": job_id,
            "phase": "EVALUATION",
            "verdict": envelope.payload["verdict"],
        }

    @application.post("/jobs/{job_id}/fee/settle")
    async def settle_fee(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != AP2EventType.FEE_SETTLED.value:
            raise BadRequestError("Expected type FEE_SETTLED")
        if "action" not in envelope.payload:
            raise BadRequestError("payload.action is required")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_ap2_job_state(events)
        validate_ap2_transition(state, envelope)

        sl = _settlement(request)
        action = envelope.payload["action"]
        if action == "release":
            result = await sl.release_fee(job_id)
        else:
            result = await sl.refund_fee(job_id)

        payload = {**envelope.payload, "settlement_ref": result.ref}
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)

        events = store.get_events(job_id)
        new_state = derive_ap2_job_state(events)
        return {
            "job_id": job_id,
            "phase": new_state.phase.value,
            "fee_track_state": new_state.fee_track_state.value
            if new_state.fee_track_state
            else None,
            "settlement_ref": result.ref,
        }

    # GET endpoints
    @application.get("/jobs/{job_id}")
    async def get_job(job_id: str, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        state = derive_ap2_job_state(events)
        return state.model_dump()

    @application.get("/jobs/{job_id}/events")
    async def get_events(job_id: str, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        return {"job_id": job_id, "events": [e.model_dump() for e in events]}

    # UW / Principal track endpoints

    @application.post("/jobs/{job_id}/uw/request")
    async def request_uw(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.UW_REQUESTED.value,
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/uw/decide")
    async def uw_decide(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if "approve" not in envelope.payload:
            raise BadRequestError("payload.approve is required")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.UW_DECIDED.value,
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "approve": envelope.payload["approve"],
        }

    @application.post("/jobs/{job_id}/uw/premium")
    async def pay_premium(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        premium_ref = envelope.payload.get("premium_ref")
        if not premium_ref:
            raise BadRequestError("payload.premium_ref is required")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.PREMIUM_PAID.value,
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "premium_ref": premium_ref,
        }

    @application.post("/jobs/{job_id}/uw/collateral/lock")
    async def lock_collateral(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if envelope.type != AP2EventType.COLLATERAL_LOCKED.value:
            raise BadRequestError("Expected type COLLATERAL_LOCKED")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_ap2_job_state(events)
        validate_ap2_transition(state, envelope)

        if not state.uw_decision:
            raise ConflictError("No UW decision recorded")
        amt = int(state.uw_decision.get("collateral_required") or 0)
        if amt <= 0:
            raise BadRequestError("No collateral required for this job")
        assert state.agreement and state.agreement.principal

        sl = _settlement(request)
        lock_result = await sl.lock_collateral(
            job_id,
            amt,
            state.agreement.principal.currency,
            payer_addr=state.agreement.merchant_pubkey,
        )

        payload = {
            **envelope.payload,
            "amount": amt,
            "collateral_ref": lock_result.ref,
        }
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)
        return {"job_id": job_id, "collateral_ref": lock_result.ref}

    @application.post("/jobs/{job_id}/uw/collateral/refuse")
    async def refuse_collateral(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.COLLATERAL_REFUSED.value,
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/uw/override")
    async def override_decision(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if "decision" not in envelope.payload:
            raise BadRequestError("payload.decision is required")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.OVERRIDE_DECIDED.value,
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "decision": envelope.payload["decision"],
        }

    @application.post("/jobs/{job_id}/release/approve")
    async def approve_release(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.RELEASE_APPROVED.value,
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/principal/release")
    async def release_principal(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if envelope.type != AP2EventType.PRINCIPAL_RELEASED.value:
            raise BadRequestError("Expected type PRINCIPAL_RELEASED")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_ap2_job_state(events)
        validate_ap2_transition(state, envelope)

        assert state.agreement and state.agreement.principal

        sl = _settlement(request)
        result = await sl.release_principal(
            job_id,
            state.agreement.principal.amount,
            state.agreement.principal.currency,
            state.agreement.principal.destination,
        )

        payload = {
            **envelope.payload,
            "transfer_ref": result.ref,
            "approvals": state.release_approvals,
        }
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)
        return {"job_id": job_id, "transfer_ref": result.ref}

    @application.post("/jobs/{job_id}/execution-evidence")
    async def submit_execution_evidence(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if not envelope.payload.get("exec_evidence_ref"):
            raise BadRequestError("payload.exec_evidence_ref is required")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.EXECUTION_EVIDENCE_SUBMITTED.value,
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "exec_evidence_ref": envelope.payload["exec_evidence_ref"],
        }


# ── Mandate routes ───────────────────────────────────────────────────────────


def _register_mandate_routes(application: FastAPI) -> None:
    @application.post("/jobs/{job_id}/mandates/intent")
    async def create_intent_mandate(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.INTENT_MANDATE_CREATED.value,
        )
        return {
            "job_id": job_id,
            "mandate_track_state": new_state.mandate_track_state.value
            if new_state.mandate_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/mandates/cart")
    async def propose_cart_mandate(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.CART_MANDATE_PROPOSED.value,
        )
        return {
            "job_id": job_id,
            "mandate_track_state": new_state.mandate_track_state.value
            if new_state.mandate_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/mandates/cart/sign")
    async def sign_cart_mandate(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != AP2EventType.CART_MANDATE_SIGNED.value:
            raise BadRequestError("Expected type CART_MANDATE_SIGNED")

        _verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_ap2_job_state(events)
        validate_ap2_transition(state, envelope)

        # In human-NOT-present mode, auto-check constraints
        constraint_check = None
        if (
            state.modality == Modality.HUMAN_NOT_PRESENT
            and state.intent_mandate
            and state.cart_mandate
        ):
            engine = _constraint_engine(request)
            intent = IntentMandate(**state.intent_mandate)
            cart = CartMandate(**state.cart_mandate)
            result = engine.check(intent, cart)
            constraint_check = result.model_dump()

        store.append_event(envelope)

        events = store.get_events(job_id)
        new_state = derive_ap2_job_state(events)
        resp = {
            "job_id": job_id,
            "mandate_track_state": new_state.mandate_track_state.value
            if new_state.mandate_track_state
            else None,
        }
        if constraint_check is not None:
            resp["constraint_check"] = constraint_check
        return resp

    @application.post("/jobs/{job_id}/mandates/cart/approve")
    async def approve_cart(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.CART_APPROVED_BY_USER.value,
        )
        return {
            "job_id": job_id,
            "mandate_track_state": new_state.mandate_track_state.value
            if new_state.mandate_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/mandates/payment")
    async def create_payment_mandate(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.PAYMENT_MANDATE_CREATED.value,
        )
        return {
            "job_id": job_id,
            "mandate_track_state": new_state.mandate_track_state.value
            if new_state.mandate_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/mandates/payment/sign")
    async def sign_payment_mandate(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.PAYMENT_MANDATE_SIGNED.value,
        )
        return {
            "job_id": job_id,
            "mandate_track_state": new_state.mandate_track_state.value
            if new_state.mandate_track_state
            else None,
        }

    @application.get("/jobs/{job_id}/mandates")
    async def get_mandates(job_id: str, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        state = derive_ap2_job_state(events)
        return {
            "job_id": job_id,
            "mandate_track_state": state.mandate_track_state.value
            if state.mandate_track_state
            else None,
            "intent_mandate": state.intent_mandate,
            "cart_mandate": state.cart_mandate,
            "payment_mandate": state.payment_mandate,
        }

    @application.get("/jobs/{job_id}/constraints/check")
    async def check_constraints(job_id: str, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        state = derive_ap2_job_state(events)
        if not state.intent_mandate or not state.cart_mandate:
            return {"job_id": job_id, "result": None, "reason": "Missing mandates"}
        engine = _constraint_engine(request)
        intent = IntentMandate(**state.intent_mandate)
        cart = CartMandate(**state.cart_mandate)
        result = engine.check(intent, cart)
        return {"job_id": job_id, "result": result.model_dump()}


# Default app instance for uvicorn
app = create_app()
