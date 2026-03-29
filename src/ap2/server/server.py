"""AP2-ARS FastAPI application: base ARS endpoints + AP2 mandate + x402."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request

from abstract_ars.crypto import compute_agreement_hash, verify_envelope_signature
from abstract_ars.errors import AuthError, BadRequestError, ConflictError, NotFoundError
from abstract_ars.models import CreateJobRequest, SignedActionEnvelope
from abstract_ars.routes import create_shared_router, make_append_validated, verify_sig
from abstract_ars.store import EventStore

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
    db_path: str = "ap2.db", settlement: Optional[SettlementLayer] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.store = EventStore(db_path=db_path)
        application.state.settlement = settlement or MockSettlementLayer()
        application.state.constraint_engine = ConstraintEngine()
        yield

    application = FastAPI(title="AP2-ARS", version="0.1.0", lifespan=lifespan)

    # Shared routes (proposals, signatures, deliverable, evaluate, UW, GET, etc.)
    shared = create_shared_router(
        derive_state=derive_ap2_job_state,
        validate_transition=validate_ap2_transition,
        validate_agreement_draft=lambda d: AP2AgreementDraft(**d),
        get_store=_store,
        event_types={m.name: m.value for m in AP2EventType},
    )
    # Override routes first (take precedence over shared routes)
    _register_override_routes(application)

    application.include_router(shared)

    # AP2-only routes (mandates, constraints)
    _register_mandate_routes(application)

    return application


def _store(request: Request) -> EventStore:
    return request.app.state.store


def _settlement(request: Request) -> SettlementLayer:
    return request.app.state.settlement


def _constraint_engine(request: Request) -> ConstraintEngine:
    return request.app.state.constraint_engine


# Reusable _append_validated for mandate routes
_append_validated = make_append_validated(
    derive_ap2_job_state, validate_ap2_transition,
)


# ── Override routes (AP2-specific settlement) ────────────────────────────────


def _register_override_routes(application: FastAPI) -> None:
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

    @application.post("/jobs/{job_id}/fee/lock")
    async def lock_fee(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != AP2EventType.FEE_ESCROW_LOCKED.value:
            raise BadRequestError("Expected type FEE_ESCROW_LOCKED")

        verify_sig(envelope)
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
            _cart = CartMandate(**state.cart_mandate)
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

        verify_sig(envelope)
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

        # Auto-handle collateral based on verdict
        collateral_result = None
        if state.collateral_ref:
            if action == "release":
                collateral_result = await sl.unlock_collateral(job_id)
            else:
                collateral_result = await sl.slash_collateral(
                    job_id, state.agreement.user_pubkey,
                )

        payload = {**envelope.payload, "settlement_ref": result.ref}
        if collateral_result:
            payload["collateral_settlement_ref"] = collateral_result.ref
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)

        events = store.get_events(job_id)
        new_state = derive_ap2_job_state(events)
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

    @application.post("/jobs/{job_id}/uw/premium")
    async def pay_premium(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if envelope.type != AP2EventType.PREMIUM_PAID.value:
            raise BadRequestError("Expected type PREMIUM_PAID")

        verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_ap2_job_state(events)
        validate_ap2_transition(state, envelope)

        assert state.agreement and state.uw_decision
        premium_amount = int(state.uw_decision.get("premium") or 0)

        sl = _settlement(request)
        result = await sl.pay_premium(
            job_id,
            premium_amount,
            state.agreement.fee.currency,
            payer_addr=state.agreement.user_pubkey,
            payee_addr=state.agreement.underwriter_pubkey or "",
        )

        payload = {**envelope.payload, "premium_ref": result.ref}
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)

        events = store.get_events(job_id)
        new_state = derive_ap2_job_state(events)
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "premium_ref": result.ref,
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

        verify_sig(envelope)
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

    @application.post("/jobs/{job_id}/principal/release")
    async def release_principal(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if envelope.type != AP2EventType.PRINCIPAL_RELEASED.value:
            raise BadRequestError("Expected type PRINCIPAL_RELEASED")

        verify_sig(envelope)
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
        }
        envelope = envelope.model_copy(update={"payload": payload})
        store.append_event(envelope)
        return {"job_id": job_id, "transfer_ref": result.ref}

    @application.post("/jobs/{job_id}/uw/decide")
    async def uw_decide(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        """AP2 override: UW decide with modality-aware auto-actions."""
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if "approve" not in envelope.payload:
            raise BadRequestError("payload.approve is required")

        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.UW_DECIDED.value,
        )

        resp = {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "approve": envelope.payload["approve"],
        }

        # Auto-actions in human-not-present mode
        if new_state.modality != Modality.HUMAN_NOT_PRESENT:
            return resp
        if not new_state.intent_mandate:
            return resp

        intent = IntentMandate(**new_state.intent_mandate)
        approved = envelope.payload.get("approve", False)
        premium = envelope.payload.get("premium", 0) or 0

        if not approved and intent.allow_uw_override:
            resp["auto_action"] = "override_recommended"
            resp["reason"] = "UW rejected, allow_uw_override=True in intent"

        elif approved and premium > 0 and intent.max_premium is not None:
            if premium <= intent.max_premium:
                resp["auto_action"] = "premium_auto_payable"
                resp["reason"] = f"Premium {premium} ≤ max_premium {intent.max_premium}"
            else:
                resp["auto_action"] = "awaiting_human"
                resp["reason"] = f"Premium {premium} > max_premium {intent.max_premium}"

        elif approved and premium > 0 and intent.max_premium is None:
            resp["auto_action"] = "awaiting_human"
            resp["reason"] = "Premium required but max_premium not set in intent"

        return resp

    @application.post("/jobs/{job_id}/uw/collateral/refuse")
    async def refuse_collateral(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        """AP2 override: collateral refuse with modality-aware auto-actions."""
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        new_state = _append_validated(
            store, job_id, envelope, AP2EventType.COLLATERAL_REFUSED.value,
        )

        resp = {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

        # Auto-actions in human-not-present mode
        if (
            new_state.modality == Modality.HUMAN_NOT_PRESENT
            and new_state.intent_mandate
        ):
            intent = IntentMandate(**new_state.intent_mandate)
            if intent.allow_uw_override:
                resp["auto_action"] = "override_recommended"
                resp["reason"] = "Collateral refused, allow_uw_override=True in intent"
            else:
                resp["auto_action"] = "awaiting_human"
                resp["reason"] = "Collateral refused, allow_uw_override=False"

        return resp


# ── Mandate routes (AP2-only) ────────────────────────────────────────────────


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

        verify_sig(envelope)
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
