"""VDC (Verifiable Digital Credential) creation, signing, and verification."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from nacl.signing import SigningKey

from ars.crypto import canonicalize, sign_envelope, verify_envelope_signature

from .models import (
    CartLineItem,
    CartMandate,
    IntentMandate,
    PaymentMandate,
    VDCHeader,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _claims_dict(mandate) -> dict:
    """Extract the signable claims (everything except 'signature')."""
    d = mandate.model_dump()
    d.pop("signature", None)
    return d


def compute_mandate_hash(mandate) -> str:
    """SHA-256 hex digest of canonicalised mandate claims (excluding signature)."""
    claims = _claims_dict(mandate)
    return hashlib.sha256(canonicalize(claims)).hexdigest()


def _compute_cart_hash(line_items: list[dict]) -> str:
    """SHA-256 hex digest of canonicalised line items list."""
    return hashlib.sha256(canonicalize(line_items)).hexdigest()


def _sign_claims(signing_key: SigningKey, claims: dict) -> str:
    """Sign canonical claims with Ed25519. Returns hex signature."""
    return sign_envelope(signing_key, claims)


# ── VDC Creation ──────────────────────────────────────────────────────────────


def create_intent_mandate(
    signing_key: SigningKey,
    job_id: str,
    budget: int,
    allowed_merchants: list[str],
    description: str,
    currency: str = "USD",
    sku_patterns: list[str] | None = None,
    ttl_seconds: int = 3600,
    requires_principal: bool = False,
) -> IntentMandate:
    """Create and sign an IntentMandate VDC."""
    now = datetime.now(timezone.utc)
    exp = datetime(
        now.year,
        now.month,
        now.day,
        now.hour,
        now.minute,
        now.second,
        tzinfo=timezone.utc,
    )
    # Compute expiry by adding seconds
    from datetime import timedelta

    exp = now + timedelta(seconds=ttl_seconds)

    pubkey_hex = signing_key.verify_key.encode().hex()
    header = VDCHeader(
        iss=pubkey_hex,
        sub=job_id,
        iat=now.isoformat(),
        exp=exp.isoformat(),
        vdc_type="intent",
    )
    mandate = IntentMandate(
        header=header,
        budget=budget,
        currency=currency,
        allowed_merchants=allowed_merchants,
        sku_patterns=sku_patterns or [],
        description=description,
        requires_principal=requires_principal,
        signature="",  # placeholder, will be replaced
    )
    claims = _claims_dict(mandate)
    sig = _sign_claims(signing_key, claims)
    return mandate.model_copy(update={"signature": sig})


def create_cart_mandate(
    signing_key: SigningKey,
    job_id: str,
    line_items: list[CartLineItem],
    ttl_seconds: int = 900,
) -> CartMandate:
    """Create and sign a CartMandate VDC."""
    now = datetime.now(timezone.utc)
    from datetime import timedelta

    exp = now + timedelta(seconds=ttl_seconds)

    pubkey_hex = signing_key.verify_key.encode().hex()
    items_dicts = [item.model_dump() for item in line_items]
    cart_hash = _compute_cart_hash(items_dicts)
    total = sum(item.quantity * item.unit_price for item in line_items)

    header = VDCHeader(
        iss=pubkey_hex,
        sub=job_id,
        iat=now.isoformat(),
        exp=exp.isoformat(),
        vdc_type="cart",
    )
    mandate = CartMandate(
        header=header,
        cart_hash=cart_hash,
        line_items=line_items,
        total=total,
        merchant_id=pubkey_hex,
        signature="",
    )
    claims = _claims_dict(mandate)
    sig = _sign_claims(signing_key, claims)
    return mandate.model_copy(update={"signature": sig})


def create_payment_mandate(
    signing_key: SigningKey,
    job_id: str,
    cart_mandate: CartMandate,
    payment_token_hash: str,
    ttl_seconds: int = 900,
) -> PaymentMandate:
    """Create and sign a PaymentMandate VDC referencing a CartMandate."""
    now = datetime.now(timezone.utc)
    from datetime import timedelta

    exp = now + timedelta(seconds=ttl_seconds)

    pubkey_hex = signing_key.verify_key.encode().hex()
    cart_mandate_hash = compute_mandate_hash(cart_mandate)

    header = VDCHeader(
        iss=pubkey_hex,
        sub=job_id,
        iat=now.isoformat(),
        exp=exp.isoformat(),
        vdc_type="payment",
    )
    mandate = PaymentMandate(
        header=header,
        cart_mandate_hash=cart_mandate_hash,
        payment_token_hash=payment_token_hash,
        amount=cart_mandate.total,
        currency="USD",
        signature="",
    )
    claims = _claims_dict(mandate)
    sig = _sign_claims(signing_key, claims)
    return mandate.model_copy(update={"signature": sig})


# ── Verification ──────────────────────────────────────────────────────────────


def verify_mandate(mandate, expected_pubkey: str) -> bool:
    """Verify a mandate's Ed25519 signature against the expected public key."""
    claims = _claims_dict(mandate)
    return verify_envelope_signature(expected_pubkey, claims, mandate.signature)


def is_expired(mandate) -> bool:
    """Check if a mandate's TTL has passed."""
    exp_str = mandate.header.exp
    exp_dt = datetime.fromisoformat(exp_str)
    if exp_dt.tzinfo is None:
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > exp_dt
