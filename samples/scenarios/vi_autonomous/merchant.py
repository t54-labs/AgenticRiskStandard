#!/usr/bin/env python3
"""VI autonomous mode: Merchant — signs, requests UW, locks collateral, delivers."""

from __future__ import annotations

import json
import os
import sys

from nacl.signing import SigningKey

from vi.client.merchant import VIMerchantClient

SERVER = os.environ.get("ARS_SERVER_URL", "http://127.0.0.1:8000")
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {}


def save_state(state: dict) -> None:
    json.dump(state, open(STATE_FILE, "w"), indent=2)


def ensure_keys(state: dict) -> None:
    if "merchant_key" not in state:
        from vi.server.crypto import generate_es256_keypair

        sk = SigningKey.generate()
        state["merchant_key"] = sk.encode().hex()
        state["merchant_pubkey"] = sk.verify_key.encode().hex()
        _, jwk = generate_es256_keypair()
        state["merchant_jwk"] = jwk
        save_state(state)
        print(f"Merchant pubkey: {state['merchant_pubkey']}")


def cmd_sign(state: dict) -> None:
    sk = SigningKey(bytes.fromhex(state["merchant_key"]))
    client = VIMerchantClient(base_url=SERVER, signing_key=sk)
    resp = client.sign_agreement(state["job_id"], state["agreement_hash"])
    print(f"Merchant signed -> phase: {resp.phase}")


def cmd_uw_request(state: dict) -> None:
    sk = SigningKey(bytes.fromhex(state["merchant_key"]))
    client = VIMerchantClient(base_url=SERVER, signing_key=sk)
    resp = client.request_uw(state["job_id"], state["agreement_hash"])
    print(f"UW requested: {resp.principal_track_state}")


def cmd_lock_collateral(state: dict) -> None:
    sk = SigningKey(bytes.fromhex(state["merchant_key"]))
    client = VIMerchantClient(base_url=SERVER, signing_key=sk)
    resp = client.lock_collateral(state["job_id"], state["agreement_hash"])
    print(f"Collateral locked: {resp.collateral_ref}")


def cmd_deliver(state: dict) -> None:
    sk = SigningKey(bytes.fromhex(state["merchant_key"]))
    client = VIMerchantClient(base_url=SERVER, signing_key=sk)
    resp = client.submit_deliverable(
        state["job_id"], state["agreement_hash"], deliverable_ref="order-auto-001",
    )
    print(f"Delivered: {resp.deliverable_ref}")


if __name__ == "__main__":
    state = load_state()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "keys"
    if cmd == "keys":
        ensure_keys(state)
    else:
        {
            "sign": cmd_sign,
            "uw-request": cmd_uw_request,
            "lock-collateral": cmd_lock_collateral,
            "deliver": cmd_deliver,
        }[cmd](state)
