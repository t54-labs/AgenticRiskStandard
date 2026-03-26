"""Composite state machine: base ARS fee/principal tracks + AP2 mandate track."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ars.errors import BadRequestError, ConflictError, ForbiddenError
from ars.models import (
    AgreementDraft,
    Event,
    EventType,
    FeeTrackState,
    JobPhase,
    PrincipalTrackState,
    SignedActionEnvelope,
)
from ars.state import derive_job_state, validate_transition

from .models import (
    AP2AgreementDraft,
    AP2Event,
    AP2EventType,
    AP2JobStateView,
    AP2SignedActionEnvelope,
    MandateTrackState,
    Modality,
    is_base_event_type,
)
from .roles import AP2Role, RoleRegistry


# ── Agreement bridging ────────────────────────────────────────────────────────


_AP2_TO_BASE_KEYS = {
    "user_pubkey": "requestor_pubkey",
    "shopping_agent_pubkey": "business_agent_pubkey",
    "payment_processor_pubkey": "settlement_layer_pubkey",
}

_AP2_ONLY_KEYS = {
    "modality",
    "credentials_provider_pubkey",
    "merchant_pubkey",
}


def _to_base_agreement(ap2_dict: dict) -> dict:
    """Convert an AP2AgreementDraft dict to AgreementDraft-compatible dict."""
    base = {}
    for k, v in ap2_dict.items():
        if k in _AP2_ONLY_KEYS:
            continue
        new_key = _AP2_TO_BASE_KEYS.get(k, k)
        base[new_key] = v
    base.setdefault("version", "ars/0.1")
    return base


def _to_base_event(ev: AP2Event, base_agreement_cache: dict) -> Event:
    """Convert an AP2Event to a base ARS Event, bridging agreement fields."""
    payload = ev.payload
    if ev.event_type in ("JOB_CREATED", "PROPOSAL_SUBMITTED"):
        if "agreement" in payload:
            base_agr = _to_base_agreement(payload["agreement"])
            payload = {**payload, "agreement": base_agr}
    return Event(
        event_id=ev.event_id,
        job_id=ev.job_id,
        event_type=EventType(ev.event_type),
        agreement_hash=ev.agreement_hash,
        payload=payload,
        actor=ev.actor,
        signature=ev.signature,
        timestamp=ev.timestamp,
        server_received_at=ev.server_received_at,
    )


# ── Mandate track accumulator ────────────────────────────────────────────────


@dataclass
class _MandateAcc:
    intent_mandate: Optional[dict] = None
    cart_mandate: Optional[dict] = None
    cart_signed: bool = False
    cart_approved: bool = False
    payment_mandate: Optional[dict] = None
    payment_mandate_signed: bool = False
    x402_ref: Optional[str] = None
    x402_settlement_ref: Optional[str] = None
    constraint_violations: list[str] = field(default_factory=list)


def _derive_mandate_track(acc: _MandateAcc) -> Optional[MandateTrackState]:
    if acc.x402_settlement_ref:
        return MandateTrackState.SETTLEMENT_CONFIRMED
    if acc.x402_ref:
        return MandateTrackState.SETTLEMENT_INITIATED
    if acc.payment_mandate_signed:
        return MandateTrackState.PAYMENT_SIGNED
    if acc.payment_mandate:
        return MandateTrackState.PAYMENT_CREATED
    if acc.cart_approved:
        return MandateTrackState.CART_APPROVED
    if acc.cart_signed:
        return MandateTrackState.CART_SIGNED
    if acc.cart_mandate:
        return MandateTrackState.CART_PROPOSED
    if acc.intent_mandate:
        return MandateTrackState.INTENT_CREATED
    return MandateTrackState.MANDATE_NONE


def _replay_mandate_events(events: list[AP2Event]) -> _MandateAcc:
    acc = _MandateAcc()
    for ev in events:
        et = ev.event_type
        if et == AP2EventType.INTENT_MANDATE_CREATED.value:
            acc.intent_mandate = ev.payload
        elif et == AP2EventType.CART_MANDATE_PROPOSED.value:
            acc.cart_mandate = ev.payload
        elif et == AP2EventType.CART_MANDATE_SIGNED.value:
            acc.cart_signed = True
        elif et == AP2EventType.CART_APPROVED_BY_USER.value:
            acc.cart_approved = True
        elif et == AP2EventType.PAYMENT_MANDATE_CREATED.value:
            acc.payment_mandate = ev.payload
        elif et == AP2EventType.PAYMENT_MANDATE_SIGNED.value:
            acc.payment_mandate_signed = True
        elif et == AP2EventType.SETTLEMENT_402_INITIATED.value:
            acc.x402_ref = ev.payload.get("x402_ref")
        elif et == AP2EventType.SETTLEMENT_402_CONFIRMED.value:
            acc.x402_settlement_ref = ev.payload.get("x402_settlement_ref")
    return acc


# ── Public: derive composite state ───────────────────────────────────────────


def derive_ap2_job_state(events: list[AP2Event]) -> AP2JobStateView:
    """Replay all events to compute the full AP2 job state.

    Base ARS events are bridged to ars.state.derive_job_state().
    AP2 mandate events are derived separately.
    Both are merged into AP2JobStateView.
    """
    if not events:
        return AP2JobStateView(job_id="", phase=JobPhase.REQUEST,)

    # Separate base and mandate events
    base_events: list[Event] = []
    for ev in events:
        if is_base_event_type(ev.event_type):
            base_events.append(_to_base_event(ev, {}))

    # Derive base state
    base_state = derive_job_state(base_events) if base_events else None

    # Derive mandate state
    mandate_acc = _replay_mandate_events(events)
    mandate_track = _derive_mandate_track(mandate_acc)

    # Extract AP2 agreement from the first JOB_CREATED event
    ap2_agreement: Optional[AP2AgreementDraft] = None
    modality: Optional[Modality] = None
    for ev in events:
        if ev.event_type == "JOB_CREATED":
            agr_dict = ev.payload.get("agreement", {})
            ap2_agreement = AP2AgreementDraft(**agr_dict)
            modality = ap2_agreement.modality
            break
        elif ev.event_type == "PROPOSAL_SUBMITTED":
            agr_dict = ev.payload.get("agreement", {})
            ap2_agreement = AP2AgreementDraft(**agr_dict)
            modality = ap2_agreement.modality

    # Merge
    if base_state:
        return AP2JobStateView(
            job_id=base_state.job_id,
            phase=base_state.phase,
            fee_track_state=base_state.fee_track_state,
            agreement=ap2_agreement,
            agreement_hash=base_state.agreement_hash,
            signatures=base_state.signatures,
            fee_lock_ref=base_state.fee_lock_ref,
            deliverable_ref=base_state.deliverable_ref,
            evaluation=base_state.evaluation,
            settlement_ref=base_state.settlement_ref,
            settlement_action=base_state.settlement_action,
            created_at=base_state.created_at,
            updated_at=base_state.updated_at,
            event_count=len(events),
            principal_track_state=base_state.principal_track_state,
            uw_decision=base_state.uw_decision,
            premium_ref=base_state.premium_ref,
            collateral_ref=base_state.collateral_ref,
            override=base_state.override,
            release_approvals=base_state.release_approvals,
            transfer_ref=base_state.transfer_ref,
            exec_evidence_ref=base_state.exec_evidence_ref,
            modality=modality,
            mandate_track_state=mandate_track,
            intent_mandate=mandate_acc.intent_mandate,
            cart_mandate=mandate_acc.cart_mandate,
            payment_mandate=mandate_acc.payment_mandate,
            x402_ref=mandate_acc.x402_ref,
            x402_settlement_ref=mandate_acc.x402_settlement_ref,
            constraint_violations=mandate_acc.constraint_violations,
        )

    return AP2JobStateView(
        job_id=events[0].job_id if events else "",
        phase=JobPhase.REQUEST,
        event_count=len(events),
        modality=modality,
        agreement=ap2_agreement,
        mandate_track_state=mandate_track,
        intent_mandate=mandate_acc.intent_mandate,
        cart_mandate=mandate_acc.cart_mandate,
        payment_mandate=mandate_acc.payment_mandate,
        x402_ref=mandate_acc.x402_ref,
        x402_settlement_ref=mandate_acc.x402_settlement_ref,
        constraint_violations=mandate_acc.constraint_violations,
    )


# ── Public: validate transition ──────────────────────────────────────────────


def validate_ap2_transition(
    state: AP2JobStateView, envelope: AP2SignedActionEnvelope,
) -> None:
    """Validate an AP2 state transition.

    For base ARS event types: bridges to ars.state.validate_transition().
    For AP2 mandate events: enforces mandate track rules + role checks.
    """
    et = envelope.type

    # Agreement hash check (all post-creation events)
    if et != AP2EventType.JOB_CREATED.value:
        if state.agreement_hash and envelope.agreement_hash != state.agreement_hash:
            raise BadRequestError("agreement_hash mismatch")

    # Base ARS events — delegate to base validator
    if is_base_event_type(et):
        _validate_base_transition(state, envelope)
        return

    # AP2 mandate events — validate here
    agr = state.agreement
    if agr is None:
        raise ConflictError("No agreement found")

    registry = RoleRegistry(agr)

    if et == AP2EventType.INTENT_MANDATE_CREATED.value:
        if state.phase not in (JobPhase.NEGOTIATION, JobPhase.TRANSACTION):
            raise ConflictError(
                "IntentMandate requires NEGOTIATION or TRANSACTION phase"
            )
        registry.assert_role(envelope.actor, AP2Role.USER)

    elif et == AP2EventType.CART_MANDATE_PROPOSED.value:
        if state.mandate_track_state not in (
            MandateTrackState.INTENT_CREATED,
            MandateTrackState.CART_PROPOSED,  # allow re-proposal
        ):
            raise ConflictError("CartMandate requires an IntentMandate first")
        registry.assert_role(envelope.actor, AP2Role.MERCHANT)

    elif et == AP2EventType.CART_MANDATE_SIGNED.value:
        if state.mandate_track_state != MandateTrackState.CART_PROPOSED:
            raise ConflictError("Cart signing requires CART_PROPOSED state")
        registry.assert_role(envelope.actor, AP2Role.MERCHANT)

    elif et == AP2EventType.CART_APPROVED_BY_USER.value:
        if state.mandate_track_state != MandateTrackState.CART_SIGNED:
            raise ConflictError("Cart approval requires CART_SIGNED state")
        if state.modality != Modality.HUMAN_PRESENT:
            raise ConflictError("Cart approval only in human-present modality")
        registry.assert_role(envelope.actor, AP2Role.USER)

    elif et == AP2EventType.PAYMENT_MANDATE_CREATED.value:
        if state.modality == Modality.HUMAN_PRESENT:
            if state.mandate_track_state != MandateTrackState.CART_APPROVED:
                raise ConflictError(
                    "PaymentMandate requires cart approval in human-present mode"
                )
        else:
            if state.mandate_track_state != MandateTrackState.CART_SIGNED:
                raise ConflictError(
                    "PaymentMandate requires CART_SIGNED in human-not-present mode"
                )
        registry.assert_role(envelope.actor, AP2Role.CREDENTIALS_PROVIDER)

    elif et == AP2EventType.PAYMENT_MANDATE_SIGNED.value:
        if state.mandate_track_state != MandateTrackState.PAYMENT_CREATED:
            raise ConflictError("Payment signing requires PAYMENT_CREATED state")
        if state.modality == Modality.HUMAN_PRESENT:
            registry.assert_role(envelope.actor, AP2Role.USER)
        else:
            # In human-not-present, credentials provider auto-signs
            registry.assert_role(envelope.actor, AP2Role.CREDENTIALS_PROVIDER)

    elif et == AP2EventType.SETTLEMENT_402_INITIATED.value:
        if state.mandate_track_state != MandateTrackState.PAYMENT_SIGNED:
            raise ConflictError("Settlement requires PAYMENT_SIGNED state")
        registry.assert_role(envelope.actor, AP2Role.PAYMENT_PROCESSOR)

    elif et == AP2EventType.SETTLEMENT_402_CONFIRMED.value:
        if state.mandate_track_state != MandateTrackState.SETTLEMENT_INITIATED:
            raise ConflictError("Confirmation requires SETTLEMENT_INITIATED state")
        registry.assert_role(envelope.actor, AP2Role.PAYMENT_PROCESSOR)

    else:
        raise BadRequestError(f"Unknown event type: {et}")


def _validate_base_transition(
    state: AP2JobStateView, envelope: AP2SignedActionEnvelope,
) -> None:
    """Bridge AP2 state to base ARS validation."""
    if state.agreement is None:
        return  # nothing to validate yet

    agr = state.agreement
    base_agr_dict = _to_base_agreement(agr.model_dump())
    base_agreement = AgreementDraft(**base_agr_dict)

    # Build a minimal base JobStateView for validation
    from ars.models import JobStateView

    base_state = JobStateView(
        job_id=state.job_id,
        phase=state.phase,
        fee_track_state=state.fee_track_state,
        agreement=base_agreement,
        agreement_hash=state.agreement_hash,
        signatures=state.signatures,
        fee_lock_ref=state.fee_lock_ref,
        deliverable_ref=state.deliverable_ref,
        evaluation=state.evaluation,
        settlement_ref=state.settlement_ref,
        settlement_action=state.settlement_action,
        created_at=state.created_at,
        updated_at=state.updated_at,
        event_count=state.event_count,
        principal_track_state=state.principal_track_state,
        uw_decision=state.uw_decision,
        premium_ref=state.premium_ref,
        collateral_ref=state.collateral_ref,
        override=state.override,
        release_approvals=state.release_approvals,
        transfer_ref=state.transfer_ref,
        exec_evidence_ref=state.exec_evidence_ref,
    )

    # Build base envelope
    base_envelope = SignedActionEnvelope(
        type=EventType(envelope.type),
        job_id=envelope.job_id,
        agreement_hash=envelope.agreement_hash,
        payload=envelope.payload,
        actor=envelope.actor,
        signature=envelope.signature,
        timestamp=envelope.timestamp,
    )

    validate_transition(base_state, base_envelope)
