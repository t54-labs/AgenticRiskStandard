from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .errors import BadRequestError, ConflictError, ForbiddenError
from .models import (
    AgreementDraft,
    EvalVerdict,
    Event,
    EventType,
    FeeTrackState,
    JobPhase,
    JobStateView,
    PrincipalTrackState,
    SettlementAction,
    SignedActionEnvelope,
)


# ── Internal accumulator ─────────────────────────────────────────────────────


@dataclass
class _Acc:
    job_id: str = ""
    agreement: Optional[AgreementDraft] = None
    agreement_hash: Optional[str] = None
    signatures: dict[str, bool] = field(default_factory=dict)
    fee_lock_ref: Optional[str] = None
    deliverable_ref: Optional[str] = None
    evaluation: Optional[dict] = None
    settlement_ref: Optional[str] = None
    settlement_action: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    event_count: int = 0
    principal_request: Optional[dict] = None
    uw_decision: Optional[dict] = None
    premium_ref: Optional[str] = None
    collateral_ref: Optional[str] = None
    collateral_required: Optional[int] = None
    premium_refused: bool = False
    collateral_refused: bool = False
    premium_amount: Optional[int] = None
    override: Optional[dict] = None
    transfer_ref: Optional[str] = None
    exec_evidence_ref: Optional[str] = None


def _agreement_bound(acc: _Acc) -> bool:
    """True when both requestor AND business agent have signed."""
    if acc.agreement is None:
        return False
    return acc.signatures.get(
        acc.agreement.requestor_pubkey, False
    ) and acc.signatures.get(acc.agreement.business_agent_pubkey, False)


def _derive_phase(acc: _Acc) -> JobPhase:
    if acc.settlement_ref is not None:
        return JobPhase.CLOSED
    if acc.evaluation is not None:
        return JobPhase.EVALUATION
    if _agreement_bound(acc):
        return JobPhase.TRANSACTION
    if acc.agreement is not None:
        return JobPhase.NEGOTIATION
    return JobPhase.REQUEST


def _derive_fee_track(acc: _Acc) -> Optional[FeeTrackState]:
    if not _agreement_bound(acc):
        return None
    if acc.settlement_ref:
        if acc.settlement_action == SettlementAction.RELEASE.value:
            return FeeTrackState.FEE_SETTLED_RELEASE
        return FeeTrackState.FEE_SETTLED_REFUND
    if acc.deliverable_ref:
        return FeeTrackState.FEE_DELIVERED
    if acc.fee_lock_ref:
        return FeeTrackState.FEE_ESCROW_LOCKED
    return FeeTrackState.FEE_AWAIT_LOCK


def _is_fund_moving(acc: _Acc) -> bool:
    return acc.agreement is not None and (
        acc.agreement.job_type == "fund-moving" or acc.agreement.principal is not None
    )


def _coverage_bound(acc: _Acc) -> bool:
    if acc.uw_decision is None:
        return False
    if not acc.uw_decision.get("approve"):
        return False
    prem = acc.uw_decision.get("premium", 0) or 0
    return prem == 0 or acc.premium_ref is not None


def _override_ack(acc: _Acc) -> bool:
    return bool(acc.override and acc.override.get("decision") == "proceed")


def _derive_principal_track(acc: _Acc) -> Optional[PrincipalTrackState]:
    if not _agreement_bound(acc) or not _is_fund_moving(acc):
        return None

    if acc.exec_evidence_ref is not None:
        return PrincipalTrackState.EXECUTION_EVIDENCE_SUBMITTED
    if acc.transfer_ref is not None:
        return PrincipalTrackState.EXECUTION_PENDING

    if acc.principal_request is None:
        return PrincipalTrackState.UW_AWAIT_REQUEST
    if acc.uw_decision is None:
        return PrincipalTrackState.UW_REVIEW

    if not acc.uw_decision.get("approve"):
        # rejected underwriting → override path
        if not _override_ack(acc):
            return PrincipalTrackState.OVERRIDE_PENDING
        return PrincipalTrackState.RELEASABLE

    # approved underwriting
    premium = acc.uw_decision.get("premium", 0) or 0
    if premium > 0 and acc.premium_ref is None:
        if acc.premium_refused:
            if not _override_ack(acc):
                return PrincipalTrackState.OVERRIDE_PENDING
            # override accepted, proceed past premium gate
        else:
            return PrincipalTrackState.PREMIUM_PENDING

    collateral_req = acc.uw_decision.get("collateral_required", 0) or 0
    if collateral_req > 0 and acc.collateral_ref is None:
        if acc.collateral_refused:
            if not _override_ack(acc):
                return PrincipalTrackState.OVERRIDE_PENDING
            # override accepted, proceed past collateral gate
        else:
            return PrincipalTrackState.COLLATERAL_REQUESTED

    # All conditions satisfied (happy path or override) → auto-release
    return PrincipalTrackState.RELEASABLE


# ── Public: derive state ─────────────────────────────────────────────────────


