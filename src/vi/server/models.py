"""VI-ARS data models: SD-JWT credential track, extended agreement, VI-specific enums."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel

from abstract_ars.models import EventType, FeeTerms, JobStateView, PrincipalTerms


# ── VI Enums ─────────────────────────────────────────────────────────────────


class VIMode(str, Enum):
    IMMEDIATE = "immediate"  # user confirms exact purchase (2-layer, no L3)
    AUTONOMOUS = "autonomous"  # agent decides within constraints (3-layer)


class CredentialTrackState(str, Enum):
    CREDENTIAL_NONE = "CREDENTIAL_NONE"
    L1_ISSUED = "L1_ISSUED"
    L2_CREATED = "L2_CREATED"
    L2_VERIFIED = "L2_VERIFIED"
    L3A_CREATED = "L3A_CREATED"  # autonomous only
    L3B_CREATED = "L3B_CREATED"  # autonomous only
    L3_CHAIN_VERIFIED = "L3_CHAIN_VERIFIED"  # autonomous only
    SETTLEMENT_INITIATED = "SETTLEMENT_INITIATED"
    SETTLEMENT_CONFIRMED = "SETTLEMENT_CONFIRMED"


# VI-specific credential events (additions beyond base ARS)
_VI_EXTRA_EVENTS = {
    "L1_CREDENTIAL_ISSUED": "L1_CREDENTIAL_ISSUED",
    "L2_MANDATE_CREATED": "L2_MANDATE_CREATED",
    "L2_MANDATE_VERIFIED": "L2_MANDATE_VERIFIED",
    "L3A_PAYMENT_CREATED": "L3A_PAYMENT_CREATED",
    "L3B_CHECKOUT_CREATED": "L3B_CHECKOUT_CREATED",
    "L3_CHAIN_VERIFIED": "L3_CHAIN_VERIFIED",
    "SETTLEMENT_VI_INITIATED": "SETTLEMENT_VI_INITIATED",
    "SETTLEMENT_VI_CONFIRMED": "SETTLEMENT_VI_CONFIRMED",
}

# Build VIEventType dynamically: all base EventType members + VI-specific ones
VIEventType = Enum(
    "VIEventType", {m.name: m.value for m in EventType} | _VI_EXTRA_EVENTS, type=str,
)

# Derive base event types from EventType automatically
_BASE_EVENT_TYPES: frozenset[str] = frozenset(m.value for m in EventType)


def is_base_event_type(event_type: str) -> bool:
    return event_type in _BASE_EVENT_TYPES


# ── VI Agreement (different domain model, NOT a subclass of AgreementDraft) ──


class VIAgreementDraft(BaseModel):
    version: str = "vi_ars/0.1"
    job_type: str
    description: str
    mode: VIMode
    # Ed25519 keys for ARS event signing (base layer)
    user_pubkey: str
    agent_pubkey: Optional[str] = None  # optional; firewall enforced when provided
    evaluator_pubkey: str
    credential_provider_pubkey: str
    merchant_pubkey: str
    payment_network_pubkey: str
    # ES256 JWKs for VI credential chain (stored as dicts)
    user_jwk: dict
    agent_jwk: Optional[dict] = None  # autonomous only
    credential_provider_jwk: dict  # L1 issuer
    merchant_jwk: dict
    payment_network_jwk: dict
    # Optional (fund-moving)
    underwriter_pubkey: Optional[str] = None
    # Intent fields (auto-action gates, same pattern as AP2 IntentMandate)
    requires_principal: bool = False
    max_premium: Optional[int] = None
    allow_uw_override: bool = False
    # Terms
    fee: FeeTerms
    principal: Optional[PrincipalTerms] = None
    deliverable_spec: Optional[str] = None


# ── VI Job State View (inherits from base, adds credential fields) ───────────


class VIJobStateView(JobStateView):
    """Extends base JobStateView with VI credential track fields."""

    agreement: Optional[VIAgreementDraft] = None  # type: ignore[assignment]
    mode: Optional[VIMode] = None
    credential_track_state: Optional[CredentialTrackState] = None
    l1_credential: Optional[str] = None  # serialized SD-JWT
    l2_mandate: Optional[dict] = None  # event payload
    l3a_payment: Optional[dict] = None  # event payload
    l3b_checkout: Optional[dict] = None  # event payload
    l3_chain_verified: bool = False
    constraint_violations: list[str] = []
