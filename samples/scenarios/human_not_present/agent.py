#!/usr/bin/env python3
"""Shopping agent: orchestrates autonomous purchase on user's behalf.

The agent reads state, coordinates with the merchant, and ensures
the mandate flow completes within the user's constraints. It then
triggers fee lock and settlement using the user's pre-authorized keys.
"""

import json
import os

from nacl.signing import SigningKey

from ap2.client.shopping_agent import ShoppingAgentClient
from ap2.client.user import UserClient

SERVER = os.environ.get("ARS_SERVER_URL", "http://127.0.0.1:8000")
STATE_FILE = "state.json"


def load_state():
    with open(STATE_FILE) as f:
        return json.load(f)


def main():
    state = load_state()
    agent_sk = SigningKey(bytes.fromhex(state["shopping_agent_key"]))
    agent = ShoppingAgentClient(base_url=SERVER, signing_key=agent_sk)

    job_id = state["job_id"]
    agr_hash = state["agreement_hash"]

    print("Shopping agent taking over...")

    # Check current state
    mandates = agent.get_mandates(job_id)
    print(f"Mandate state: {mandates['mandate_track_state']}")
    print(f"Intent mandate: {'present' if mandates['intent_mandate'] else 'missing'}")

    # Wait for merchant to propose and sign cart
    # (In a real system, the agent would negotiate with the merchant)
    print("Waiting for merchant to propose cart...")

    # After merchant has proposed and signed, check constraints
    mandates = agent.get_mandates(job_id)
    if mandates["mandate_track_state"] == "CART_SIGNED":
        constraints = agent.check_constraints(job_id)
        result = constraints.get("result", {})
        if result and result.get("allowed"):
            print("Constraint check: PASSED")
        else:
            violations = result.get("violations", []) if result else []
            print(f"Constraint check: FAILED ({len(violations)} violations)")
            for v in violations:
                print(f"  - {v['field']}: {v['message']}")
            return

    # Credentials provider auto-signs payment in not-present mode
    cred_sk = SigningKey(bytes.fromhex(state["cred_provider_key"]))
    cred_client = UserClient(base_url=SERVER, signing_key=cred_sk)
    cred_client._post_envelope(
        f"/jobs/{job_id}/mandates/payment",
        "PAYMENT_MANDATE_CREATED",
        job_id,
        agr_hash,
        payload={"payment_token_hash": "tok_auto"},
    )
    print("Credentials provider created PaymentMandate")

    cred_client._post_envelope(
        f"/jobs/{job_id}/mandates/payment/sign",
        "PAYMENT_MANDATE_SIGNED",
        job_id,
        agr_hash,
    )
    print("Credentials provider signed payment (autonomous mode)")

    # Now trigger fee lock using user's key (pre-authorized)
    user_sk = SigningKey(bytes.fromhex(state["user_key"]))
    user = UserClient(base_url=SERVER, signing_key=user_sk)

    lock = user.lock_fee(job_id, agr_hash)
    print(f"Fee locked: {lock.lock_ref}")

    print("\nMandate complete. Waiting for merchant to deliver...")


if __name__ == "__main__":
    main()
