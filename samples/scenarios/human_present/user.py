#!/usr/bin/env python3
"""User actor: creates jobs, mandates, approves, locks fee, settles."""

import json
import sys
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


def get_client():
    state = load_state()
    if "user_key" not in state:
        sk = SigningKey.generate()
        state["user_key"] = sk.encode().hex()
        save_state(state)
    else:
        sk = SigningKey(bytes.fromhex(state["user_key"]))
    return UserClient(base_url=SERVER, signing_key=sk), state


def cmd_create():
    client, state = get_client()

    # Generate keys for other actors if not already set
    for role in ["shopping_agent", "cred_provider", "processor"]:
        if f"{role}_key" not in state:
            sk = SigningKey.generate()
            state[f"{role}_key"] = sk.encode().hex()
            state[f"{role}_pubkey"] = sk.verify_key.encode().hex()

    save_state(state)

    agreement = {
        "version": "ap2_ars/0.1",
        "job_type": "purchase",
        "description": "Human-present purchase demo",
        "modality": "human-present",
        "user_pubkey": client.pubkey,
        "shopping_agent_pubkey": state["shopping_agent_pubkey"],
        "evaluator_pubkey": state.get("evaluator_pubkey", ""),
        "credentials_provider_pubkey": state["cred_provider_pubkey"],
        "merchant_pubkey": state.get("merchant_pubkey", ""),
        "payment_processor_pubkey": state["processor_pubkey"],
        "fee": {"amount": 5000, "currency": "USD"},
    }

    # Check if merchant/evaluator pubkeys are set
    if not agreement["merchant_pubkey"] or not agreement["evaluator_pubkey"]:
        print("Set merchant_pubkey and evaluator_pubkey in state.json first.")
        print("Run merchant.py and evaluator.py to generate their keys.")
        save_state(state)
        return

    job = client.create_job(agreement)
    state["job_id"] = job.job_id
    state["agreement_hash"] = job.agreement_hash
    save_state(state)

    print(f"Job created: {job.job_id}")
    print(f"Agreement hash: {job.agreement_hash}")

    # User signs
    client.sign_agreement(job.job_id, job.agreement_hash)
    print("User signed agreement")


def cmd_intent():
    client, state = get_client()
    resp = client.create_intent_mandate(
        state["job_id"],
        state["agreement_hash"],
        budget=5000,
        allowed_merchants=[state["merchant_pubkey"]],
        description="Buy widgets",
    )
    print(f"IntentMandate created (state: {resp.mandate_track_state})")


def cmd_approve_cart():
    client, state = get_client()
    resp = client.approve_cart(state["job_id"], state["agreement_hash"])
    print(f"Cart approved (state: {resp.mandate_track_state})")


def cmd_sign_payment():
    client, state = get_client()

    # Credentials provider creates payment mandate first
    cred_sk = SigningKey(bytes.fromhex(state["cred_provider_key"]))
    cred_client = UserClient(base_url=SERVER, signing_key=cred_sk)
    cred_client._post_envelope(
        f"/jobs/{state['job_id']}/mandates/payment",
        "PAYMENT_MANDATE_CREATED",
        state["job_id"],
        state["agreement_hash"],
        payload={"payment_token_hash": "tok_demo"},
    )
    print("PaymentMandate created by credentials provider")

    resp = client.sign_payment(state["job_id"], state["agreement_hash"])
    print(f"Payment signed (state: {resp.mandate_track_state})")


def cmd_lock_fee():
    client, state = get_client()
    resp = client.lock_fee(state["job_id"], state["agreement_hash"])
    print(f"Fee locked: {resp.lock_ref}")


def cmd_settle():
    client, state = get_client()
    resp = client.settle_fee(state["job_id"], state["agreement_hash"], "release")
    print(f"Fee settled: {resp.fee_track_state} (phase: {resp.phase})")


if __name__ == "__main__":
    commands = {
        "create": cmd_create,
        "intent": cmd_intent,
        "approve-cart": cmd_approve_cart,
        "sign-payment": cmd_sign_payment,
        "lock-fee": cmd_lock_fee,
        "settle": cmd_settle,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(f"Usage: python user.py <{'|'.join(commands)}>")
        sys.exit(1)
    commands[sys.argv[1]]()
