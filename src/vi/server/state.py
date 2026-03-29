"""Composite state machine: base ARS fee/principal tracks + VI credential track."""

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
    CredentialTrackState,
    VIAgreementDraft,
    VIEventType,
    VIJobStateView,
    VIMode,
    is_base_event_type,
)
from .roles import VIRole, VIRoleRegistry


# ── Agreement bridging ───────────────────────────────────────────────────────


_VI_TO_BASE_KEYS = {
    "user_pubkey": "requestor_pubkey",
    "merchant_pubkey": "business_agent_pubkey",
    "payment_network_pubkey": "settlement_layer_pubkey",
}

_VI_ONLY_KEYS = {
    "mode",
    "credential_provider_pubkey",
    "agent_pubkey",
    "user_jwk",
    "agent_jwk",
    "credential_provider_jwk",
    "merchant_jwk",
    "payment_network_jwk",
    "requires_principal",
    "max_premium",
    "allow_uw_override",
}


def _to_base_agreement(vi_dict: dict) -> dict:
    """Convert a VIAgreementDraft dict to AgreementDraft-compatible dict."""
    base = {}
    for k, v in vi_dict.items():
        if k in _VI_ONLY_KEYS:
            continue
        new_key = _VI_TO_BASE_KEYS.get(k, k)
        base[new_key] = v
    base.setdefault("version", "ars/0.1")
    return base


def _bridge_event_for_base(ev: Event) -> Event:
    """Bridge a VI event's agreement payload to base ARS format."""
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


# ── Credential track accumulator ────────────────────────────────────────────


@dataclass
class _CredentialAcc:
    l1_credential: Optional[str] = None
    l2_mandate: Optional[dict] = None
    l2_mode: Optional[VIMode] = None
    l2_verified: bool = False
    l3a_payment: Optional[dict] = None
    l3b_checkout: Optional[dict] = None
    l3_chain_verified: bool = False
    settlement_vi_ref: Optional[str] = None
    settlement_vi_confirmed: bool = False
    constraint_violations: list[str] = field(default_factory=list)


def _derive_credential_track(acc: _CredentialAcc) -> Optional[CredentialTrackState]:
    if acc.settlement_vi_confirmed:
        return CredentialTrackState.SETTLEMENT_CONFIRMED
    if acc.settlement_vi_ref:
        return CredentialTrackState.SETTLEMENT_INITIATED
    if acc.l3_chain_verified:
        return CredentialTrackState.L3_CHAIN_VERIFIED
    if acc.l3b_checkout:
        return CredentialTrackState.L3B_CREATED
    if acc.l3a_payment:
        return CredentialTrackState.L3A_CREATED
    if acc.l2_verified:
        return CredentialTrackState.L2_VERIFIED
    if acc.l2_mandate:
        return CredentialTrackState.L2_CREATED
    if acc.l1_credential:
        return CredentialTrackState.L1_ISSUED
    return CredentialTrackState.CREDENTIAL_NONE


def _replay_credential_events(events: list[Event]) -> _CredentialAcc:
    acc = _CredentialAcc()
    for ev in events:
        et = ev.event_type
        if et == VIEventType.L1_CREDENTIAL_ISSUED.value:
            acc.l1_credential = ev.payload.get("l1_serialized")
        elif et == VIEventType.L2_MANDATE_CREATED.value:
            acc.l2_mandate = ev.payload
            acc.l2_mode = VIMode(ev.payload.get("mode", "autonomous"))
        elif et == VIEventType.L2_MANDATE_VERIFIED.value:
            acc.l2_verified = True
        elif et == VIEventType.L3A_PAYMENT_CREATED.value:
            acc.l3a_payment = ev.payload
        elif et == VIEventType.L3B_CHECKOUT_CREATED.value:
            acc.l3b_checkout = ev.payload
        elif et == VIEventType.L3_CHAIN_VERIFIED.value:
            acc.l3_chain_verified = True
        elif et == VIEventType.SETTLEMENT_VI_INITIATED.value:
            acc.settlement_vi_ref = ev.payload.get("settlement_ref")
        elif et == VIEventType.SETTLEMENT_VI_CONFIRMED.value:
            acc.settlement_vi_confirmed = True
    return acc


# ── Public: derive composite state ──────────────────────────────────────────


