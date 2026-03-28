"""VI-ARS FastAPI application: base ARS endpoints + VI credential track."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request

from ars.crypto import compute_agreement_hash, verify_envelope_signature
from ars.errors import AuthError, BadRequestError, ConflictError, NotFoundError
from ars.models import CreateJobRequest, SignedActionEnvelope
from ars.routes import create_shared_router, make_append_validated, verify_sig
from ars.store import EventStore

from .constraints import VIConstraintEngine
from .models import (
    CredentialTrackState,
    VIAgreementDraft,
    VIEventType,
    VIMode,
)
from .roles import VIRoleRegistry
from .settlement import MockSettlementLayer, SettlementLayer
from .state import derive_vi_job_state, validate_vi_transition


# ── App factory ─────────────────────────────────────────────────────────────


def create_app(
    db_path: str = "vi.db", settlement: Optional[SettlementLayer] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.store = EventStore(db_path=db_path)
        application.state.settlement = settlement or MockSettlementLayer()
        application.state.constraint_engine = VIConstraintEngine()
        yield

    application = FastAPI(title="VI-ARS", version="0.1.0", lifespan=lifespan)

    # Shared routes (proposals, signatures, deliverable, evaluate, UW, GET, etc.)
    shared = create_shared_router(
        derive_state=derive_vi_job_state,
        validate_transition=validate_vi_transition,
        validate_agreement_draft=lambda d: VIAgreementDraft(**d),
        get_store=_store,
        event_types={m.name: m.value for m in VIEventType},
    )
    # Override routes first (take precedence over shared routes)
    _register_override_routes(application)

    application.include_router(shared)

    # VI-only routes (credentials, constraints)
    _register_credential_routes(application)

    return application


def _store(request: Request) -> EventStore:
    return request.app.state.store


def _settlement(request: Request) -> SettlementLayer:
    return request.app.state.settlement


def _constraint_engine(request: Request) -> VIConstraintEngine:
    return request.app.state.constraint_engine


# Reusable _append_validated for credential routes
_append_validated = make_append_validated(derive_vi_job_state, validate_vi_transition,)


# ── Override routes (VI-specific settlement) ────────────────────────────────


def _register_override_routes(application: FastAPI) -> None:
    @application.post("/jobs", status_code=201)
    async def create_job(req: CreateJobRequest, request: Request):
        if req.type != "JOB_CREATED":
            raise BadRequestError("Expected type JOB_CREATED")

        agreement_dict = req.payload.get("agreement")
        if not agreement_dict:
            raise BadRequestError("payload.agreement is required")

        agreement = VIAgreementDraft(**agreement_dict)

        if req.actor != agreement.user_pubkey:
            raise BadRequestError("Actor must be the user (requestor)")

        # Enforce agent-credential firewall at creation
        registry = VIRoleRegistry(agreement)
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
            type=VIEventType.JOB_CREATED.value,
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
            "mode": agreement.mode.value,
        }

    @application.post("/jobs/{job_id}/fee/lock")
    async def lock_fee(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != VIEventType.FEE_ESCROW_LOCKED.value:
            raise BadRequestError("Expected type FEE_ESCROW_LOCKED")

        verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_vi_job_state(events)
        validate_vi_transition(state, envelope)

        assert state.agreement is not None
        sl = _settlement(request)

        fee_amount = state.agreement.fee.amount
        fee_currency = state.agreement.fee.currency

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

        if envelope.type != VIEventType.FEE_SETTLED.value:
            raise BadRequestError("Expected type FEE_SETTLED")
        if "action" not in envelope.payload:
            raise BadRequestError("payload.action is required")

        verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_vi_job_state(events)
        validate_vi_transition(state, envelope)

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
        new_state = derive_vi_job_state(events)
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
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if envelope.type != VIEventType.COLLATERAL_LOCKED.value:
            raise BadRequestError("Expected type COLLATERAL_LOCKED")

        verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_vi_job_state(events)
        validate_vi_transition(state, envelope)

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
        if envelope.type != VIEventType.PRINCIPAL_RELEASED.value:
            raise BadRequestError("Expected type PRINCIPAL_RELEASED")

        verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_vi_job_state(events)
        validate_vi_transition(state, envelope)

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
        """VI override: UW decide with mode-aware auto-actions."""
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        if "approve" not in envelope.payload:
            raise BadRequestError("payload.approve is required")

        new_state = _append_validated(
            store, job_id, envelope, VIEventType.UW_DECIDED.value,
        )

        resp = {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "approve": envelope.payload["approve"],
        }

        # Auto-actions in autonomous mode
        if new_state.mode != VIMode.AUTONOMOUS:
            return resp
        if not new_state.agreement:
            return resp

        approved = envelope.payload.get("approve", False)
        premium = envelope.payload.get("premium", 0) or 0

        if not approved and new_state.agreement.allow_uw_override:
            resp["auto_action"] = "override_recommended"
            resp["reason"] = "UW rejected, allow_uw_override=True in agreement"

        elif approved and premium > 0 and new_state.agreement.max_premium is not None:
            if premium <= new_state.agreement.max_premium:
                resp["auto_action"] = "premium_auto_payable"
                resp[
                    "reason"
                ] = f"Premium {premium} <= max_premium {new_state.agreement.max_premium}"
            else:
                resp["auto_action"] = "awaiting_human"
                resp[
                    "reason"
                ] = f"Premium {premium} > max_premium {new_state.agreement.max_premium}"

        elif approved and premium > 0 and new_state.agreement.max_premium is None:
            resp["auto_action"] = "awaiting_human"
            resp["reason"] = "Premium required but max_premium not set in agreement"

        return resp

    @application.post("/jobs/{job_id}/uw/collateral/refuse")
    async def refuse_collateral(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        """VI override: collateral refuse with mode-aware auto-actions."""
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        new_state = _append_validated(
            store, job_id, envelope, VIEventType.COLLATERAL_REFUSED.value,
        )

        resp = {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

        # Auto-actions in autonomous mode
        if new_state.mode == VIMode.AUTONOMOUS and new_state.agreement:
            if new_state.agreement.allow_uw_override:
                resp["auto_action"] = "override_recommended"
                resp[
                    "reason"
                ] = "Collateral refused, allow_uw_override=True in agreement"
            else:
                resp["auto_action"] = "awaiting_human"
                resp["reason"] = "Collateral refused, allow_uw_override=False"

        return resp


# ── Credential routes (VI-only) ─────────────────────────────────────────────


def _register_credential_routes(application: FastAPI) -> None:
    @application.post("/jobs/{job_id}/credentials/l1")
    async def issue_l1(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, VIEventType.L1_CREDENTIAL_ISSUED.value,
        )
        return {
            "job_id": job_id,
            "credential_track_state": new_state.credential_track_state.value
            if new_state.credential_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/credentials/l2")
    async def create_l2(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, VIEventType.L2_MANDATE_CREATED.value,
        )
        return {
            "job_id": job_id,
            "credential_track_state": new_state.credential_track_state.value
            if new_state.credential_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/credentials/l2/verify")
    async def verify_l2(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, VIEventType.L2_MANDATE_VERIFIED.value,
        )
        return {
            "job_id": job_id,
            "credential_track_state": new_state.credential_track_state.value
            if new_state.credential_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/credentials/l3a")
    async def create_l3a(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, VIEventType.L3A_PAYMENT_CREATED.value,
        )
        return {
            "job_id": job_id,
            "credential_track_state": new_state.credential_track_state.value
            if new_state.credential_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/credentials/l3b")
    async def create_l3b(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, VIEventType.L3B_CHECKOUT_CREATED.value,
        )
        return {
            "job_id": job_id,
            "credential_track_state": new_state.credential_track_state.value
            if new_state.credential_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/credentials/l3/verify")
    async def verify_chain(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        """Verify the full L1 → L2 → L3a + L3b chain.

        In autonomous mode, also checks constraints.
        """
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != VIEventType.L3_CHAIN_VERIFIED.value:
            raise BadRequestError("Expected type L3_CHAIN_VERIFIED")

        verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_vi_job_state(events)
        validate_vi_transition(state, envelope)

        # Check constraints in autonomous mode
        constraint_check = None
        if (
            state.mode == VIMode.AUTONOMOUS
            and state.l2_mandate
            and state.l3a_payment
            and state.l3b_checkout
        ):
            engine = _constraint_engine(request)
            constraints = state.l2_mandate.get("constraints", {})
            result = engine.check(constraints, state.l3a_payment, state.l3b_checkout)
            constraint_check = result.model_dump()

        store.append_event(envelope)

        events = store.get_events(job_id)
        new_state = derive_vi_job_state(events)
        resp = {
            "job_id": job_id,
            "credential_track_state": new_state.credential_track_state.value
            if new_state.credential_track_state
            else None,
        }
        if constraint_check is not None:
            resp["constraint_check"] = constraint_check
        return resp

    @application.post("/jobs/{job_id}/credentials/settlement/initiate")
    async def initiate_settlement(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, VIEventType.SETTLEMENT_VI_INITIATED.value,
        )
        return {
            "job_id": job_id,
            "credential_track_state": new_state.credential_track_state.value
            if new_state.credential_track_state
            else None,
        }

    @application.post("/jobs/{job_id}/credentials/settlement/confirm")
    async def confirm_settlement(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        new_state = _append_validated(
            store, job_id, envelope, VIEventType.SETTLEMENT_VI_CONFIRMED.value,
        )
        return {
            "job_id": job_id,
            "credential_track_state": new_state.credential_track_state.value
            if new_state.credential_track_state
            else None,
        }

    @application.get("/jobs/{job_id}/credentials")
    async def get_credentials(job_id: str, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        state = derive_vi_job_state(events)
        return {
            "job_id": job_id,
            "credential_track_state": state.credential_track_state.value
            if state.credential_track_state
            else None,
            "l1_credential": state.l1_credential,
            "l2_mandate": state.l2_mandate,
            "l3a_payment": state.l3a_payment,
            "l3b_checkout": state.l3b_checkout,
            "l3_chain_verified": state.l3_chain_verified,
        }

    @application.get("/jobs/{job_id}/credentials/present/merchant")
    async def present_to_merchant(job_id: str, request: Request):
        """Selective presentation: only checkout-related disclosures."""
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        state = derive_vi_job_state(events)
        return {
            "job_id": job_id,
            "l1_credential": state.l1_credential,
            "l3b_checkout": state.l3b_checkout,
            "presentation_type": "merchant",
        }

    @application.get("/jobs/{job_id}/credentials/present/network")
    async def present_to_network(job_id: str, request: Request):
        """Selective presentation: only payment-related disclosures."""
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        state = derive_vi_job_state(events)
        return {
            "job_id": job_id,
            "l1_credential": state.l1_credential,
            "l3a_payment": state.l3a_payment,
            "presentation_type": "network",
        }

    @application.get("/jobs/{job_id}/constraints/check")
    async def check_constraints(job_id: str, request: Request):
        store = _store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        state = derive_vi_job_state(events)
        if not state.l2_mandate:
            return {"job_id": job_id, "result": None, "reason": "Missing L2 mandate"}
        if not state.l3a_payment and not state.l3b_checkout:
            return {
                "job_id": job_id,
                "result": None,
                "reason": "Missing L3 credentials",
            }
        engine = _constraint_engine(request)
        constraints = state.l2_mandate.get("constraints", {})
        result = engine.check(constraints, state.l3a_payment, state.l3b_checkout)
        return {"job_id": job_id, "result": result.model_dump()}


# Default app instance for uvicorn
app = create_app()
