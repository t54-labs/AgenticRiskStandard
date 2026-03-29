"""Composite state machine: base ARS fee/principal tracks + AP2 mandate track."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from abstract_ars.errors import BadRequestError, ConflictError
from abstract_ars.models import (
    AgreementDraft,
    Event,
    JobPhase,
    JobStateView,
    SignedActionEnvelope,
)
from abstract_ars.state import derive_job_state, validate_transition

from .models import (
    AP2AgreementDraft,
    AP2EventType,
    AP2JobStateView,
    MandateTrackState,
    Modality,
    is_base_event_type,
)
from .roles import AP2Role, RoleRegistry


# ── Agreement bridging ────────────────────────────────────────────────────────


_AP2_TO_BASE_KEYS = {
    "user_pubkey": "requestor_pubkey",
    "merchant_pubkey": "business_agent_pubkey",
    "payment_processor_pubkey": "settlement_layer_pubkey",
}

_AP2_ONLY_KEYS = {
    "modality",
    "credentials_provider_pubkey",
    "shopping_agent_pubkey",
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


def _bridge_event_for_base(ev: Event) -> Event:
    """Bridge an AP2 event's agreement payload to base ARS format."""
    if ev.event_type in ("JOB_CREATED", "PROPOSAL_SUBMITTED"):
        if "agreement" in ev.payload:
            base_agr = _to_base_agreement(ev.payload["agreement"])
            return Event(
                event_id=ev.event_id,
                job_id=ev.job_id,
                event_type=ev.event_type,
                agreement_hash=ev.agreement_hash,
                payload={**ev.payload, "agreement": base_agr},
                actor=ev.actor,
                signature=ev.signature,
                timestamp=ev.timestamp,
                server_received_at=ev.server_received_at,
            )
    return ev


# ── Mandate track accumulator ────────────────────────────────────────────────


@dataclass
class _MandateAcc:
    intent_mandate: Optional[dict] = None
    cart_mandate: Optional[dict] = None
    cart_signed: bool = False
    cart_approved: bool = False
    payment_mandate: Optional[dict] = None
    payment_mandate_signed: bool = False
    constraint_violations: list[str] = field(default_factory=list)


def _derive_mandate_track(acc: _MandateAcc) -> Optional[MandateTrackState]:
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


def _replay_mandate_events(events: list[Event]) -> _MandateAcc:
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
    return acc


# ── Public: derive composite state ───────────────────────────────────────────


def derive_ap2_job_state(events: list[Event]) -> AP2JobStateView:
    """Replay all events to compute the full AP2 job state.

    Base ARS events are bridged and passed to ars.state.derive_job_state().
    AP2 mandate events are derived separately.
    Both are merged into AP2JobStateView.
    """
    if not events:
        return AP2JobStateView(job_id="", phase=JobPhase.REQUEST)

    # Bridge base events (convert AP2 agreement fields to base format)
    base_events = [
        _bridge_event_for_base(ev) for ev in events if is_base_event_type(ev.event_type)
    ]

    # Derive base state
    base_state = derive_job_state(base_events) if base_events else None

    # Derive mandate state
    mandate_acc = _replay_mandate_events(events)
    mandate_track = _derive_mandate_track(mandate_acc)

    # Extract AP2 agreement
    ap2_agreement: Optional[AP2AgreementDraft] = None
    modality: Optional[Modality] = None
    for ev in events:
        if ev.event_type in ("JOB_CREATED", "PROPOSAL_SUBMITTED"):
            agr_dict = ev.payload.get("agreement", {})
            ap2_agreement = AP2AgreementDraft(**agr_dict)
            modality = ap2_agreement.modality
            if ev.event_type == "JOB_CREATED":
                break

    # Merge base + mandate into AP2JobStateView
    _override_keys = {"event_count", "agreement"}
    if base_state:
        return AP2JobStateView(
            **{
                k: v
                for k, v in base_state.model_dump().items()
                if k in JobStateView.model_fields and k not in _override_keys
            },
            event_count=len(events),
            agreement=ap2_agreement,
            modality=modality,
            mandate_track_state=mandate_track,
            intent_mandate=mandate_acc.intent_mandate,
            cart_mandate=mandate_acc.cart_mandate,
            payment_mandate=mandate_acc.payment_mandate,
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
        constraint_violations=mandate_acc.constraint_violations,
    )


# ── Public: validate transition ──────────────────────────────────────────────


def validate_ap2_transition(
    state: AP2JobStateView, envelope: SignedActionEnvelope,
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
        _mandate_active = (
            state.mandate_track_state is not None
            and state.mandate_track_state != MandateTrackState.MANDATE_NONE
        )
        _mandate_complete = (
            state.mandate_track_state == MandateTrackState.PAYMENT_SIGNED
        )
        _requires_principal = bool(
            state.intent_mandate and state.intent_mandate.get("requires_principal")
        )

        # Gate fee lock on mandate completion (when mandate exists)
        if et == AP2EventType.FEE_ESCROW_LOCKED.value:
            if _mandate_active and not _mandate_complete:
                raise ConflictError(
                    "Fee lock requires mandate to be completed (PAYMENT_SIGNED)"
                )

        # Gate UW request on mandate's requires_principal flag
        if et == AP2EventType.UW_REQUESTED.value:
            if _mandate_active and not _mandate_complete:
                raise ConflictError(
                    "UW request requires mandate to be completed (PAYMENT_SIGNED)"
                )
            if _mandate_active and not _requires_principal:
                raise ConflictError(
                    "UW request blocked: intent mandate has requires_principal=False"
                )

        # Gate OVERRIDE_DECIDED in HNP mode on allow_uw_override
        if et == AP2EventType.OVERRIDE_DECIDED.value:
            if (
                state.modality == Modality.HUMAN_NOT_PRESENT
                and state.intent_mandate
                and not state.intent_mandate.get("allow_uw_override", False)
            ):
                raise ConflictError(
                    "Override blocked in human-not-present mode: "
                    "intent mandate has allow_uw_override=False"
                )

        # Gate PREMIUM_PAID in HNP mode on max_premium
        if et == AP2EventType.PREMIUM_PAID.value:
            if state.modality == Modality.HUMAN_NOT_PRESENT and state.intent_mandate:
                max_prem = state.intent_mandate.get("max_premium")
                uw_premium = (
                    state.uw_decision.get("premium", 0) if state.uw_decision else 0
                ) or 0
                if max_prem is None:
                    raise ConflictError(
                        "Premium payment blocked in human-not-present mode: "
                        "max_premium not set in intent mandate"
                    )
                if uw_premium > max_prem:
                    raise ConflictError(
                        f"Premium payment blocked: premium {uw_premium} "
                        f"exceeds max_premium {max_prem} in intent mandate"
                    )

        _validate_base_transition(state, envelope)
        return

    # AP2 mandate events
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
            MandateTrackState.CART_PROPOSED,
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
            registry.assert_role(envelope.actor, AP2Role.CREDENTIALS_PROVIDER)

    else:
        raise BadRequestError(f"Unknown event type: {et}")


def _validate_base_transition(
    state: AP2JobStateView, envelope: SignedActionEnvelope,
) -> None:
    """Bridge AP2 state to base ARS validation."""
    if state.agreement is None:
        return

    agr = state.agreement
    base_agr_dict = _to_base_agreement(agr.model_dump())

    # Build base JobStateView using dict filtering
    base_fields = {
        k: v for k, v in state.model_dump().items() if k in JobStateView.model_fields
    }
    base_fields["agreement"] = base_agr_dict
    base_state = JobStateView(**base_fields)

    validate_transition(base_state, envelope)
