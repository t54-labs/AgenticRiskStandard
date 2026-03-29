#!/usr/bin/env python3
"""VI autonomous mode: Underwriter — assesses risk, sets premium/collateral terms."""

from __future__ import annotations

import json
import os
import sys

from nacl.signing import SigningKey

from abstract_ars_client.underwriter import UnderwriterClient

SERVER = os.environ.get("ARS_SERVER_URL", "http://127.0.0.1:8000")
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {}


def save_state(state: dict) -> None:
    json.dump(state, open(STATE_FILE, "w"), indent=2)


if __name__ == "__main__":
    state = load_state()

    if "underwriter_key" not in state:
        sk = SigningKey.generate()
        state["underwriter_key"] = sk.encode().hex()
        state["underwriter_pubkey"] = sk.verify_key.encode().hex()
        save_state(state)
        print(f"Underwriter pubkey: {state['underwriter_pubkey']}")
    else:
        sk = SigningKey(bytes.fromhex(state["underwriter_key"]))
        client = UnderwriterClient(base_url=SERVER, signing_key=sk)
        resp = client.uw_decide(
            state["job_id"],
            state["agreement_hash"],
            approve=True,
            premium=200,
            collateral_required=5000,
        )
        print(f"UW decided: approve=True, premium=$200, collateral=$5000")
        print(f"  Principal track: {resp.principal_track_state}")
        auto = resp.model_dump().get("auto_action")
        if auto:
            print(f"  Auto-action: {auto}")
