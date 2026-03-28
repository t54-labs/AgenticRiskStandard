#!/usr/bin/env python3
"""VI immediate mode: Credential Provider — issues L1, verifies L2."""

from __future__ import annotations

import json
import os
import sys

from nacl.signing import SigningKey

from vi.client.credential_provider import VICredentialProviderClient
from vi.server.crypto import generate_es256_keypair

SERVER = os.environ.get("ARS_SERVER_URL", "http://127.0.0.1:8000")
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {}


def save_state(state: dict) -> None:
    json.dump(state, open(STATE_FILE, "w"), indent=2)


def ensure_keys(state: dict) -> None:
    if "cred_provider_key" not in state:
        sk = SigningKey.generate()
        state["cred_provider_key"] = sk.encode().hex()
        state["cred_provider_pubkey"] = sk.verify_key.encode().hex()
        es256_key, jwk = generate_es256_keypair()
        state["cred_provider_jwk"] = jwk
        save_state(state)
        print(f"Credential provider pubkey: {state['cred_provider_pubkey']}")


def cmd_l1(state: dict) -> None:
    """Issue L1 identity credential."""
    sk = SigningKey(bytes.fromhex(state["cred_provider_key"]))
    client = VICredentialProviderClient(base_url=SERVER, signing_key=sk)
    resp = client.issue_l1(
        state["job_id"], state["agreement_hash"], l1_serialized="l1-issuer-credential",
    )
    print(f"L1 issued: {resp.credential_track_state}")


def cmd_verify_l2(state: dict) -> None:
    """Verify L1 -> L2 chain."""
    sk = SigningKey(bytes.fromhex(state["cred_provider_key"]))
    client = VICredentialProviderClient(base_url=SERVER, signing_key=sk)
    resp = client.verify_l2(state["job_id"], state["agreement_hash"])
    print(f"L2 verified: {resp.credential_track_state}")


if __name__ == "__main__":
    state = load_state()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "keys"
    if cmd == "keys":
        ensure_keys(state)
    else:
        {"l1": cmd_l1, "verify-l2": cmd_verify_l2}[cmd](state)
