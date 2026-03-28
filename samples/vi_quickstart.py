#!/usr/bin/env python3
"""VI-ARS Quickstart: autonomous agent-mediated currency exchange with principal track.

Demonstrates the full VI-ARS flow in a single script using an in-process test server.
No external infrastructure needed — everything runs in-memory.

Scenario: User delegates a $100 USD → CAD currency exchange to an agent.
The agent operates within constraints (max amount, allowed merchants).
An underwriter assesses risk, requires premium ($200) and collateral ($5000).
The agent auto-pays the premium (within max_premium). Merchant locks collateral.
After delivery and evaluation, fee is released and collateral returned.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from ars_client._transport import Transport
from vi.client.user import VIUserClient
from vi.client.agent import VIAgentClient
from vi.client.merchant import VIMerchantClient
from vi.client.credential_provider import VICredentialProviderClient
from vi.client.payment_network import VIPaymentNetworkClient
from ars_client.evaluator import EvaluatorClient
from ars_client.underwriter import UnderwriterClient
from vi.server.server import create_app
from vi.server.crypto import generate_es256_keypair, public_key_to_jwk


# ── Helper: inject TestClient as transport ──────────────────────────────────


def make_client(cls, test_client, es256_key=None):
    sk = SigningKey.generate()
    client = cls.__new__(cls)
    client._sk = sk
    t = Transport.__new__(Transport)
    t._client = test_client
    client._transport = t
    if es256_key is not None and hasattr(cls, "_es256_key"):
        # VIDualKeyClient subclasses need ES256 key
        client._es256_key = es256_key
    return client


# ── Setup ────────────────────────────────────────────────────────────────────

app = create_app(db_path=":memory:")
tc = TestClient(app)
tc.__enter__()

# Create actors
user = make_client(VIUserClient, tc)
agent_es256_key, agent_es256_jwk = generate_es256_keypair()
agent = make_client(VIAgentClient, tc, es256_key=agent_es256_key)
merchant = make_client(VIMerchantClient, tc)
cred_es256_key, cred_es256_jwk = generate_es256_keypair()
cred_provider = make_client(VICredentialProviderClient, tc, es256_key=cred_es256_key)
net_es256_key, net_es256_jwk = generate_es256_keypair()
payment_network = make_client(VIPaymentNetworkClient, tc, es256_key=net_es256_key)
evaluator = make_client(EvaluatorClient, tc)
underwriter = make_client(UnderwriterClient, tc)

# ES256 JWKs for actors that need them
_, user_es256_jwk = generate_es256_keypair()
_, merchant_es256_jwk = generate_es256_keypair()

print("=" * 60)
print("VI-ARS Quickstart: Autonomous Currency Exchange")
print("=" * 60)

# ── Phase 1: Job Setup ──────────────────────────────────────────────────────

print("\n── Phase 1: Job Setup ──")

agreement = {
    "version": "vi_ars/0.1",
    "job_type": "fund-moving",
    "description": "USD to CAD exchange via agent",
    "mode": "autonomous",
    "user_pubkey": user.pubkey,
    "agent_pubkey": agent.pubkey,
    "evaluator_pubkey": evaluator.pubkey,
    "credential_provider_pubkey": cred_provider.pubkey,
    "merchant_pubkey": merchant.pubkey,
    "payment_network_pubkey": payment_network.pubkey,
    "underwriter_pubkey": underwriter.pubkey,
    "user_jwk": user_es256_jwk,
    "agent_jwk": agent_es256_jwk,
    "credential_provider_jwk": cred_es256_jwk,
    "merchant_jwk": merchant_es256_jwk,
    "payment_network_jwk": net_es256_jwk,
    "requires_principal": True,
    "max_premium": 500,
    "allow_uw_override": True,
    "fee": {"amount": 1000, "currency": "USD"},
    "principal": {"amount": 10000, "currency": "USD", "destination": "cad-account"},
}

resp = user.create_job(agreement)
job_id = resp.job_id
agr_hash = resp.agreement_hash
print(f"  Job created: {job_id}")
print(f"  Agreement hash: {agr_hash}")
print(f"  Mode: autonomous | Phase: {resp.phase}")

# Both sign
user.sign_agreement(job_id, agr_hash)
resp = merchant.sign_agreement(job_id, agr_hash)
print(f"  Both signed -> Phase: {resp.phase}")

# ── Phase 2: Credential Authorization ────────────────────────────────────────

print("\n── Phase 2: Credential Authorization (L1 → L2 → L3a + L3b) ──")

# L1: Credential provider issues identity
resp = cred_provider.issue_l1(job_id, agr_hash, l1_serialized="l1-identity-sdjwt")
print(f"  L1 issued: {resp.credential_track_state}")

# L2: User creates autonomous mandate with constraints
resp = user.create_l2_mandate(
    job_id,
    agr_hash,
    mode="autonomous",
    l2_serialized="l2-autonomous-sdjwt",
    constraints={
        "payment_amount": {"min_amount": 0, "max_amount": 15000},
        "allowed_merchants": {"merchant_ids": [merchant.pubkey]},
    },
)
print(f"  L2 created: {resp.credential_track_state}")

# Verify L2 chain
resp = cred_provider.verify_l2(job_id, agr_hash)
print(f"  L2 verified: {resp.credential_track_state}")

# L3a: Agent creates payment fulfillment
resp = agent.create_l3a_payment(
    job_id,
    agr_hash,
    l3a_serialized="l3a-payment-sdjwt",
    transaction_id="fx-001",
    payee="exchange-service",
    amount=10000,
    currency="USD",
)
print(f"  L3a created: {resp.credential_track_state}")

# L3b: Agent creates checkout fulfillment
resp = agent.create_l3b_checkout(
    job_id,
    agr_hash,
    l3b_serialized="l3b-checkout-sdjwt",
    checkout_jwt="checkout-fx-001",
    merchant_id=merchant.pubkey,
)
print(f"  L3b created: {resp.credential_track_state}")

# Verify full chain
resp = payment_network.verify_chain(job_id, agr_hash)
print(f"  Chain verified: {resp.credential_track_state}")

# ── Phase 3: Principal Track (UW + Premium + Collateral) ────────────────────

print("\n── Phase 3: Principal Track (Underwriting) ──")

# Merchant requests UW
resp = merchant.request_uw(job_id, agr_hash)
print(f"  UW requested: {resp.principal_track_state}")

# Underwriter decides: approve with premium and collateral
resp = underwriter.uw_decide(
    job_id, agr_hash, approve=True, premium=200, collateral_required=5000,
)
print(f"  UW decided: approve=True, premium=$200, collateral=$5000")
print(f"    Principal track: {resp.principal_track_state}")
auto = resp.model_dump().get("auto_action")
if auto:
    print(f"    Auto-action: {auto} ({resp.model_dump().get('reason')})")

# Agent auto-pays premium ($200 <= max_premium $500)
resp = user.pay_premium(job_id, agr_hash, premium_ref="premium-fx-001")
print(f"  Premium paid: {resp.principal_track_state}")

# Merchant locks collateral
resp = merchant.lock_collateral(job_id, agr_hash)
print(f"  Collateral locked: {resp.collateral_ref}")

# ── Phase 4: Fee Track ──────────────────────────────────────────────────────

print("\n── Phase 4: Fee Track (Escrow) ──")

resp = user.lock_fee(job_id, agr_hash)
print(f"  Fee locked: {resp.fee_track_state} (ref: {resp.lock_ref})")

# ── Phase 5: Delivery + Evaluation ──────────────────────────────────────────

print("\n── Phase 5: Delivery + Evaluation ──")

resp = merchant.submit_deliverable(
    job_id, agr_hash, deliverable_ref="fx-confirmation-001"
)
print(f"  Delivered: {resp.deliverable_ref}")

resp = evaluator.evaluate(job_id, agr_hash, verdict="pass")
print(f"  Evaluated: {resp.verdict}")

# ── Phase 6: Settlement ─────────────────────────────────────────────────────

print("\n── Phase 6: Settlement ──")

resp = user.settle_fee(job_id, agr_hash, action="release")
print(f"  Fee settled: {resp.fee_track_state}")
print(f"  Phase: {resp.phase}")
collateral_ref = resp.model_dump().get("collateral_settlement_ref")
if collateral_ref:
    print(f"  Collateral auto-unlocked: {collateral_ref}")

# ── Final State ─────────────────────────────────────────────────────────────

print("\n── Final State ──")
state = user.get_job(job_id)
print(f"  Phase: {state['phase']}")
print(f"  Fee track: {state.get('fee_track_state')}")
print(f"  Credential track: {state.get('credential_track_state')}")
print(f"  Principal track: {state.get('principal_track_state')}")

# Selective presentations
merchant_view = tc.get(f"/jobs/{job_id}/credentials/present/merchant").json()
network_view = tc.get(f"/jobs/{job_id}/credentials/present/network").json()
print(
    f"\n  Merchant sees: L3b checkout = {'yes' if merchant_view.get('l3b_checkout') else 'no'}, L3a payment = {'yes' if merchant_view.get('l3a_payment') else 'no'}"
)
print(
    f"  Network sees:  L3a payment = {'yes' if network_view.get('l3a_payment') else 'no'}, L3b checkout = {'yes' if network_view.get('l3b_checkout') else 'no'}"
)

print("\n" + "=" * 60)
print("Done. All phases completed successfully.")
print("=" * 60)

tc.__exit__(None, None, None)
