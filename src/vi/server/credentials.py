"""VI credential chain: L1/L2/L3 creation, signing, and verification.

Analogous to ap2/server/vdc.py but using ES256/SD-JWT instead of Ed25519/JSON.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
)

from .crypto import (
    compute_sd_hash,
    create_sd_jwt,
    decode_sd_jwt,
    public_key_to_jwk,
    verify_sd_jwt_signature,
)


# ── L1: Issuer Credential ───────────────────────────────────────────────────


def create_l1_credential(
    issuer_private_key: EllipticCurvePrivateKey,
    user_public_jwk: dict,
    pan_last_four: str = "0000",
    scheme: str = "visa",
    email: Optional[str] = None,
    ttl_days: int = 365,
) -> str:
    """Create and sign an L1 Issuer Credential (SD-JWT).

    The L1 asserts user identity and binds the user's public key via cnf.
    """
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=ttl_days)

    payload = {
        "vct": "VerifiedIdentity",
        "iss": "credential-provider",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "cnf": {"jwk": user_public_jwk},
        "pan_last_four": pan_last_four,
        "scheme": scheme,
    }
    if email:
        payload["email"] = email

    # Disclosures for selective revelation
    disclosures = [
        ["salt_pan", "pan_last_four", pan_last_four],
        ["salt_scheme", "scheme", scheme],
    ]
    if email:
        disclosures.append(["salt_email", "email", email])

    return create_sd_jwt(issuer_private_key, payload, disclosures)


# ── L2: User Mandate ────────────────────────────────────────────────────────


def create_l2_immediate(
    user_private_key: EllipticCurvePrivateKey,
    l1_serialized: str,
    checkout_jwt: str,
    amount: int,
    currency: str = "USD",
    payee: str = "",
    ttl_minutes: int = 15,
) -> str:
    """Create L2 Immediate Mode mandate (user confirms exact purchase).

    Binds to L1 via sd_hash. Contains final checkout and payment values.
    """
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=ttl_minutes)

    payload = {
        "vct": "UserMandate",
        "mode": "immediate",
        "iss": "user",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "sd_hash": compute_sd_hash(l1_serialized),
        "checkout_mandate": {"checkout_jwt": checkout_jwt,},
        "payment_mandate": {"amount": amount, "currency": currency, "payee": payee,},
    }

    return create_sd_jwt(user_private_key, payload)


def create_l2_autonomous(
    user_private_key: EllipticCurvePrivateKey,
    l1_serialized: str,
    agent_public_jwk: dict,
    constraints: dict,
    ttl_days: int = 30,
    prompt_summary: Optional[str] = None,
) -> str:
    """Create L2 Autonomous Mode mandate (agent decides within constraints).

    Binds to L1 via sd_hash. Contains constraints and delegates to agent via cnf.

    Args:
        constraints: dict with keys like 'payment_amount', 'allowed_merchants',
                     'allowed_payees', 'line_items', 'payment_budget'.
    """
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=ttl_days)

    payload = {
        "vct": "UserMandate",
        "mode": "autonomous",
        "iss": "user",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "sd_hash": compute_sd_hash(l1_serialized),
        "cnf": {"jwk": agent_public_jwk},
        "constraints": constraints,
    }
    if prompt_summary:
        payload["prompt_summary"] = prompt_summary

    # Disclosures for selective presentation:
    # Checkout constraints go to merchant; payment constraints go to network.
    disclosures = []
    if "allowed_merchants" in constraints:
        disclosures.append(
            ["salt_merchants", "allowed_merchants", constraints["allowed_merchants"]]
        )
    if "payment_amount" in constraints:
        disclosures.append(
            ["salt_payment", "payment_amount", constraints["payment_amount"]]
        )
    if "allowed_payees" in constraints:
        disclosures.append(
            ["salt_payees", "allowed_payees", constraints["allowed_payees"]]
        )

    return create_sd_jwt(user_private_key, payload, disclosures)


# ── L3a: Agent Payment Fulfillment ──────────────────────────────────────────


def create_l3a_payment(
    agent_private_key: EllipticCurvePrivateKey,
    l2_serialized: str,
    transaction_id: str,
    payee: str,
    amount: int,
    currency: str = "USD",
) -> str:
    """Create L3a Payment Fulfillment credential (autonomous only).

    Agent signs final payment values. Binds to L2 via sd_hash.
    """
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=5)  # 5-minute max validity per VI spec

    payload = {
        "vct": "AgentPaymentFulfillment",
        "iss": "agent",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "sd_hash": compute_sd_hash(l2_serialized),
        "transaction_id": transaction_id,
        "payee": payee,
        "amount": amount,
        "currency": currency,
    }

    return create_sd_jwt(agent_private_key, payload)


# ── L3b: Agent Checkout Fulfillment ─────────────────────────────────────────


def create_l3b_checkout(
    agent_private_key: EllipticCurvePrivateKey,
    l2_serialized: str,
    checkout_jwt: str,
    merchant_id: str = "",
    line_items: list[dict] | None = None,
) -> str:
    """Create L3b Checkout Fulfillment credential (autonomous only).

    Agent signs final checkout values. Binds to L2 via sd_hash.
    """
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=5)

    payload = {
        "vct": "AgentCheckoutFulfillment",
        "iss": "agent",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "sd_hash": compute_sd_hash(l2_serialized),
        "checkout_jwt": checkout_jwt,
        "merchant_id": merchant_id,
    }
    if line_items:
        payload["line_items"] = line_items

    return create_sd_jwt(agent_private_key, payload)


# ── Chain Verification ──────────────────────────────────────────────────────


def verify_l1(l1_serialized: str, issuer_public_key: EllipticCurvePublicKey) -> bool:
    """Verify L1 issuer signature."""
    return verify_sd_jwt_signature(l1_serialized, issuer_public_key)


def verify_l2_binding(l2_serialized: str, l1_serialized: str) -> bool:
    """Verify L2 binds to L1 via sd_hash."""
    decoded = decode_sd_jwt(l2_serialized)
    expected_hash = compute_sd_hash(l1_serialized)
    return decoded["payload"].get("sd_hash") == expected_hash


def verify_l3_binding(l3_serialized: str, l2_serialized: str) -> bool:
    """Verify L3 (a or b) binds to L2 via sd_hash."""
    decoded = decode_sd_jwt(l3_serialized)
    expected_hash = compute_sd_hash(l2_serialized)
    return decoded["payload"].get("sd_hash") == expected_hash


def verify_chain(
    l1_serialized: str,
    l2_serialized: str,
    issuer_public_key: EllipticCurvePublicKey,
    l3a_serialized: Optional[str] = None,
    l3b_serialized: Optional[str] = None,
) -> dict:
    """Verify the full credential chain (L1 → L2, optionally → L3a/L3b).

    Returns {"verified": bool, "errors": list[str]}.
    """
    errors: list[str] = []

    # 1. Verify L1 signature
    if not verify_l1(l1_serialized, issuer_public_key):
        errors.append("L1 signature verification failed")

    # 2. Verify L2 binds to L1
    if not verify_l2_binding(l2_serialized, l1_serialized):
        errors.append("L2 sd_hash does not match L1")

    # 3. Check L2 expiry
    l2_decoded = decode_sd_jwt(l2_serialized)
    l2_exp = l2_decoded["payload"].get("exp")
    if l2_exp and datetime.now(timezone.utc).timestamp() > l2_exp:
        errors.append("L2 mandate has expired")

    # 4. Verify L3a binding (if provided)
    if l3a_serialized:
        if not verify_l3_binding(l3a_serialized, l2_serialized):
            errors.append("L3a sd_hash does not match L2")
        l3a_decoded = decode_sd_jwt(l3a_serialized)
        l3a_exp = l3a_decoded["payload"].get("exp")
        if l3a_exp and datetime.now(timezone.utc).timestamp() > l3a_exp:
            errors.append("L3a credential has expired")

    # 5. Verify L3b binding (if provided)
    if l3b_serialized:
        if not verify_l3_binding(l3b_serialized, l2_serialized):
            errors.append("L3b sd_hash does not match L2")
        l3b_decoded = decode_sd_jwt(l3b_serialized)
        l3b_exp = l3b_decoded["payload"].get("exp")
        if l3b_exp and datetime.now(timezone.utc).timestamp() > l3b_exp:
            errors.append("L3b credential has expired")

    # 6. Cross-reference L3a and L3b (if both provided)
    if l3a_serialized and l3b_serialized:
        l3a_decoded = decode_sd_jwt(l3a_serialized)
        l3b_decoded = decode_sd_jwt(l3b_serialized)
        # Both must reference the same L2
        if l3a_decoded["payload"].get("sd_hash") != l3b_decoded["payload"].get(
            "sd_hash"
        ):
            errors.append("L3a and L3b reference different L2 mandates")

    return {"verified": len(errors) == 0, "errors": errors}
