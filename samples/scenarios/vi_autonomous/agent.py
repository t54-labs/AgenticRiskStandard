#!/usr/bin/env python3
"""VI autonomous mode: Agent — creates L3 fulfillment, handles UW auto-actions, locks fee."""

from __future__ import annotations

import json
import os

from nacl.signing import SigningKey

from vi.client.agent import VIAgentClient
from vi.client.user import VIUserClient

SERVER = os.environ.get("ARS_SERVER_URL", "http://127.0.0.1:8000")
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def load_state() -> dict:
    return json.load(open(STATE_FILE))


if __name__ == "__main__":
    state = load_state()
    job_id = state["job_id"]
    agr_hash = state["agreement_hash"]

    agent_sk = SigningKey(bytes.fromhex(state["agent_key"]))
    agent = VIAgentClient(base_url=SERVER, signing_key=agent_sk)

    # Create L3a payment fulfillment
    resp = agent.create_l3a_payment(
        job_id,
        agr_hash,
        l3a_serialized="l3a-payment-fulfillment",
        transaction_id="tx-auto-001",
        payee="vendor-acct",
        amount=50000,
        currency="USD",
    )
    print(f"L3a created: {resp.credential_track_state}")

    # Create L3b checkout fulfillment
    resp = agent.create_l3b_checkout(
        job_id,
        agr_hash,
        l3b_serialized="l3b-checkout-fulfillment",
        checkout_jwt="checkout-auto-001",
        merchant_id=state["merchant_pubkey"],
    )
    print(f"L3b created: {resp.credential_track_state}")

    print("Agent: L3 credentials created. Waiting for chain verification...")
