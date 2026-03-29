from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from abstract_ars.crypto import (
    compute_agreement_hash,
    envelope_body,
    sign_envelope,
)
from abstract_ars.models import EventType
from abstract_ars.server import create_app


@pytest.fixture()
def app():
    return create_app(db_path=":memory:")


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def requestor_keys():
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
def underwriter_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


@pytest.fixture()
def settlement_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


def make_envelope(
    event_type: EventType,
    job_id: str,
    agreement_hash: str,
    payload: dict,
    signing_key: SigningKey,
) -> dict:
    """Build a signed envelope dict ready to POST as JSON."""
    pubkey_hex = signing_key.verify_key.encode().hex()
    body = {
        "type": event_type.value,
        "job_id": job_id,
        "agreement_hash": agreement_hash,
        "payload": payload,
        "actor": pubkey_hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    sig = sign_envelope(signing_key, body)
    body["signature"] = sig
    return body


def make_create_request(payload: dict, signing_key: SigningKey) -> dict:
    """Build a signed CreateJobRequest dict (no job_id / agreement_hash)."""
    pubkey_hex = signing_key.verify_key.encode().hex()
    body = {
        "type": "JOB_CREATED",
        "payload": payload,
        "actor": pubkey_hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    sig = sign_envelope(signing_key, body)
    body["signature"] = sig
    return body


def make_agreement_dict(req_pk: str, agent_pk: str, eval_pk: str, **overrides) -> dict:
    """Return a plain dict representing an AgreementDraft."""
    agr = {
        "version": "ars/0.1",
        "job_type": "code_review",
        "description": "Review PR #42",
        "requestor_pubkey": req_pk,
        "business_agent_pubkey": agent_pk,
        "evaluator_pubkey": eval_pk,
        "fee": {"amount": 500, "currency": "USD"},
    }
    agr.update(overrides)
    return agr


def make_fund_moving_agreement_dict(
    req_pk: str, agent_pk: str, eval_pk: str, uw_pk: str, settle_pk: str, **overrides,
) -> dict:
    """Return a plain dict for a fund-moving agreement with principal terms."""
    agr = {
        "version": "ars/0.1",
        "job_type": "fund-moving",
        "description": "Transfer funds to vendor",
        "requestor_pubkey": req_pk,
        "business_agent_pubkey": agent_pk,
        "evaluator_pubkey": eval_pk,
        "fee": {"amount": 100, "currency": "USD"},
        "underwriter_pubkey": uw_pk,
        "settlement_layer_pubkey": settle_pk,
        "principal": {"amount": 10000, "currency": "USD", "destination": "vendor-acct"},
    }
    agr.update(overrides)
    return agr
