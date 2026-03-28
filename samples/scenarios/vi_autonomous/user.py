#!/usr/bin/env python3
"""VI autonomous mode: User — creates fund-moving job, L2 with constraints, walks away."""

from __future__ import annotations

import json
import os
import sys

from nacl.signing import SigningKey

from vi.client.user import VIUserClient
from vi.server.crypto import generate_es256_keypair

SERVER = os.environ.get("ARS_SERVER_URL", "http://127.0.0.1:8000")
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {}


def save_state(state: dict) -> None:
    json.dump(state, open(STATE_FILE, "w"), indent=2)


def cmd_create() -> None:
    """Create job and sign agreement."""
    state = load_state()

    # Generate user keys
    sk = SigningKey.generate()
    state["user_key"] = sk.encode().hex()
    state["user_pubkey"] = sk.verify_key.encode().hex()
    _, user_jwk = generate_es256_keypair()
    state["user_jwk"] = user_jwk

    # Generate agent keys
    agent_sk = SigningKey.generate()
    state["agent_key"] = agent_sk.encode().hex()
    state["agent_pubkey"] = agent_sk.verify_key.encode().hex()
    _, agent_jwk = generate_es256_keypair()
    state["agent_jwk"] = agent_jwk

    # Generate payment network keys (infrastructure)
    net_sk = SigningKey.generate()
    state["network_key"] = net_sk.encode().hex()
    state["network_pubkey"] = net_sk.verify_key.encode().hex()
    _, net_jwk = generate_es256_keypair()
    state["network_jwk"] = net_jwk

    # Check required actor keys
    merchant_pk = state.get("merchant_pubkey")
    eval_pk = state.get("evaluator_pubkey")
    cred_pk = state.get("cred_provider_pubkey")
    uw_pk = state.get("underwriter_pubkey")

    if not all([merchant_pk, eval_pk, cred_pk, uw_pk]):
        print(
            "ERROR: Run merchant.py, evaluator.py, credential_provider.py, underwriter.py first"
        )
        sys.exit(1)

    client = VIUserClient(base_url=SERVER, signing_key=sk)

    agreement = {
        "version": "vi_ars/0.1",
        "job_type": "fund-moving",
        "description": "Autonomous agent purchase with underwriting",
        "mode": "autonomous",
        "user_pubkey": state["user_pubkey"],
        "agent_pubkey": state["agent_pubkey"],
        "evaluator_pubkey": eval_pk,
        "credential_provider_pubkey": cred_pk,
        "merchant_pubkey": merchant_pk,
        "payment_network_pubkey": state["network_pubkey"],
        "underwriter_pubkey": uw_pk,
        "user_jwk": user_jwk,
        "agent_jwk": agent_jwk,
        "credential_provider_jwk": state.get("cred_provider_jwk", {}),
        "merchant_jwk": state.get("merchant_jwk", {}),
        "payment_network_jwk": net_jwk,
        "requires_principal": True,
        "max_premium": 500,
        "allow_uw_override": True,
        "fee": {"amount": 2000, "currency": "USD"},
        "principal": {"amount": 50000, "currency": "USD", "destination": "vendor-acct"},
    }

    resp = client.create_job(agreement)
    state["job_id"] = resp.job_id
    state["agreement_hash"] = resp.agreement_hash
    print(f"Job created: {resp.job_id} (mode: autonomous, fund-moving)")

    client.sign_agreement(resp.job_id, resp.agreement_hash)
    print("User signed agreement")
    save_state(state)


def cmd_l2() -> None:
    """Create L2 autonomous mandate with constraints, then walk away."""
    state = load_state()
    sk = SigningKey(bytes.fromhex(state["user_key"]))
    client = VIUserClient(base_url=SERVER, signing_key=sk)

    resp = client.create_l2_mandate(
        state["job_id"],
        state["agreement_hash"],
        mode="autonomous",
        l2_serialized="l2-autonomous-constraints",
        constraints={
            "payment_amount": {"min_amount": 0, "max_amount": 60000},
            "allowed_merchants": {"merchant_ids": [state["merchant_pubkey"]]},
        },
    )
    print(f"L2 autonomous mandate created: {resp.credential_track_state}")
    print("User walks away. Agent takes over.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "create"
    {"create": cmd_create, "l2": cmd_l2}[cmd]()