def derive_job_state(events: list[Event]) -> JobStateView:
    acc = _Acc()
    for ev in events:
        acc.event_count += 1
        acc.job_id = ev.job_id
        acc.updated_at = ev.timestamp

        if ev.event_type == EventType.JOB_CREATED:
            acc.agreement = AgreementDraft(**ev.payload["agreement"])
            acc.agreement_hash = ev.agreement_hash
            acc.created_at = ev.timestamp

        elif ev.event_type == EventType.PROPOSAL_SUBMITTED:
            acc.agreement = AgreementDraft(**ev.payload["agreement"])
            acc.agreement_hash = ev.agreement_hash
            acc.signatures.clear()

        elif ev.event_type == EventType.AGREEMENT_SIGNED:
            acc.signatures[ev.actor] = True

        elif ev.event_type == EventType.FEE_ESCROW_LOCKED:
            acc.fee_lock_ref = ev.payload.get("lock_ref")

        elif ev.event_type == EventType.DELIVERABLE_SUBMITTED:
            acc.deliverable_ref = ev.payload.get("deliverable_ref")

        elif ev.event_type == EventType.OUTCOME_EVALUATED:
            acc.evaluation = {
                "verdict": ev.payload["verdict"],
                "evidence_ref": ev.payload.get("evidence_ref"),
                "reason": ev.payload.get("reason"),
            }

        elif ev.event_type == EventType.FEE_SETTLED:
            acc.settlement_ref = ev.payload.get("settlement_ref")
            acc.settlement_action = ev.payload.get("action")

        elif ev.event_type == EventType.UW_REQUESTED:
            acc.principal_request = ev.payload

        elif ev.event_type == EventType.UW_DECIDED:
            acc.uw_decision = ev.payload
            acc.premium_amount = ev.payload.get("premium")
            acc.collateral_required = ev.payload.get("collateral_required")

        elif ev.event_type == EventType.PREMIUM_PAID:
            acc.premium_ref = ev.payload.get("premium_ref")

        elif ev.event_type == EventType.PREMIUM_REFUSED:
            acc.premium_refused = True

        elif ev.event_type == EventType.COLLATERAL_LOCKED:
            acc.collateral_ref = ev.payload.get("collateral_ref")

        elif ev.event_type == EventType.COLLATERAL_REFUSED:
            acc.collateral_refused = True

        elif ev.event_type == EventType.OVERRIDE_DECIDED:
            acc.override = ev.payload

        elif ev.event_type == EventType.PRINCIPAL_RELEASED:
            acc.transfer_ref = ev.payload.get("transfer_ref")

        elif ev.event_type == EventType.EXECUTION_EVIDENCE_SUBMITTED:
            acc.exec_evidence_ref = ev.payload.get("exec_evidence_ref")

    return JobStateView(
        job_id=acc.job_id,
        phase=_derive_phase(acc),
        fee_track_state=_derive_fee_track(acc),
        agreement=acc.agreement.model_dump() if acc.agreement else None,
        agreement_hash=acc.agreement_hash,
        signatures=acc.signatures,
        fee_lock_ref=acc.fee_lock_ref,
        deliverable_ref=acc.deliverable_ref,
        evaluation=acc.evaluation,
        settlement_ref=acc.settlement_ref,
        settlement_action=acc.settlement_action,
        created_at=acc.created_at,
        updated_at=acc.updated_at,
        event_count=acc.event_count,
        principal_track_state=_derive_principal_track(acc),
        uw_decision=acc.uw_decision,
        premium_ref=acc.premium_ref,
        collateral_ref=acc.collateral_ref,
        override=acc.override,
        transfer_ref=acc.transfer_ref,
        exec_evidence_ref=acc.exec_evidence_ref,
    )


# ── Public: validate transition ──────────────────────────────────────────────