def derive_vi_job_state(events: list[Event]) -> VIJobStateView:
    """Replay all events to compute the full VI job state.

    Base ARS events are bridged and passed to ars.state.derive_job_state().
    VI credential events are derived separately.
    Both are merged into VIJobStateView.
    """
    if not events:
        return VIJobStateView(job_id="", phase=JobPhase.REQUEST)

    # Bridge base events (convert VI agreement fields to base format)
    base_events = [
        _bridge_event_for_base(ev) for ev in events if is_base_event_type(ev.event_type)
    ]

    # Derive base state
    base_state = derive_job_state(base_events) if base_events else None

    # Derive credential state
    cred_acc = _replay_credential_events(events)
    cred_track = _derive_credential_track(cred_acc)

    # Extract VI agreement
    vi_agreement: Optional[VIAgreementDraft] = None
    mode: Optional[VIMode] = None
    for ev in events:
        if ev.event_type in ("JOB_CREATED", "PROPOSAL_SUBMITTED"):
            agr_dict = ev.payload.get("agreement", {})
            vi_agreement = VIAgreementDraft(**agr_dict)
            mode = vi_agreement.mode
            if ev.event_type == "JOB_CREATED":
                break

    # Merge base + credential into VIJobStateView
    _override_keys = {"event_count", "agreement"}
    if base_state:
        return VIJobStateView(
            **{
                k: v
                for k, v in base_state.model_dump().items()
                if k in JobStateView.model_fields and k not in _override_keys
            },
            event_count=len(events),
            agreement=vi_agreement,
            mode=mode,
            credential_track_state=cred_track,
            l1_credential=cred_acc.l1_credential,
            l2_mandate=cred_acc.l2_mandate,
            l3a_payment=cred_acc.l3a_payment,
            l3b_checkout=cred_acc.l3b_checkout,
            l3_chain_verified=cred_acc.l3_chain_verified,
            constraint_violations=cred_acc.constraint_violations,
        )

    return VIJobStateView(
        job_id=events[0].job_id if events else "",
        phase=JobPhase.REQUEST,
        event_count=len(events),
        mode=mode,
        agreement=vi_agreement,
        credential_track_state=cred_track,
        l1_credential=cred_acc.l1_credential,
        l2_mandate=cred_acc.l2_mandate,
        l3a_payment=cred_acc.l3a_payment,
        l3b_checkout=cred_acc.l3b_checkout,
        l3_chain_verified=cred_acc.l3_chain_verified,
        constraint_violations=cred_acc.constraint_violations,
    )


# ── Public: validate transition ─────────────────────────────────────────────


