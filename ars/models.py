from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ── Enums ────────────────────────────────────────────────────────────────────


class JobPhase(str, Enum):
    REQUEST = "REQUEST"
    NEGOTIATION = "NEGOTIATION"
    TRANSACTION = "TRANSACTION"
    EVALUATION = "EVALUATION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FeeTrackState(str, Enum):
    FEE_AWAIT_LOCK = "FEE_AWAIT_LOCK"
    FEE_ESCROW_LOCKED = "FEE_ESCROW_LOCKED"
    FEE_DELIVERED = "FEE_DELIVERED"
    FEE_SETTLED_RELEASE = "FEE_SETTLED_RELEASE"
    FEE_SETTLED_REFUND = "FEE_SETTLED_REFUND"


class EventType(str, Enum):
    # Fee track
    JOB_CREATED = "JOB_CREATED"
    PROPOSAL_SUBMITTED = "PROPOSAL_SUBMITTED"
    AGREEMENT_SIGNED = "AGREEMENT_SIGNED"
    FEE_ESCROW_LOCKED = "FEE_ESCROW_LOCKED"
    DELIVERABLE_SUBMITTED = "DELIVERABLE_SUBMITTED"
    OUTCOME_EVALUATED = "OUTCOME_EVALUATED"
    FEE_SETTLED = "FEE_SETTLED"
    # Principal / UW track
    UW_REQUESTED = "UW_REQUESTED"
    UW_DECIDED = "UW_DECIDED"
    PREMIUM_PAID = "PREMIUM_PAID"
    COLLATERAL_LOCKED = "COLLATERAL_LOCKED"
    COLLATERAL_REFUSED = "COLLATERAL_REFUSED"
    OVERRIDE_DECIDED = "OVERRIDE_DECIDED"
    RELEASE_APPROVED = "RELEASE_APPROVED"
    PRINCIPAL_RELEASED = "PRINCIPAL_RELEASED"
    EXECUTION_EVIDENCE_SUBMITTED = "EXECUTION_EVIDENCE_SUBMITTED"


class EvalVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class SettlementAction(str, Enum):
    RELEASE = "release"
    REFUND = "refund"


class PrincipalTrackState(str, Enum):
    UW_AWAIT_REQUEST = "UW_AWAIT_REQUEST"
    UW_REVIEW = "UW_REVIEW"
    PREMIUM_PENDING = "PREMIUM_PENDING"
    COLLATERAL_REQUESTED = "COLLATERAL_REQUESTED"
    OVERRIDE_PENDING = "OVERRIDE_PENDING"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    RELEASABLE = "RELEASABLE"
    EXECUTION_PENDING = "EXECUTION_PENDING"
    EXECUTION_EVIDENCE_SUBMITTED = "EXECUTION_EVIDENCE_SUBMITTED"


# ── Agreement ────────────────────────────────────────────────────────────────


class FeeTerms(BaseModel):
    amount: int  # smallest currency unit (e.g. cents)
    currency: str = "USD"


class PrincipalTerms(BaseModel):
    amount: int  # smallest unit
    currency: str = "USD"
    destination: Optional[str] = None


class AgreementDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str = "ars/0.1"
    job_type: str
    description: str
    requestor_pubkey: str
    business_agent_pubkey: str
    evaluator_pubkey: str
    fee: FeeTerms
    deliverable_spec: Optional[str] = None
    underwriter_pubkey: Optional[str] = None
    settlement_layer_pubkey: Optional[str] = None
    principal: Optional[PrincipalTerms] = None


# ── Signed envelope (universal POST input) ───────────────────────────────────


class SignedActionEnvelope(BaseModel):
    type: str
    job_id: str
    agreement_hash: str
    payload: dict
    actor: str  # hex-encoded Ed25519 public key
    signature: str  # hex-encoded Ed25519 signature
    timestamp: str  # ISO 8601 UTC


class CreateJobRequest(BaseModel):
    """POST /jobs input.  No job_id or agreement_hash — both server-computed."""

    type: str = "JOB_CREATED"
    payload: dict  # {"agreement": {...}}
    actor: str  # requestor pubkey hex
    signature: str  # signs {type, payload, actor, timestamp}
    timestamp: str  # ISO 8601 UTC


# ── Stored event ─────────────────────────────────────────────────────────────


class Event(BaseModel):
    event_id: int
    job_id: str
    event_type: str
    agreement_hash: str
    payload: dict
    actor: str
    signature: str
    timestamp: str
    server_received_at: str


# ── Job state view (GET response) ────────────────────────────────────────────


class JobStateView(BaseModel):
    job_id: str
    phase: JobPhase
    fee_track_state: Optional[FeeTrackState] = None
    agreement: Optional[dict] = None
    agreement_hash: Optional[str] = None
    signatures: dict[str, bool] = {}
    fee_lock_ref: Optional[str] = None
    deliverable_ref: Optional[str] = None
    evaluation: Optional[dict] = None
    settlement_ref: Optional[str] = None
    settlement_action: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    event_count: int = 0
    principal_track_state: Optional[PrincipalTrackState] = None
    uw_decision: Optional[dict] = None
    premium_ref: Optional[str] = None
    collateral_ref: Optional[str] = None
    override: Optional[dict] = None
    release_approvals: dict[str, bool] = {}
    transfer_ref: Optional[str] = None
    exec_evidence_ref: Optional[str] = None
