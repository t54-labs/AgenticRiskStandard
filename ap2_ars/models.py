"""AP2-ARS data models: VDC mandates, extended agreement, AP2 envelopes/events."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel

from ars.models import (
    FeeTerms,
    FeeTrackState,
    JobPhase,
    PrincipalTerms,
    PrincipalTrackState,
)


# ── AP2 Enums ────────────────────────────────────────────────────────────────


class Modality(str, Enum):
    HUMAN_PRESENT = "human-present"
    HUMAN_NOT_PRESENT = "human-not-present"


class MandateTrackState(str, Enum):
    MANDATE_NONE = "MANDATE_NONE"
    INTENT_CREATED = "INTENT_CREATED"
    CART_PROPOSED = "CART_PROPOSED"
    CART_SIGNED = "CART_SIGNED"
    CART_APPROVED = "CART_APPROVED"
    PAYMENT_CREATED = "PAYMENT_CREATED"
    PAYMENT_SIGNED = "PAYMENT_SIGNED"
    SETTLEMENT_INITIATED = "SETTLEMENT_INITIATED"
    SETTLEMENT_CONFIRMED = "SETTLEMENT_CONFIRMED"


class AP2EventType(str, Enum):
    # Base ARS event types (re-exported)
    JOB_CREATED = "JOB_CREATED"
    PROPOSAL_SUBMITTED = "PROPOSAL_SUBMITTED"
    AGREEMENT_SIGNED = "AGREEMENT_SIGNED"
    FEE_ESCROW_LOCKED = "FEE_ESCROW_LOCKED"
    DELIVERABLE_SUBMITTED = "DELIVERABLE_SUBMITTED"
    OUTCOME_EVALUATED = "OUTCOME_EVALUATED"
    FEE_SETTLED = "FEE_SETTLED"
    UW_REQUESTED = "UW_REQUESTED"
    UW_DECIDED = "UW_DECIDED"
    PREMIUM_PAID = "PREMIUM_PAID"
    COLLATERAL_LOCKED = "COLLATERAL_LOCKED"
    COLLATERAL_REFUSED = "COLLATERAL_REFUSED"
    OVERRIDE_DECIDED = "OVERRIDE_DECIDED"
    RELEASE_APPROVED = "RELEASE_APPROVED"
    PRINCIPAL_RELEASED = "PRINCIPAL_RELEASED"
    EXECUTION_EVIDENCE_SUBMITTED = "EXECUTION_EVIDENCE_SUBMITTED"
    # AP2-specific mandate events
    INTENT_MANDATE_CREATED = "INTENT_MANDATE_CREATED"
    CART_MANDATE_PROPOSED = "CART_MANDATE_PROPOSED"
    CART_MANDATE_SIGNED = "CART_MANDATE_SIGNED"
    CART_APPROVED_BY_USER = "CART_APPROVED_BY_USER"
    PAYMENT_MANDATE_CREATED = "PAYMENT_MANDATE_CREATED"
    PAYMENT_MANDATE_SIGNED = "PAYMENT_MANDATE_SIGNED"
    SETTLEMENT_402_INITIATED = "SETTLEMENT_402_INITIATED"
    SETTLEMENT_402_CONFIRMED = "SETTLEMENT_402_CONFIRMED"


# Set of base ARS event type values (for filtering)
_BASE_EVENT_TYPES = {
    "JOB_CREATED",
    "PROPOSAL_SUBMITTED",
    "AGREEMENT_SIGNED",
    "FEE_ESCROW_LOCKED",
    "DELIVERABLE_SUBMITTED",
    "OUTCOME_EVALUATED",
    "FEE_SETTLED",
    "UW_REQUESTED",
    "UW_DECIDED",
    "PREMIUM_PAID",
    "COLLATERAL_LOCKED",
    "COLLATERAL_REFUSED",
    "OVERRIDE_DECIDED",
    "RELEASE_APPROVED",
    "PRINCIPAL_RELEASED",
    "EXECUTION_EVIDENCE_SUBMITTED",
}


def is_base_event_type(event_type: str) -> bool:
    return event_type in _BASE_EVENT_TYPES


# ── VDC (Verifiable Digital Credential) Models ───────────────────────────────


class VDCHeader(BaseModel):
    iss: str  # signer pubkey hex
    sub: str  # job_id
    iat: str  # ISO 8601 UTC
    exp: str  # ISO 8601 UTC
    vdc_type: str  # "intent" | "cart" | "payment"


class IntentMandate(BaseModel):
    header: VDCHeader
    budget: int  # max spend in smallest currency unit
    currency: str = "USD"
    allowed_merchants: list[str]  # merchant pubkey hex whitelist
    sku_patterns: list[str] = []  # glob patterns for allowed SKUs
    description: str  # natural language intent
    signature: str  # Ed25519 over canonical claims


class CartLineItem(BaseModel):
    sku: str
    description: str
    quantity: int
    unit_price: int  # smallest currency unit


class CartMandate(BaseModel):
    header: VDCHeader
    cart_hash: str  # SHA-256 of canonical line_items
    line_items: list[CartLineItem]
    total: int
    merchant_id: str  # merchant pubkey hex
    signature: str


class PaymentMandate(BaseModel):
    header: VDCHeader
    cart_mandate_hash: str  # SHA-256 of CartMandate
    payment_token_hash: str  # hash of payment method (agent never sees plaintext)
    amount: int
    currency: str = "USD"
    signature: str


# ── AP2 Agreement ─────────────────────────────────────────────────────────────


class AP2AgreementDraft(BaseModel):
    version: str = "ap2_ars/0.1"
    job_type: str
    description: str
    modality: Modality
    # 6 mandatory actors
    user_pubkey: str
    shopping_agent_pubkey: str
    evaluator_pubkey: str
    credentials_provider_pubkey: str
    merchant_pubkey: str
    payment_processor_pubkey: str
    # Optional (fund-moving)
    underwriter_pubkey: Optional[str] = None
    human_authority_pubkey: Optional[str] = None
    # Terms
    fee: FeeTerms
    principal: Optional[PrincipalTerms] = None
    deliverable_spec: Optional[str] = None


# ── AP2 Signed Envelope (string-typed) ────────────────────────────────────────


class AP2SignedActionEnvelope(BaseModel):
    """Universal POST input for AP2. Uses string type to accept all event types."""

    type: str
    job_id: str
    agreement_hash: str
    payload: dict
    actor: str  # hex-encoded Ed25519 public key
    signature: str  # hex-encoded Ed25519 signature
    timestamp: str  # ISO 8601 UTC


class AP2CreateJobRequest(BaseModel):
    """POST /jobs input for AP2. No job_id or agreement_hash."""

    type: str = "JOB_CREATED"
    payload: dict  # {"agreement": {...}}
    actor: str
    signature: str
    timestamp: str


# ── AP2 Stored Event ──────────────────────────────────────────────────────────


class AP2Event(BaseModel):
    event_id: int
    job_id: str
    event_type: str  # string, not enum
    agreement_hash: str
    payload: dict
    actor: str
    signature: str
    timestamp: str
    server_received_at: str


# ── AP2 Job State View ───────────────────────────────────────────────────────


class AP2JobStateView(BaseModel):
    # Base ARS fields
    job_id: str
    phase: JobPhase
    fee_track_state: Optional[FeeTrackState] = None
    agreement: Optional[AP2AgreementDraft] = None
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
    # AP2-specific fields
    modality: Optional[Modality] = None
    mandate_track_state: Optional[MandateTrackState] = None
    intent_mandate: Optional[dict] = None
    cart_mandate: Optional[dict] = None
    payment_mandate: Optional[dict] = None
    x402_ref: Optional[str] = None
    x402_settlement_ref: Optional[str] = None
    constraint_violations: list[str] = []
