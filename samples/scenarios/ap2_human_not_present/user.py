#!/usr/bin/env python3
"""User actor: creates job, signs intent mandate, then walks away.

In human-not-present mode, the user sets up the job and constraints,
then the shopping agent handles the rest autonomously.
"""

import json
import os

from nacl.signing import SigningKey

from ap2.client.user import UserClient

SERVER = os.environ.get("ARS_SERVER_URL", "http://127.0.0.1:8000")
STATE_FILE = "state.json"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def main():
    state = load_state()

    # Generate user key
    if "user_key" not in state:
        sk = SigningKey.generate()
        state["user_key"] = sk.encode().hex()
    else:
        sk = SigningKey(bytes.fromhex(state["user_key"]))

    # Generate infra keys
    for role in ["shopping_agent", "cred_provider", "processor"]:
        if f"{role}_key" not in state:
            rsk = SigningKey.generate()
            state[f"{role}_key"] = rsk.encode().hex()
            state[f"{role}_pubkey"] = rsk.verify_key.encode().hex()

    save_state(state)

    # Check dependencies
    if not state.get("merchant_pubkey") or not state.get("evaluator_pubkey"):
        print("Run merchant.py and evaluator.py first to generate their keys.")
        return

    client = UserClient(base_url=SERVER, signing_key=sk)

    # Create job with human-not-present modality
    agreement = {
        "version": "ap2_ars/0.1",
        "job_type": "purchase",
        "description": "Autonomous purchase demo",
        "modality": "human-not-present",
        "user_pubkey": client.pubkey,
        "shopping_agent_pubkey": state["shopping_agent_pubkey"],
        "evaluator_pubkey": state["evaluator_pubkey"],
        "credentials_provider_pubkey": state["cred_provider_pubkey"],
        "merchant_pubkey": state["merchant_pubkey"],
        "payment_processor_pubkey": state["processor_pubkey"],
        "fee": {"amount": 10000, "currency": "USD"},
    }

    job = client.create_job(agreement)
    state["job_id"] = job.job_id
    state["agreement_hash"] = job.agreement_hash
    save_state(state)
    print(f"Job created: {job.job_id[:16]}... (modality: human-not-present)")

    # Sign agreement
    client.sign_agreement(job.job_id, job.agreement_hash)
    print("User signed agreement")

    # Create intent mandate with constraints
    intent = client.create_intent_mandate(
        job.job_id,
        job.agreement_hash,
        budget=10000,
        allowed_merchants=[state["merchant_pubkey"]],
        description="Buy up to $100 of widgets from approved merchants",
        sku_patterns=["WIDGET-*"],
    )
    print(f"IntentMandate created: budget=$100, merchants=1, SKUs=WIDGET-*")
    print(f"  (state: {intent.mandate_track_state})")

    print("\nUser walks away. Shopping agent takes over.")


if __name__ == "__main__":
    main()