def validate_transition(state: JobStateView, envelope: SignedActionEnvelope) -> None:
    """Raise an HTTP error if the transition is not allowed."""
    et = envelope.type
    agr = AgreementDraft(**state.agreement) if state.agreement else None

    # Every post-creation action must reference the correct agreement_hash
    if et != EventType.JOB_CREATED:
        if state.agreement_hash and envelope.agreement_hash != state.agreement_hash:
            raise BadRequestError("agreement_hash mismatch")

    if et == EventType.PROPOSAL_SUBMITTED:
        if state.phase not in (JobPhase.NEGOTIATION, JobPhase.REQUEST):
            raise ConflictError("Proposals only accepted during NEGOTIATION")
        if agr and envelope.actor not in (
            agr.requestor_pubkey,
            agr.business_agent_pubkey,
        ):
            raise ForbiddenError(
                "Only requestor or business agent can submit proposals"
            )

    elif et == EventType.AGREEMENT_SIGNED:
        if state.phase not in (JobPhase.NEGOTIATION,):
            raise ConflictError("Signatures only accepted during NEGOTIATION")
        if agr and envelope.actor not in (
            agr.requestor_pubkey,
            agr.business_agent_pubkey,
        ):
            raise ForbiddenError(
                "Only requestor or business agent can sign the agreement"
            )
        if envelope.actor in state.signatures:
            raise ConflictError("Actor already signed this agreement")

    elif et == EventType.FEE_ESCROW_LOCKED:
        if state.phase != JobPhase.TRANSACTION:
            raise ConflictError("Fee lock requires TRANSACTION phase (both signatures)")
        if state.fee_track_state != FeeTrackState.FEE_AWAIT_LOCK:
            raise ConflictError("Fee already locked")
        if agr and envelope.actor != agr.requestor_pubkey:
            raise ForbiddenError("Only requestor can lock fee escrow")

    elif et == EventType.DELIVERABLE_SUBMITTED:
        if state.fee_track_state != FeeTrackState.FEE_ESCROW_LOCKED:
            raise ConflictError("Deliverable requires fee to be locked first")
        if agr and envelope.actor != agr.business_agent_pubkey:
            raise ForbiddenError("Only business agent can submit deliverable")

    elif et == EventType.OUTCOME_EVALUATED:
        if state.fee_track_state != FeeTrackState.FEE_DELIVERED:
            raise ConflictError("Evaluation requires deliverable to be submitted first")
        if agr and envelope.actor != agr.evaluator_pubkey:
            raise ForbiddenError("Only evaluator can evaluate outcome")

    elif et == EventType.FEE_SETTLED:
        if state.evaluation is None:
            raise ConflictError("Settlement requires evaluation first")
        if state.settlement_ref is not None:
            raise ConflictError("Fee already settled")
        action = envelope.payload.get("action")
        verdict = state.evaluation.get("verdict")
        if (
            verdict == EvalVerdict.PASS.value
            and action != SettlementAction.RELEASE.value
        ):
            raise BadRequestError("Pass verdict requires 'release' action")
        if (
            verdict == EvalVerdict.FAIL.value
            and action != SettlementAction.REFUND.value
        ):
            raise BadRequestError("Fail verdict requires 'refund' action")

    # ── Principal / UW track transitions ─────────────────────────────────

    elif et == EventType.UW_REQUESTED:
        if state.phase != JobPhase.TRANSACTION:
            raise ConflictError("UW request requires TRANSACTION phase")
        if state.principal_track_state != PrincipalTrackState.UW_AWAIT_REQUEST:
            raise ConflictError("UW already requested or not a fund-moving job")
        if agr and envelope.actor != agr.business_agent_pubkey:
            raise ForbiddenError("Only business agent can request underwriting")

    elif et == EventType.UW_DECIDED:
        if state.principal_track_state != PrincipalTrackState.UW_REVIEW:
            raise ConflictError("UW decision requires UW_REVIEW state")
        if agr and envelope.actor != agr.underwriter_pubkey:
            raise ForbiddenError("Only underwriter can submit UW decision")

    elif et == EventType.PREMIUM_PAID:
        if state.principal_track_state != PrincipalTrackState.PREMIUM_PENDING:
            raise ConflictError("Premium payment requires PREMIUM_PENDING state")
        if agr and envelope.actor != agr.requestor_pubkey:
            raise ForbiddenError("Only requestor can pay premium")

    elif et == EventType.PREMIUM_REFUSED:
        if state.principal_track_state != PrincipalTrackState.PREMIUM_PENDING:
            raise ConflictError("Premium refusal requires PREMIUM_PENDING state")
        if agr and envelope.actor != agr.requestor_pubkey:
            raise ForbiddenError("Only requestor can refuse premium")

    elif et == EventType.COLLATERAL_LOCKED:
        if state.principal_track_state != PrincipalTrackState.COLLATERAL_REQUESTED:
            raise ConflictError("Collateral lock requires COLLATERAL_REQUESTED state")
        if agr and envelope.actor != agr.business_agent_pubkey:
            raise ForbiddenError("Only business agent can lock collateral")

    elif et == EventType.COLLATERAL_REFUSED:
        if state.principal_track_state != PrincipalTrackState.COLLATERAL_REQUESTED:
            raise ConflictError(
                "Collateral refusal requires COLLATERAL_REQUESTED state"
            )
        if agr and envelope.actor != agr.business_agent_pubkey:
            raise ForbiddenError("Only business agent can refuse collateral")

    elif et == EventType.OVERRIDE_DECIDED:
        if state.principal_track_state != PrincipalTrackState.OVERRIDE_PENDING:
            raise ConflictError("Override requires OVERRIDE_PENDING state")
        if agr and envelope.actor != agr.requestor_pubkey:
            raise ForbiddenError("Only requestor can submit override decision")

    elif et == EventType.PRINCIPAL_RELEASED:
        if state.principal_track_state != PrincipalTrackState.RELEASABLE:
            raise ConflictError("Principal release requires RELEASABLE state")
        if agr and envelope.actor != agr.settlement_layer_pubkey:
            raise ForbiddenError("Only settlement layer can release principal")

    elif et == EventType.EXECUTION_EVIDENCE_SUBMITTED:
        if state.principal_track_state != PrincipalTrackState.EXECUTION_PENDING:
            raise ConflictError("Execution evidence requires EXECUTION_PENDING state")
        if agr and envelope.actor != agr.business_agent_pubkey:
            raise ForbiddenError("Only business agent can submit execution evidence")
