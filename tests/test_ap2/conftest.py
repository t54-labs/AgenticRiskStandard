"""AP2 test fixtures and helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from ars.crypto import canonicalize, sign_envelope

from ap2.server.server import create_app


# ── Key fixtures (8 actors) ──────────────────────────────────────────────────


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
def processor_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


@pytest.fixture()
def underwriter_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


# ── App / client ──────────────────────────────────────────────────────────────


@pytest.fixture()
def app():
    return create_app(db_path=":memory:")


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


# ── Agreement helpers ─────────────────────────────────────────────────────────


def make_ap2_agreement_dict(
    user_pk: str,
    agent_pk: str,
    eval_pk: str,
    cred_pk: str,
    merchant_pk: str,
    processor_pk: str,
    modality: str = "human-present",
    **overrides,
) -> dict:
    base = {
        "version": "ap2_ars/0.1",
        "job_type": "purchase",
        "description": "Test AP2 job",
        "modality": modality,
        "user_pubkey": user_pk,
        "shopping_agent_pubkey": agent_pk,
        "evaluator_pubkey": eval_pk,
        "credentials_provider_pubkey": cred_pk,
        "merchant_pubkey": merchant_pk,
        "payment_processor_pubkey": processor_pk,
        "fee": {"amount": 1000, "currency": "USD"},
    }
    base.update(overrides)
    return base


def make_fund_moving_ap2_agreement_dict(
    user_pk: str,
    agent_pk: str,
    eval_pk: str,
    cred_pk: str,
    merchant_pk: str,
    processor_pk: str,
    uw_pk: str,
    **overrides,
) -> dict:
    base = make_ap2_agreement_dict(
        user_pk, agent_pk, eval_pk, cred_pk, merchant_pk, processor_pk,
    )
    base.update(
        {
            "job_type": "fund-moving",
            "underwriter_pubkey": uw_pk,
            "principal": {
                "amount": 50000,
                "currency": "USD",
                "destination": "acct_123",
            },
        }
    )
    base.update(overrides)
    return base


# ── Envelope helpers ──────────────────────────────────────────────────────────


def make_ap2_envelope(
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


def make_ap2_create_request(payload: dict, signing_key: SigningKey) -> dict:
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


# ── Intent mandate helper ─────────────────────────────────────────────────────


def make_intent_mandate_payload(
    user_pk: str,
    job_id: str,
    budget: int = 5000,
    allowed_merchants: list[str] | None = None,
    ttl_seconds: int = 3600,
    requires_principal: bool = False,
) -> dict:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=ttl_seconds)
    return {
        "header": {
            "iss": user_pk,
            "sub": job_id,
            "iat": now.isoformat(),
            "exp": exp.isoformat(),
            "vdc_type": "intent",
        },
        "budget": budget,
        "currency": "USD",
        "allowed_merchants": allowed_merchants or [],
        "sku_patterns": ["*"],
        "description": "Test intent",
        "requires_principal": requires_principal,
        "signature": "placeholder",
    }


def make_cart_mandate_payload(
    merchant_pk: str, job_id: str, total: int = 2000,
) -> dict:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=900)
    return {
        "header": {
            "iss": merchant_pk,
            "sub": job_id,
            "iat": now.isoformat(),
            "exp": exp.isoformat(),
            "vdc_type": "cart",
        },
        "cart_hash": "abc123",
        "line_items": [
            {
                "sku": "ITEM-001",
                "description": "Widget",
                "quantity": 1,
                "unit_price": total,
            },
        ],
        "total": total,
        "merchant_id": merchant_pk,
        "signature": "placeholder",
    }
