#!/usr/bin/env python3
"""Merchant actor: signs agreements, proposes carts, delivers goods."""

import json
import sys
import os

from nacl.signing import SigningKey

from ap2.client.merchant import MerchantClient

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
    if "merchant_key" not in state:
        sk = SigningKey.generate()
        state["merchant_key"] = sk.encode().hex()
        state["merchant_pubkey"] = sk.verify_key.encode().hex()
        save_state(state)
        print(f"Merchant key generated. Pubkey: {state['merchant_pubkey'][:16]}...")
    else:
        sk = SigningKey(bytes.fromhex(state["merchant_key"]))
    return MerchantClient(base_url=SERVER, signing_key=sk), state


def cmd_sign():
    client, state = get_client()
    resp = client.sign_agreement(state["job_id"], state["agreement_hash"])
    print(f"Merchant signed agreement (phase: {resp.phase})")


def cmd_cart():
    client, state = get_client()

    # Propose cart
    line_items = [
        {
            "sku": "WIDGET-001",
            "description": "Premium Widget",
            "quantity": 2,
            "unit_price": 1500,
        },
    ]
    resp = client.propose_cart(
        state["job_id"], state["agreement_hash"], line_items, total=3000,
    )
    print(
        f"Cart proposed: 2x Premium Widget = $30.00 (state: {resp.mandate_track_state})"
    )

    # Sign cart
    client.sign_cart(state["job_id"], state["agreement_hash"])
    print("Cart signed by merchant")


def cmd_deliver():
    client, state = get_client()
    resp = client.submit_deliverable(
        state["job_id"], state["agreement_hash"], deliverable_ref="order:ORD-DEMO-001",
    )
    print(f"Delivered: {resp.deliverable_ref}")


if __name__ == "__main__":
    commands = {"sign": cmd_sign, "cart": cmd_cart, "deliver": cmd_deliver}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(f"Usage: python merchant.py <{'|'.join(commands)}>")
        sys.exit(1)
    commands[sys.argv[1]]()
