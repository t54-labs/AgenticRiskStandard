# Agentic Risk Standard

A settlement-layer protocol for trustworthy AI agent services. ARS provides cryptographically signed, event-sourced job lifecycle management with fee escrow, underwriting, and principal release tracks.

## Overview

When a human (or organization) delegates a task to an AI agent, both sides need guarantees: the requestor needs assurance the agent will deliver, and the agent needs assurance it will be paid. ARS solves this by introducing a structured protocol where:

- Every action is an **Ed25519-signed event** appended to an immutable log
- Fees are held in **escrow** until an independent evaluator confirms delivery
- For high-value fund-moving jobs, an **underwriting track** gates principal release behind risk assessment, collateral, and multi-party approval
- All state is **derived by replaying the event log** — there is no mutable state to corrupt

## Roles

ARS defines six participant roles. Each role is identified by an Ed25519 public key and can only perform specific actions:

| Role | Description |
|------|-------------|
| **Requestor** | Creates jobs, locks fee escrow, pays premiums, approves principal release |
| **Business Agent** | Signs agreements, submits deliverables, requests underwriting, submits execution evidence |
| **Evaluator** | Independently evaluates deliverable quality (pass/fail verdict) |
| **Underwriter** | Assesses risk for fund-moving jobs; approves/rejects with premium and collateral terms |
| **Human Authority** | Provides override decisions when underwriting rejects or collateral is refused |
| **Settlement Layer** | Executes principal fund transfers after all approvals are in place |

## Job Lifecycle

### Fee Track (all jobs)

Every job follows the fee track, which manages the service fee through escrow:

```
REQUEST ──> NEGOTIATION ──> TRANSACTION ──> EVALUATION ──> CLOSED
  │              │               │               │            │
  Create     Propose /       Lock fee →     Evaluator     Settle
  job        counter-        Deliver         verdicts     (release
             propose,                       pass/fail     or refund)
             both sign
```

1. **Requestor** creates a job with an agreement draft (`POST /jobs`)
2. Either party submits counter-proposals (`POST /jobs/{id}/proposals`)
3. Both **requestor** and **business agent** sign the agreement (`POST /jobs/{id}/signatures`)
4. **Requestor** locks the fee in escrow (`POST /jobs/{id}/fee/lock`)
5. **Business agent** submits the deliverable (`POST /jobs/{id}/deliverable`)
6. **Evaluator** evaluates the outcome — pass or fail (`POST /jobs/{id}/evaluate`)
7. Fee is settled — released to agent on pass, refunded to requestor on fail (`POST /jobs/{id}/fee/settle`)

### Principal Track (fund-moving jobs)

Jobs with `job_type: "fund-moving"` or a `principal` field activate a second track that runs in parallel with the fee track:

```
UW_AWAIT_REQUEST ──> UW_REVIEW ──> [PREMIUM_PENDING] ──> [COLLATERAL_REQUESTED]
       │                  │               │                        │
   Agent requests    Underwriter      Requestor pays         Requestor locks
   underwriting      decides          premium (if any)       collateral (if any)
                         │
                    If rejected ──> OVERRIDE_PENDING ──> Human authority decides
                                                              │
                                              ┌───────────────┘
                                              v
                                     APPROVAL_PENDING ──> RELEASABLE ──> EXECUTION_PENDING
                                           │                    │                │
                                      Requestor           Settlement        Agent submits
                                      approves             layer            execution
                                      release             releases          evidence
                                                          principal
```

## Quickstart

### Install

```bash
pip install -e ".[dev]"
```

### Run the server

```bash
uvicorn ars.server:app --host 0.0.0.0 --port 8000
```

### Run tests

```bash
pytest tests/ -v
```

## Connecting to the Protocol

### Generating Keys

Every participant needs an Ed25519 keypair. Using Python with PyNaCl:

```python
from nacl.signing import SigningKey

sk = SigningKey.generate()
public_key_hex = sk.verify_key.encode().hex()
print(f"Public key: {public_key_hex}")
# Share this public key — it identifies you in agreements
```

### Signing Envelopes

Every action sent to the server is a **signed envelope**. The signing process:

1. Build the envelope body (all fields except `signature`)
2. Canonicalize (sorted-key JSON, no whitespace)
3. Sign with Ed25519
4. Attach the hex-encoded signature

```python
import json
from nacl.signing import SigningKey

def canonicalize(obj: dict) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

def sign_envelope(signing_key: SigningKey, body: dict) -> str:
    canonical = canonicalize(body)
    signed = signing_key.sign(canonical)
    return signed.signature.hex()

# Example: sign an AGREEMENT_SIGNED envelope
body = {
    "type": "AGREEMENT_SIGNED",
    "job_id": "<job-id>",
    "agreement_hash": "<hash>",
    "payload": {},
    "actor": public_key_hex,
    "timestamp": "2025-01-01T00:00:00+00:00",
}
signature = sign_envelope(sk, body)
body["signature"] = signature
# POST body as JSON to the appropriate endpoint
```

