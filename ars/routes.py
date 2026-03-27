"""Shared APIRouter factory for base ARS and concrete implementations."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Request

from .crypto import compute_agreement_hash, envelope_body, verify_envelope_signature
from .errors import AuthError, BadRequestError, NotFoundError
from .models import SignedActionEnvelope
from .store import EventStore


# ── Shared helpers ────────────────────────────────────────────────────────────


def verify_sig(envelope: SignedActionEnvelope) -> None:
    """Verify Ed25519 signature on a signed envelope."""
    body = envelope_body(envelope.model_dump())
    if not verify_envelope_signature(envelope.actor, body, envelope.signature):
        raise AuthError()


def make_append_validated(
    derive_state: Callable, validate_transition: Callable,
) -> Callable:
    """Build a reusable _append_validated function closed over state/validation fns."""

    def _append_validated(
        store: EventStore,
        job_id: str,
        envelope: SignedActionEnvelope,
        expected_type: str,
        extra_payload: dict | None = None,
    ) -> Any:
        if envelope.type != expected_type:
            raise BadRequestError(f"Expected type {expected_type}")

        verify_sig(envelope)
        envelope = envelope.model_copy(update={"job_id": job_id})

        events = store.get_events(job_id)
        state = derive_state(events)
        validate_transition(state, envelope)

        if extra_payload:
            payload = {**envelope.payload, **extra_payload}
            envelope = envelope.model_copy(update={"payload": payload})

        store.append_event(envelope)

        events = store.get_events(job_id)
        return derive_state(events)

    return _append_validated


# ── Router factory ────────────────────────────────────────────────────────────


def create_shared_router(
    *,
    derive_state: Callable,
    validate_transition: Callable,
    validate_agreement_draft: Callable[[dict], None],
    get_store: Callable[[Request], EventStore],
    event_types: dict[str, str],
) -> APIRouter:
    """Create an APIRouter with the 14 routes shared between ars/ and ap2_ars/.

    Parameters:
        derive_state: (events) -> JobStateView — state derivation function
        validate_transition: (state, envelope) -> None — transition validator
        validate_agreement_draft: (dict) -> None — validates agreement dict (raises on invalid)
        get_store: (Request) -> EventStore — extracts the event store from request
        event_types: dict mapping event names to string values
    """
    router = APIRouter()
    _append = make_append_validated(derive_state, validate_transition)

    # ── Proposals ─────────────────────────────────────────────────────────

    @router.post("/jobs/{job_id}/proposals")
    async def propose_agreement(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if envelope.type != event_types["PROPOSAL_SUBMITTED"]:
            raise BadRequestError("Expected type PROPOSAL_SUBMITTED")

        agreement_dict = envelope.payload.get("agreement")
        if not agreement_dict:
            raise BadRequestError("payload.agreement is required")
        validate_agreement_draft(agreement_dict)

        verify_sig(envelope)

        agr_hash = compute_agreement_hash(agreement_dict)
        envelope = envelope.model_copy(
            update={"job_id": job_id, "agreement_hash": agr_hash},
        )

        events = store.get_events(job_id)
        state = derive_state(events)
        validate_transition(state, envelope)

        store.append_event(envelope)
        return {"job_id": job_id, "agreement_hash": agr_hash}

    # ── Signatures ────────────────────────────────────────────────────────

    @router.post("/jobs/{job_id}/signatures")
    async def sign_agreement(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        new_state = _append(store, job_id, envelope, event_types["AGREEMENT_SIGNED"],)
        return {
            "job_id": job_id,
            "phase": new_state.phase.value,
            "signatures": new_state.signatures,
        }

    # ── Deliverable ───────────────────────────────────────────────────────

    @router.post("/jobs/{job_id}/deliverable")
    async def submit_deliverable(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if not envelope.payload.get("deliverable_ref"):
            raise BadRequestError("payload.deliverable_ref is required")

        _append(
            store, job_id, envelope, event_types["DELIVERABLE_SUBMITTED"],
        )
        return {
            "job_id": job_id,
            "fee_track_state": "FEE_DELIVERED",
            "deliverable_ref": envelope.payload["deliverable_ref"],
        }

    # ── Evaluate ──────────────────────────────────────────────────────────

    @router.post("/jobs/{job_id}/evaluate")
    async def evaluate_outcome(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if "verdict" not in envelope.payload:
            raise BadRequestError("payload.verdict is required")

        _append(
            store, job_id, envelope, event_types["OUTCOME_EVALUATED"],
        )
        return {
            "job_id": job_id,
            "phase": "EVALUATION",
            "verdict": envelope.payload["verdict"],
        }

    # ── UW / Principal track ──────────────────────────────────────────────

    @router.post("/jobs/{job_id}/uw/request")
    async def request_uw(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        new_state = _append(store, job_id, envelope, event_types["UW_REQUESTED"],)
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

    @router.post("/jobs/{job_id}/uw/decide")
    async def uw_decide(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if "approve" not in envelope.payload:
            raise BadRequestError("payload.approve is required")

        new_state = _append(store, job_id, envelope, event_types["UW_DECIDED"],)
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "approve": envelope.payload["approve"],
        }

    @router.post("/jobs/{job_id}/uw/premium")
    async def pay_premium(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        premium_ref = envelope.payload.get("premium_ref")
        if not premium_ref:
            raise BadRequestError("payload.premium_ref is required")

        new_state = _append(store, job_id, envelope, event_types["PREMIUM_PAID"],)
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "premium_ref": premium_ref,
        }

    @router.post("/jobs/{job_id}/uw/premium/refuse")
    async def refuse_premium(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        new_state = _append(store, job_id, envelope, event_types["PREMIUM_REFUSED"],)
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

    @router.post("/jobs/{job_id}/uw/collateral/refuse")
    async def refuse_collateral(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        new_state = _append(store, job_id, envelope, event_types["COLLATERAL_REFUSED"],)
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

    @router.post("/jobs/{job_id}/uw/override")
    async def override_decision(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if "decision" not in envelope.payload:
            raise BadRequestError("payload.decision is required")

        new_state = _append(store, job_id, envelope, event_types["OVERRIDE_DECIDED"],)
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "decision": envelope.payload["decision"],
        }

    @router.post("/jobs/{job_id}/release/approve")
    async def approve_release(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        new_state = _append(store, job_id, envelope, event_types["RELEASE_APPROVED"],)
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
        }

    @router.post("/jobs/{job_id}/execution-evidence")
    async def submit_execution_evidence(
        job_id: str, envelope: SignedActionEnvelope, request: Request,
    ):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")

        if not envelope.payload.get("exec_evidence_ref"):
            raise BadRequestError("payload.exec_evidence_ref is required")

        new_state = _append(
            store, job_id, envelope, event_types["EXECUTION_EVIDENCE_SUBMITTED"],
        )
        return {
            "job_id": job_id,
            "principal_track_state": new_state.principal_track_state.value
            if new_state.principal_track_state
            else None,
            "exec_evidence_ref": envelope.payload["exec_evidence_ref"],
        }

    # ── GET endpoints ─────────────────────────────────────────────────────

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str, request: Request):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        state = derive_state(events)
        return state.model_dump()

    @router.get("/jobs/{job_id}/events")
    async def get_events(job_id: str, request: Request):
        store = get_store(request)
        if not store.job_exists(job_id):
            raise NotFoundError(f"Job {job_id} not found")
        events = store.get_events(job_id)
        return {"job_id": job_id, "events": [e.model_dump() for e in events]}

    return router
