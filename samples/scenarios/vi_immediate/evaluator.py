#!/usr/bin/env python3
"""VI immediate mode: Evaluator — issues pass/fail verdict."""

from __future__ import annotations

import json
import os

from nacl.signing import SigningKey

from abstract_ars_client.evaluator import EvaluatorClient

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

    if "evaluator_key" not in state:
        sk = SigningKey.generate()
        state["evaluator_key"] = sk.encode().hex()
        state["evaluator_pubkey"] = sk.verify_key.encode().hex()
        save_state(state)
        print(f"Evaluator pubkey: {state['evaluator_pubkey']}")
    else:
        sk = SigningKey(bytes.fromhex(state["evaluator_key"]))
        client = EvaluatorClient(base_url=SERVER, signing_key=sk)
        resp = client.evaluate(state["job_id"], state["agreement_hash"], verdict="pass")
        print(f"Evaluated: {resp.verdict}")
