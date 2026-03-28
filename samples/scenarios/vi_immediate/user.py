#!/usr/bin/env python3
"""VI immediate mode: User actor — creates job, L2 mandate, locks fee, settles."""

from __future__ import annotations

import json
import os
import sys

from nacl.signing import SigningKey

from vi.client.user import VIUserClient
from vi.server.crypto import generate_es256_keypair, public_key_to_jwk

SERVER = os.environ.get("ARS_SERVER_URL", "http://127.0.0.1:8000")
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {}


def save_state(state: dict) -> None:
    json.dump(state, open(STATE_FILE, "w"), indent=2)


def cmd_create(state: dict) -> None:
    """Create job and sign agreement."""
    # Generate user keys
    sk = SigningKey.generate()
    state["user_key"] = sk.encode().hex()
    state["user_pubkey"] = sk.verify_key.encode().hex()

    # Generate ES256 keys for VI credential chain
    _, user_jwk = generate_es256_keypair()
    state["user_jwk"] = user_jwk

    # Read other actor pubkeys from state (must be set by other scripts first)
    merchant_pk = state.get("merchant_pubkey")
    eval_pk = state.get("evaluator_pubkey")
    cred_pk = state.get("cred_provider_pubkey")

    if not all([merchant_pk, eval_pk, cred_pk]):
        print("ERROR: Run merchant.py, evaluator.py, and credential_provider.py first")
        sys.exit(1)

    # Generate payment network keys (infrastructure, managed by user in example)
    net_sk = SigningKey.generate()
    state["network_key"] = net_sk.encode().hex()
    state["network_pubkey"] = net_sk.verify_key.encode().hex()
    _, net_jwk = generate_es256_keypair()
    state["network_jwk"] = net_jwk

    client = VIUserClient(base_url=SERVER, signing_key=sk)

    agreement = {
        "version": "vi_ars/0.1",
        "job_type": "purchase",
        "description": "Immediate mode purchase",
        "mode": "immediate",
        "user_pubkey": state["user_pubkey"],
        "evaluator_pubkey": eval_pk,
        "credential_provider_pubkey": cred_pk,
        "merchant_pubkey": merchant_pk,
        "payment_network_pubkey": state["network_pubkey"],
        "user_jwk": user_jwk,
        "credential_provider_jwk": state.get("cred_provider_jwk", {}),
        "merchant_jwk": state.get("merchant_jwk", {}),
        "payment_network_jwk": net_jwk,
        "fee": {"amount": 3000, "currency": "USD"},
    }

    resp = client.create_job(agreement)
    state["job_id"] = resp.job_id
    state["agreement_hash"] = resp.agreement_hash
    print(f"Job created: {resp.job_id} (mode: immediate)")

    client.sign_agreement(resp.job_id, resp.agreement_hash)
    print("User signed agreement")
    save_state(state)


def cmd_l2(state: dict) -> None:
    """Create L2 immediate mandate."""
    sk = SigningKey(bytes.fromhex(state["user_key"]))
    client = VIUserClient(base_url=SERVER, signing_key=sk)
    resp = client.create_l2_mandate(
        state["job_id"],
        state["agreement_hash"],
        mode="immediate",
        l2_serialized="l2-immediate-purchase",
    )
    print(f"L2 immediate mandate created: {resp.credential_track_state}")


def cmd_lock_fee(state: dict) -> None:
    """Lock fee in escrow."""
    sk = SigningKey(bytes.fromhex(state["user_key"]))
    client = VIUserClient(base_url=SERVER, signing_key=sk)
    resp = client.lock_fee(state["job_id"], state["agreement_hash"])
    print(f"Fee locked: {resp.lock_ref}")


def cmd_settle(state: dict) -> None:
    """Settle fee (release)."""
    sk = SigningKey(bytes.fromhex(state["user_key"]))
    client = VIUserClient(base_url=SERVER, signing_key=sk)
    resp = client.settle_fee(state["job_id"], state["agreement_hash"], "release")
    print(f"Fee settled: {resp.fee_track_state} (phase: {resp.phase})")


if __name__ == "__main__":
    state = load_state()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "create"
    {
        "create": cmd_create,
        "l2": cmd_l2,
        "lock-fee": cmd_lock_fee,
        "settle": cmd_settle,
    }[cmd](state)