def validate_vi_transition(
    state: VIJobStateView, envelope: SignedActionEnvelope,
) -> None:
    """Validate a VI state transition.

    For base ARS event types: bridges to ars.state.validate_transition().
    For VI credential events: enforces credential track rules + role checks.
    """
    et = envelope.type

    # Agreement hash check (all post-creation events)
    if et != VIEventType.JOB_CREATED.value:
        if state.agreement_hash and envelope.agreement_hash != state.agreement_hash:
            raise BadRequestError("agreement_hash mismatch")

    # Base ARS events — delegate to base validator with credential gates
    if is_base_event_type(et):
        _cred_active = (
            state.credential_track_state is not None
            and state.credential_track_state != CredentialTrackState.CREDENTIAL_NONE
        )

        # Determine if credential track is "complete" for fee gating
        if state.mode == VIMode.IMMEDIATE:
            _cred_complete = (
                state.credential_track_state == CredentialTrackState.L2_VERIFIED
                or state.credential_track_state
                in (
                    CredentialTrackState.SETTLEMENT_INITIATED,
                    CredentialTrackState.SETTLEMENT_CONFIRMED,
                )
            )
        else:
            _cred_complete = (
                state.credential_track_state == CredentialTrackState.L3_CHAIN_VERIFIED
                or state.credential_track_state
                in (
                    CredentialTrackState.SETTLEMENT_INITIATED,
                    CredentialTrackState.SETTLEMENT_CONFIRMED,
                )
            )

        _requires_principal = bool(
            state.agreement and state.agreement.requires_principal
        )

        # Gate fee lock on credential track completion
        if et == VIEventType.FEE_ESCROW_LOCKED.value:
            if _cred_active and not _cred_complete:
                raise ConflictError("Fee lock requires credential chain to be verified")

        # Gate UW request on requires_principal flag
        if et == VIEventType.UW_REQUESTED.value:
            if _cred_active and not _cred_complete:
                raise ConflictError(
                    "UW request requires credential chain to be verified"
                )
            if _cred_active and not _requires_principal:
                raise ConflictError(
                    "UW request blocked: agreement has requires_principal=False"
                )

        # Gate OVERRIDE_DECIDED on allow_uw_override
        if et == VIEventType.OVERRIDE_DECIDED.value:
            if (
                state.mode == VIMode.AUTONOMOUS
                and state.agreement
                and not state.agreement.allow_uw_override
            ):
                raise ConflictError(
                    "Override blocked in autonomous mode: "
                    "agreement has allow_uw_override=False"
                )

        # Gate PREMIUM_PAID on max_premium
        if et == VIEventType.PREMIUM_PAID.value:
            if state.mode == VIMode.AUTONOMOUS and state.agreement:
                max_prem = state.agreement.max_premium
                uw_premium = (
                    state.uw_decision.get("premium", 0) if state.uw_decision else 0
                ) or 0
                if max_prem is None:
                    raise ConflictError(
                        "Premium payment blocked in autonomous mode: "
                        "max_premium not set in agreement"
                    )
                if uw_premium > max_prem:
                    raise ConflictError(
                        f"Premium payment blocked: premium {uw_premium} "
                        f"exceeds max_premium {max_prem} in agreement"
                    )

        _validate_base_transition(state, envelope)
        return

    # VI credential events
    agr = state.agreement
    if agr is None:
        raise ConflictError("No agreement found")

    registry = VIRoleRegistry(agr)

    if et == VIEventType.L1_CREDENTIAL_ISSUED.value:
        if state.phase not in (JobPhase.NEGOTIATION, JobPhase.TRANSACTION):
            raise ConflictError("L1 requires NEGOTIATION or TRANSACTION phase")
        registry.assert_role(envelope.actor, VIRole.CREDENTIAL_PROVIDER)

    elif et == VIEventType.L2_MANDATE_CREATED.value:
        if state.credential_track_state != CredentialTrackState.L1_ISSUED:
            raise ConflictError("L2 mandate requires L1 to be issued first")
        registry.assert_role(envelope.actor, VIRole.USER)

    elif et == VIEventType.L2_MANDATE_VERIFIED.value:
        if state.credential_track_state != CredentialTrackState.L2_CREATED:
            raise ConflictError("L2 verification requires L2 to be created first")
        # Any verifier role can verify (credential provider or payment network)
        actor_role = registry.get_role(envelope.actor)
        if actor_role not in (VIRole.CREDENTIAL_PROVIDER, VIRole.PAYMENT_NETWORK):
            raise ConflictError(
                "Only credential_provider or payment_network can verify L2"
            )

    elif et == VIEventType.L3A_PAYMENT_CREATED.value:
        if state.mode != VIMode.AUTONOMOUS:
            raise ConflictError("L3a only allowed in autonomous mode")
        if state.credential_track_state not in (
            CredentialTrackState.L2_VERIFIED,
            CredentialTrackState.L3B_CREATED,
        ):
            raise ConflictError("L3a requires L2 to be verified first")
        registry.assert_role(envelope.actor, VIRole.AGENT)

    elif et == VIEventType.L3B_CHECKOUT_CREATED.value:
        if state.mode != VIMode.AUTONOMOUS:
            raise ConflictError("L3b only allowed in autonomous mode")
        if state.credential_track_state not in (
            CredentialTrackState.L2_VERIFIED,
            CredentialTrackState.L3A_CREATED,
        ):
            raise ConflictError("L3b requires L2 to be verified first")
        registry.assert_role(envelope.actor, VIRole.AGENT)

    elif et == VIEventType.L3_CHAIN_VERIFIED.value:
        if state.l3a_payment is None or state.l3b_checkout is None:
            raise ConflictError("Chain verification requires both L3a and L3b")
        actor_role = registry.get_role(envelope.actor)
        if actor_role not in (VIRole.CREDENTIAL_PROVIDER, VIRole.PAYMENT_NETWORK):
            raise ConflictError(
                "Only credential_provider or payment_network can verify chain"
            )

    elif et == VIEventType.SETTLEMENT_VI_INITIATED.value:
        # In immediate mode, L2_VERIFIED is sufficient
        if state.mode == VIMode.IMMEDIATE:
            if state.credential_track_state != CredentialTrackState.L2_VERIFIED:
                raise ConflictError("Settlement requires L2 to be verified")
        else:
            if state.credential_track_state != CredentialTrackState.L3_CHAIN_VERIFIED:
                raise ConflictError("Settlement requires chain to be verified")
        registry.assert_role(envelope.actor, VIRole.PAYMENT_NETWORK)

    elif et == VIEventType.SETTLEMENT_VI_CONFIRMED.value:
        if state.credential_track_state != CredentialTrackState.SETTLEMENT_INITIATED:
            raise ConflictError("Confirmation requires settlement to be initiated")
        registry.assert_role(envelope.actor, VIRole.PAYMENT_NETWORK)

    else:
        raise BadRequestError(f"Unknown event type: {et}")


def _validate_base_transition(
    state: VIJobStateView, envelope: SignedActionEnvelope,
) -> None:
    """Bridge VI state to base ARS validation."""
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
