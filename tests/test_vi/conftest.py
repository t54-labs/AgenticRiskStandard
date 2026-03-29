"""VI test fixtures and helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from abstract_ars.crypto import sign_envelope
from vi.server.crypto import generate_es256_keypair, public_key_to_jwk
from vi.server.server import create_app


# ── Ed25519 key fixtures (7 actors) ─────────────────────────────────────────


@pytest.fixture()
def user_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


@pytest.fixture()
def agent_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


@pytest.fixture()
def evaluator_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


@pytest.fixture()
def cred_provider_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


@pytest.fixture()
def merchant_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


@pytest.fixture()
def payment_network_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


@pytest.fixture()
def underwriter_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


# ── ES256 key fixtures (for VI credential chain) ────────────────────────────


@pytest.fixture()
def user_es256():
    private_key, jwk = generate_es256_keypair()
    return private_key, jwk


@pytest.fixture()
def agent_es256():
    private_key, jwk = generate_es256_keypair()
    return private_key, jwk


@pytest.fixture()
def cred_provider_es256():
    private_key, jwk = generate_es256_keypair()
    return private_key, jwk


@pytest.fixture()
def merchant_es256():
    private_key, jwk = generate_es256_keypair()
    return private_key, jwk


@pytest.fixture()
def payment_network_es256():
    private_key, jwk = generate_es256_keypair()
    return private_key, jwk


# ── App / client ─────────────────────────────────────────────────────────────


@pytest.fixture()
def app():
    return create_app(db_path=":memory:")


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


# ── Agreement helpers ────────────────────────────────────────────────────────


def make_vi_agreement_dict(
    user_pk: str,
    agent_pk: str,
    eval_pk: str,
    cred_pk: str,
    merchant_pk: str,
    network_pk: str,
    user_jwk: dict,
    agent_jwk: dict,
    cred_jwk: dict,
    merchant_jwk: dict,
    network_jwk: dict,
    mode: str = "autonomous",
    **overrides,
) -> dict:
    base = {
        "version": "vi_ars/0.1",
        "job_type": "purchase",
        "description": "Test VI job",
        "mode": mode,
        "user_pubkey": user_pk,
        "agent_pubkey": agent_pk,
        "evaluator_pubkey": eval_pk,
        "credential_provider_pubkey": cred_pk,
        "merchant_pubkey": merchant_pk,
        "payment_network_pubkey": network_pk,
        "user_jwk": user_jwk,
        "agent_jwk": agent_jwk,
        "credential_provider_jwk": cred_jwk,
        "merchant_jwk": merchant_jwk,
        "payment_network_jwk": network_jwk,
        "fee": {"amount": 1000, "currency": "USD"},
    }
    base.update(overrides)
    return base


# ── Envelope helpers ─────────────────────────────────────────────────────────


def make_vi_envelope(
    event_type: str,
    job_id: str,
    agreement_hash: str,
    payload: dict,
    signing_key: SigningKey,
) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    body = {
        "type": event_type,
        "job_id": job_id,
        "agreement_hash": agreement_hash,
        "payload": payload,
        "actor": signing_key.verify_key.encode().hex(),
        "timestamp": ts,
    }
    sig = sign_envelope(signing_key, body)
    body["signature"] = sig
    return body


def make_vi_create_request(payload: dict, signing_key: SigningKey) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    body = {
        "type": "JOB_CREATED",
        "payload": payload,
        "actor": signing_key.verify_key.encode().hex(),
        "timestamp": ts,
    }
    sig = sign_envelope(signing_key, body)
    body["signature"] = sig
    return body