### Agreement Hash

Every action (except job creation) must reference the SHA-256 hash of the canonicalized agreement:

```python
import hashlib

agreement_hash = hashlib.sha256(canonicalize(agreement_dict)).hexdigest()
```

The server computes and returns this hash when a job is created or a proposal is submitted.

## API Reference

### Job Creation

| Method | Path | Actor | Description |
|--------|------|-------|-------------|
| `POST` | `/jobs` | Requestor | Create a new job |

Request body (CreateJobRequest — no `job_id` or `agreement_hash`):

```json
{
  "type": "JOB_CREATED",
  "payload": {
    "agreement": {
      "version": "ars/0.1",
      "job_type": "code_review",
      "description": "Review PR #42",
      "requestor_pubkey": "<requestor-pk>",
      "business_agent_pubkey": "<agent-pk>",
      "evaluator_pubkey": "<evaluator-pk>",
      "fee": {"amount": 500, "currency": "USD"}
    }
  },
  "actor": "<requestor-pk>",
  "timestamp": "2025-01-01T00:00:00+00:00",
  "signature": "<hex-signature>"
}
```

For fund-moving jobs, add underwriting fields to the agreement:

```json
{
  "agreement": {
    "job_type": "fund-moving",
    "underwriter_pubkey": "<uw-pk>",
    "human_authority_pubkey": "<authority-pk>",
    "settlement_layer_pubkey": "<settlement-pk>",
    "principal": {"amount": 10000, "currency": "USD", "destination": "vendor-acct"},
    ...
  }
}
```

Response: `{"job_id": "<uuid>", "agreement_hash": "<sha256-hex>", "phase": "NEGOTIATION"}`

### Fee Track Endpoints

All subsequent endpoints accept a `SignedActionEnvelope`:

```json
{
  "type": "<EVENT_TYPE>",
  "job_id": "<job-id>",
  "agreement_hash": "<agreement-hash>",
  "payload": { ... },
  "actor": "<actor-public-key>",
  "timestamp": "<iso-8601-utc>",
  "signature": "<hex-signature>"
}
```

| Method | Path | Event Type | Actor | Required Payload |
|--------|------|-----------|-------|------------------|
| `POST` | `/jobs/{id}/proposals` | `PROPOSAL_SUBMITTED` | Requestor or Agent | `{"agreement": {...}}` |
| `POST` | `/jobs/{id}/signatures` | `AGREEMENT_SIGNED` | Requestor or Agent | `{}` |
| `POST` | `/jobs/{id}/fee/lock` | `FEE_ESCROW_LOCKED` | Requestor | `{}` |
| `POST` | `/jobs/{id}/deliverable` | `DELIVERABLE_SUBMITTED` | Agent | `{"deliverable_ref": "..."}` |
| `POST` | `/jobs/{id}/evaluate` | `OUTCOME_EVALUATED` | Evaluator | `{"verdict": "pass" or "fail"}` |
| `POST` | `/jobs/{id}/fee/settle` | `FEE_SETTLED` | Any | `{"action": "release" or "refund"}` |

Settlement rules: `pass` verdict requires `release` action; `fail` verdict requires `refund`.

### Principal Track Endpoints (fund-moving jobs)

| Method | Path | Event Type | Actor | Required Payload |
|--------|------|-----------|-------|------------------|
| `POST` | `/jobs/{id}/uw/request` | `UW_REQUESTED` | Agent | `{}` |
| `POST` | `/jobs/{id}/uw/decide` | `UW_DECIDED` | Underwriter | `{"approve": true/false, "premium": 0, "collateral_required": 0}` |
| `POST` | `/jobs/{id}/uw/premium` | `PREMIUM_PAID` | Requestor | `{"premium_ref": "..."}` |
| `POST` | `/jobs/{id}/uw/collateral/lock` | `COLLATERAL_LOCKED` | Requestor | `{}` |
| `POST` | `/jobs/{id}/uw/collateral/refuse` | `COLLATERAL_REFUSED` | Requestor | `{}` |
| `POST` | `/jobs/{id}/uw/override` | `OVERRIDE_DECIDED` | Human Authority | `{"decision": "proceed"}` |
| `POST` | `/jobs/{id}/release/approve` | `RELEASE_APPROVED` | Requestor | `{}` |
| `POST` | `/jobs/{id}/principal/release` | `PRINCIPAL_RELEASED` | Settlement Layer | `{}` |
| `POST` | `/jobs/{id}/execution-evidence` | `EXECUTION_EVIDENCE_SUBMITTED` | Agent | `{"exec_evidence_ref": "..."}` |

### Query Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/jobs/{id}` | Get current job state (derived from event log) |
| `GET` | `/jobs/{id}/events` | Get full event history |

### Example: Complete Fee-Track Job (Python)

