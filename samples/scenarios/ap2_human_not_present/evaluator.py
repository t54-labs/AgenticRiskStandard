#!/usr/bin/env python3
"""Evaluator actor for autonomous scenario."""

import json
import os

from nacl.signing import SigningKey

from abstract_ars_client.evaluator import EvaluatorClient

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

    if "evaluator_key" not in state:
        sk = SigningKey.generate()
        state["evaluator_key"] = sk.encode().hex()
        state["evaluator_pubkey"] = sk.verify_key.encode().hex()
        save_state(state)
    else:
        sk = SigningKey(bytes.fromhex(state["evaluator_key"]))

    client = EvaluatorClient(base_url=SERVER, signing_key=sk)
    resp = client.evaluate(state["job_id"], state["agreement_hash"], "pass")
    print(f"Evaluator verdict: {resp.verdict}")


if __name__ == "__main__":
    main()
