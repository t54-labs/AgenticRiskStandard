"""AP2-ARS data models: VDC mandates, extended agreement, AP2-specific enums."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel

from abstract_ars.models import EventType, FeeTerms, JobStateView, PrincipalTerms


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


# AP2-specific mandate events (the 8 additions beyond base ARS)
_AP2_EXTRA_EVENTS = {
    "INTENT_MANDATE_CREATED": "INTENT_MANDATE_CREATED",
    "CART_MANDATE_PROPOSED": "CART_MANDATE_PROPOSED",
    "CART_MANDATE_SIGNED": "CART_MANDATE_SIGNED",
    "CART_APPROVED_BY_USER": "CART_APPROVED_BY_USER",
    "PAYMENT_MANDATE_CREATED": "PAYMENT_MANDATE_CREATED",
    "PAYMENT_MANDATE_SIGNED": "PAYMENT_MANDATE_SIGNED",
}

# Build AP2EventType dynamically: all base EventType members + AP2-specific ones
AP2EventType = Enum(
    "AP2EventType", {m.name: m.value for m in EventType} | _AP2_EXTRA_EVENTS, type=str,
)

# Derive base event types from EventType automatically
_BASE_EVENT_TYPES: frozenset[str] = frozenset(m.value for m in EventType)


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
    requires_principal: bool = False  # whether UW/principal track is needed
    max_premium: Optional[int] = None  # auto-pay premium if ≤ this amount (HNP mode)
    allow_uw_override: bool = False  # auto-override UW rejection/refusal (HNP mode)
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


# ── AP2 Agreement (different domain model, NOT a subclass of AgreementDraft) ─


class AP2AgreementDraft(BaseModel):
    version: str = "ap2_ars/0.1"
    job_type: str
    description: str
    modality: Modality
    # Actors
    user_pubkey: str
    shopping_agent_pubkey: Optional[
        str
    ] = None  # optional; when provided, firewall enforced
    evaluator_pubkey: str
    credentials_provider_pubkey: str
    merchant_pubkey: str
    payment_processor_pubkey: str
    # Optional (fund-moving)
    underwriter_pubkey: Optional[str] = None
    # Terms
    fee: FeeTerms
    principal: Optional[PrincipalTerms] = None
    deliverable_spec: Optional[str] = None


# ── AP2 Job State View (inherits from base, adds mandate fields) ─────────────


class AP2JobStateView(JobStateView):
    """Extends base JobStateView with AP2 mandate track fields."""

    agreement: Optional[AP2AgreementDraft] = None  # type: ignore[assignment]
    modality: Optional[Modality] = None
    mandate_track_state: Optional[MandateTrackState] = None
    intent_mandate: Optional[dict] = None
    cart_mandate: Optional[dict] = None
    payment_mandate: Optional[dict] = None
    constraint_violations: list[str] = []