```python
import json
import hashlib
from datetime import datetime, timezone
import httpx
from nacl.signing import SigningKey

BASE = "http://localhost:8000"

def canonicalize(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def sign(sk, body):
    return sk.sign(canonicalize(body)).signature.hex()

def now():
    return datetime.now(timezone.utc).isoformat()

# 1. Generate keys for all participants
requestor_sk = SigningKey.generate()
agent_sk = SigningKey.generate()
evaluator_sk = SigningKey.generate()

req_pk = requestor_sk.verify_key.encode().hex()
agent_pk = agent_sk.verify_key.encode().hex()
eval_pk = evaluator_sk.verify_key.encode().hex()

# 2. Requestor creates job
agreement = {
    "version": "ars/0.1",
    "job_type": "code_review",
    "description": "Review PR #42",
    "requestor_pubkey": req_pk,
    "business_agent_pubkey": agent_pk,
    "evaluator_pubkey": eval_pk,
    "fee": {"amount": 500, "currency": "USD"},
}

body = {"type": "JOB_CREATED", "payload": {"agreement": agreement},
        "actor": req_pk, "timestamp": now()}
body["signature"] = sign(requestor_sk, body)
resp = httpx.post(f"{BASE}/jobs", json=body)
job_id = resp.json()["job_id"]
agr_hash = resp.json()["agreement_hash"]

# 3. Both parties sign
for sk in [requestor_sk, agent_sk]:
    pk = sk.verify_key.encode().hex()
    body = {"type": "AGREEMENT_SIGNED", "job_id": job_id,
            "agreement_hash": agr_hash, "payload": {},
            "actor": pk, "timestamp": now()}
    body["signature"] = sign(sk, body)
    httpx.post(f"{BASE}/jobs/{job_id}/signatures", json=body)

# 4. Requestor locks fee
body = {"type": "FEE_ESCROW_LOCKED", "job_id": job_id,
        "agreement_hash": agr_hash, "payload": {},
        "actor": req_pk, "timestamp": now()}
body["signature"] = sign(requestor_sk, body)
httpx.post(f"{BASE}/jobs/{job_id}/fee/lock", json=body)

# 5. Agent submits deliverable
body = {"type": "DELIVERABLE_SUBMITTED", "job_id": job_id,
        "agreement_hash": agr_hash,
        "payload": {"deliverable_ref": "ipfs://Qm..."},
        "actor": agent_pk, "timestamp": now()}
body["signature"] = sign(agent_sk, body)
httpx.post(f"{BASE}/jobs/{job_id}/deliverable", json=body)

# 6. Evaluator evaluates
body = {"type": "OUTCOME_EVALUATED", "job_id": job_id,
        "agreement_hash": agr_hash,
        "payload": {"verdict": "pass", "reason": "All checks passed"},
        "actor": eval_pk, "timestamp": now()}
body["signature"] = sign(evaluator_sk, body)
httpx.post(f"{BASE}/jobs/{job_id}/evaluate", json=body)

# 7. Settle — release fee to agent
body = {"type": "FEE_SETTLED", "job_id": job_id,
        "agreement_hash": agr_hash,
        "payload": {"action": "release"},
        "actor": req_pk, "timestamp": now()}
body["signature"] = sign(requestor_sk, body)
httpx.post(f"{BASE}/jobs/{job_id}/fee/settle", json=body)

# Check final state
state = httpx.get(f"{BASE}/jobs/{job_id}").json()
print(state["phase"])           # "CLOSED"
print(state["fee_track_state"]) # "FEE_SETTLED_RELEASE"
```

## Architecture

```
ars/
  models.py    # Pydantic models, enums (JobPhase, EventType, etc.)
  crypto.py    # Ed25519 signing, RFC 8785 canonicalization, SHA-256 hashing
  server.py    # FastAPI app with all endpoints
  state.py     # Event-sourced state derivation + transition validation
  store.py     # SQLite append-only event store
  vault.py     # Mock escrow, collateral, and principal vaults
```

**Event sourcing**: The server stores every signed action as an immutable event. Job state is never stored directly — it is always derived by replaying all events for a job through `derive_job_state()`. This makes the system auditable and tamper-evident.

**State machine**: `validate_transition()` enforces that each action is only allowed in the correct phase/state and by the correct role. Invalid transitions return `409 Conflict`; unauthorized actors get `403 Forbidden`.

**Mock vaults**: The current implementation uses in-memory mock vaults (`MockEscrowVault`, `MockCollateralVault`, `MockPrincipalVault`). In production, these would be replaced with integrations to real payment rails, custodial services, or on-chain contracts.

## Error Codes

| Code | Meaning |
|------|---------|
| `400` | Bad request (missing fields, type mismatch) |
| `401` | Signature verification failed |
| `403` | Actor not authorized for this action |
| `404` | Job not found |
| `409` | Invalid state transition (wrong phase, duplicate action, etc.) |

## License

Apache 2.0 — see [LICENSE](LICENSE).
