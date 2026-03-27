# Agentic Risk Standard

A settlement-layer protocol for trustworthy AI agent services. ARS provides cryptographically signed, event-sourced job lifecycle management with fee escrow, underwriting, and principal release tracks.

**ARS is designed as an abstract protocol with pluggable concrete implementations.** The `ars/` package defines the protocol primitives — models, state machine, event store, and cryptographic signing. Concrete implementations inherit from these primitives and supply real settlement rails, payment protocols, and role models.

This repo ships with one concrete implementation: **`ap2_ars/`**, which realizes ARS using Google's AP2 (Agent Payments Protocol) with x402 on-chain USDC settlement and an escrow smart contract.

## Abstract vs. Concrete

```
ars/          Abstract protocol layer (models, state machine, crypto, event store)
  |              - Generic event types, agreement structure, role-based validation
  |              - Mock vaults for development/testing
  |              - Pluggable: any concrete implementation can inherit from it
  |
ap2_ars/      Concrete AP2 realization (inherits from ars/)
                 - AP2 mandates (IntentMandate, CartMandate, PaymentMandate)
                 - 6-actor model with cryptographic agent-payment firewall
                 - x402 payment rail (Coinbase SDK, on-chain USDC via EIP-3009)
                 - ARSEscrow.sol smart contract (hold/release/refund/slash)
                 - Dual modality: human-present and human-NOT-present flows
```

`ap2_ars/` extends `ars/` through proper inheritance:
- Uses `ars.models.SignedActionEnvelope` and `ars.models.Event` directly (no reimplementation)
- `AP2JobStateView` inherits from `ars.models.JobStateView`, adding mandate track fields
- `AP2EventType` is dynamically composed from base `EventType` + AP2-specific events (no duplication)
- Uses `ars.store.EventStore` directly for event persistence
- Calls `ars.state.derive_job_state()` and `ars.state.validate_transition()` for base fee/principal tracks
- Mandate track provides structured user intent verification (authorization layer) that feeds into the base fee/principal tracks for actual settlement

## Overview

When a human (or organization) delegates a task to an AI agent, both sides need guarantees: the requestor needs assurance the agent will deliver, and the agent needs assurance it will be paid. ARS solves this by introducing a structured protocol where:

- Every action is an **Ed25519-signed event** appended to an immutable log
- Fees are held in **escrow** until an independent evaluator confirms delivery
- For high-value fund-moving jobs, an **underwriting track** gates principal release behind risk assessment, collateral, and multi-party approval
- All state is **derived by replaying the event log** — there is no mutable state to corrupt

---

## ars/ — Abstract Protocol

### Roles

ARS defines six participant roles. Each role is identified by an Ed25519 public key and can only perform specific actions:

| Role | Description |
|------|-------------|
| **Requestor** | Creates jobs, locks fee escrow, pays premiums, approves principal release, submits override decisions |
| **Business Agent** | Signs agreements, submits deliverables, requests underwriting, submits execution evidence |
| **Evaluator** | Independently evaluates deliverable quality (pass/fail verdict) |
| **Underwriter** | Assesses risk for fund-moving jobs; approves/rejects with premium and collateral terms |
| **Settlement Layer** | Executes principal fund transfers after all approvals are in place |

### Job Lifecycle

#### Fee Track (all jobs)

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

#### Principal Track (fund-moving jobs)

Jobs with `job_type: "fund-moving"` or a `principal` field activate a second track that runs in parallel with the fee track:

```
UW_AWAIT_REQUEST ──> UW_REVIEW ──> [PREMIUM_PENDING] ──> [COLLATERAL_REQUESTED]
       │                  │               │                        │
   Agent requests    Underwriter      Requestor pays         Requestor locks
   underwriting      decides          premium (if any)       collateral (if any)
                         │
                    If rejected ──> OVERRIDE_PENDING ──> Requestor decides override
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

### Quickstart

```bash
# Install
pip install -e ".[dev]"

# Run the abstract ARS server (mock vaults)
uvicorn ars.server:app --host 0.0.0.0 --port 8000

# Run base tests
pytest tests/test_e2e.py -v
```

### Architecture

```
ars/
  models.py    # Pydantic models, enums (JobPhase, EventType, etc.)
  crypto.py    # Ed25519 signing, RFC 8785 canonicalization, SHA-256 hashing
  server.py    # FastAPI app with all endpoints
  state.py     # Event-sourced state derivation + transition validation
  store.py     # SQLite append-only event store
  vault.py     # Mock escrow, collateral, and principal vaults
  errors.py    # HTTP error hierarchy
```

**Event sourcing**: The server stores every signed action as an immutable event. Job state is never stored directly — it is always derived by replaying all events for a job through `derive_job_state()`. This makes the system auditable and tamper-evident.

**State machine**: `validate_transition()` enforces that each action is only allowed in the correct phase/state and by the correct role. Invalid transitions return `409 Conflict`; unauthorized actors get `403 Forbidden`.

**Mock vaults**: The abstract implementation uses in-memory mock vaults (`MockEscrowVault`, `MockCollateralVault`, `MockPrincipalVault`). Concrete implementations replace these with real settlement — see `ap2_ars/` below.

---

## ap2_ars/ — Concrete AP2 Implementation

`ap2_ars/` is a concrete realization of ARS using Google's Agent Payments Protocol (AP2). It inherits the abstract `ars/` primitives and adds three layers:

### 1. AP2 Mandates (Authorization Layer)

Three signed credential types that provide cryptographic proof of user intent. The mandate flow is the **authorization layer** — it verifies what to buy and from whom. After mandate completion (`PAYMENT_SIGNED`), actual money movement flows through the base ARS fee/principal tracks for settlement safety.

| Mandate | Signer | Purpose |
|---------|--------|---------|
| **IntentMandate** | User | Pre-authorizes purchases: budget, merchant whitelist, SKU constraints, TTL, `requires_principal` flag |
| **CartMandate** | Merchant | Price/items guarantee with short TTL (5-15 min), prevents bait-and-switch |
| **PaymentMandate** | User / Credentials Provider | Final payment authorization referencing the CartMandate hash |

The `requires_principal` field on `IntentMandate` determines which settlement track is used after mandate completion:
- `requires_principal=False`: Fee track only (escrow purchase amount → deliver → evaluate → release/refund)
- `requires_principal=True`: Fee track + principal track (adds UW review, premium, collateral)

### 2. Six-Actor Model with Firewall

AP2 extends the base ARS roles to six mandatory actors. The key insight: the **shopping agent is the user's proxy** (it never receives payment), while the **merchant is the counterparty** who signs agreements, delivers goods, and receives payment:

| AP2 Role | Base ARS Equivalent | Purpose |
|----------|-------------------|---------|
| **User** | Requestor | Signs mandates, locks fee escrow, ultimate payment authority |
| **Shopping Agent** | *(user's proxy)* | Negotiates with merchants on behalf of user, **never sees payment data or receives payment** |
| **Evaluator** | Evaluator | Independent quality verdict |
| **Credentials Provider** | *(new)* | Secure wallet holding PCI/PII data, executes PaymentMandate |
| **Merchant** | Business Agent | Builds cart, signs CartMandate, signs agreements, delivers goods, receives payment |
| **Payment Processor** | Settlement Layer | Routes transactions, triggers 3DS |

The **agent-payment firewall** is enforced cryptographically at job creation: the Shopping Agent's key must differ from the Credentials Provider's and Payment Processor's keys. The agent orchestrates the flow but cannot access payment credentials.

### 3. Settlement Stack: x402 + ARSEscrow

x402 and ARSEscrow work together as the **internal transport** for the fee and principal tracks. There is no separate mandate settlement path — mandates authorize, tracks settle.

```
Fee/Principal Tracks ──> x402 (payment rail) ──> ARSEscrow.sol (hold/release/refund/slash)
                           │                          │
                           EIP-3009 gasless USDC      On-chain escrow contract
                           via Coinbase facilitator    per-job deposit tracking
```

**x402** handles moving USDC between wallets — it's a one-shot payment protocol using EIP-3009 `transferWithAuthorization`. The user signs an authorization offline, and the Coinbase facilitator submits it on-chain.

**ARSEscrow.sol** handles the business logic x402 can't do alone — holding funds, conditional release, refund, and collateral slashing. x402 transfers USDC *into* the escrow contract; the contract's functions determine where it goes *out*:

| Contract Function | What it does |
|---|---|
| `recordDeposit(jobId, type, payer, payee, amount)` | Tags a deposit after x402 transfer |
| `release(jobId, type)` | Sends USDC to payee (merchant) |
| `refund(jobId, type)` | Returns USDC to payer (user) |
| `slash(jobId, treasury)` | Seizes collateral to protocol treasury |

### Dual Modality

Both modalities follow the same pattern: mandate authorizes, then fee/principal tracks settle.

**Human-Present**: User sees the cart and explicitly approves before payment.

```
User → Agent → Merchant negotiation → CartMandate signed
  → User approves cart → PaymentMandate → User signs payment
  → Fee lock (escrow cart total, payee = merchant)
  → Merchant delivers → Evaluator verdicts → Fee release/refund
```

**Human-NOT-Present** (autonomous): User pre-signs an IntentMandate with constraints. The agent shops within those boundaries without human intervention.

```
User pre-signs IntentMandate (budget, merchants, SKUs, TTL, requires_principal)
  → Agent shops → Merchant signs CartMandate
  → Constraint engine auto-validates (budget, whitelist, SKU patterns)
  → Credentials Provider creates + signs PaymentMandate
  → Fee lock (escrow cart total, payee = merchant)
  → [If requires_principal: UW review → premium/collateral]
  → Merchant delivers → Evaluator verdicts → Fee release/refund
```

### AP2-Specific Endpoints

In addition to all base ARS endpoints, `ap2_ars/` adds mandate endpoints. After mandate completion, the base ARS fee/principal endpoints handle settlement:

| Method | Path | Event Type | Actor |
|--------|------|-----------|-------|
| `POST` | `/jobs/{id}/mandates/intent` | `INTENT_MANDATE_CREATED` | User |
| `POST` | `/jobs/{id}/mandates/cart` | `CART_MANDATE_PROPOSED` | Merchant |
| `POST` | `/jobs/{id}/mandates/cart/sign` | `CART_MANDATE_SIGNED` | Merchant |
| `POST` | `/jobs/{id}/mandates/cart/approve` | `CART_APPROVED_BY_USER` | User (human-present only) |
| `POST` | `/jobs/{id}/mandates/payment` | `PAYMENT_MANDATE_CREATED` | Credentials Provider |
| `POST` | `/jobs/{id}/mandates/payment/sign` | `PAYMENT_MANDATE_SIGNED` | User / Credentials Provider |
| `GET` | `/jobs/{id}/mandates` | — | Any |
| `GET` | `/jobs/{id}/constraints/check` | — | Any |

### Quickstart

```bash
# Install with AP2 extras (x402 SDK + web3)
pip install -e ".[dev,ap2]"

# Run the AP2 server (mock settlement for development)
uvicorn ap2_ars.server:app --host 0.0.0.0 --port 8000

# Run AP2 tests
pytest tests/test_ap2/ -v

# Run ALL tests (base + AP2)
pytest tests/ -v
```

For real on-chain settlement, pass a configured `SettlementLayer`:

```python
from ap2_ars.server import create_app
from ap2_ars.x402 import LiveX402Settlement
from ap2_ars.escrow import LiveEscrowClient
from ap2_ars.settlement import LiveSettlementLayer

x402 = LiveX402Settlement(
    facilitator_url="https://api.developer.coinbase.com/x402/facilitator",
    pay_to="<escrow-contract-address>",
    network="eip155:8453",  # Base Mainnet
)
escrow = LiveEscrowClient(
    rpc_url="https://mainnet.base.org",
    contract_address="<deployed-ARSEscrow-address>",
    abi=...,  # load from ap2_ars/contracts/ars_escrow_abi.json
    operator_key="<operator-private-key>",
)
settlement = LiveSettlementLayer(x402=x402, escrow=escrow)
app = create_app(settlement=settlement)
```

### Architecture

```
ap2_ars/
  models.py        # AP2AgreementDraft, VDC types, AP2EventType (derived from base), AP2JobStateView
  vdc.py           # VDC creation, Ed25519 signing/verification, TTL enforcement
  roles.py         # 6-actor RoleRegistry + cryptographic firewall
  constraints.py   # IntentMandate constraint engine (budget, merchant, SKU, TTL)
  x402.py          # x402 payment rail (internal transport) — LiveX402Settlement + Mock
  escrow.py        # Python interface to ARSEscrow contract — LiveEscrowClient + Mock
  settlement.py    # Unified SettlementLayer composing x402 + escrow for fee/principal tracks
  state.py         # Composite state machine: mandate authorization + base fee/principal tracks
  server.py        # FastAPI app — base ARS endpoints + AP2 mandate endpoints
  contracts/
    ARSEscrow.sol       # Solidity escrow contract (USDC hold/release/refund/slash)
    ars_escrow_abi.json  # Pre-compiled contract ABI
```

---

## Building Your Own Concrete Implementation

To build a new realization of ARS (e.g., using a different payment rail or blockchain):

1. **Import from `ars/`**: Use `SignedActionEnvelope`, `Event`, `EventStore`, `JobStateView`, `derive_job_state()`, `validate_transition()` directly
2. **Define your agreement model**: Map your domain's actors to ARS roles via a bridging function (see `ap2_ars/state.py:_to_base_agreement()`)
3. **Extend `JobStateView`**: Add fields for your protocol-specific state
4. **Implement `SettlementLayer`**: Wire your payment rail (the ABC is in `ap2_ars/settlement.py`)
5. **Add new event types**: String-typed events pass through the base store/state unchanged; add your own state machine for domain-specific transitions

---

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

## Base ARS API Reference

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
| `POST` | `/jobs/{id}/proposals` | `PROPOSAL_SUBMITTED` | Requestor or Business Agent | `{"agreement": {...}}` |
| `POST` | `/jobs/{id}/signatures` | `AGREEMENT_SIGNED` | Requestor or Business Agent | `{}` |
| `POST` | `/jobs/{id}/fee/lock` | `FEE_ESCROW_LOCKED` | Requestor | `{}` |
| `POST` | `/jobs/{id}/deliverable` | `DELIVERABLE_SUBMITTED` | Business Agent | `{"deliverable_ref": "..."}` |
| `POST` | `/jobs/{id}/evaluate` | `OUTCOME_EVALUATED` | Evaluator | `{"verdict": "pass" or "fail"}` |
| `POST` | `/jobs/{id}/fee/settle` | `FEE_SETTLED` | Any | `{"action": "release" or "refund"}` |

In `ap2_ars/`, the fee lock uses the **cart total** from the completed mandate as the escrow amount, with the **merchant** as payee. The fee lock and UW request are gated on mandate completion (`PAYMENT_SIGNED`).

Settlement rules: `pass` verdict requires `release` action; `fail` verdict requires `refund`.

### Principal Track Endpoints (fund-moving jobs)

| Method | Path | Event Type | Actor | Required Payload |
|--------|------|-----------|-------|------------------|
| `POST` | `/jobs/{id}/uw/request` | `UW_REQUESTED` | Business Agent | `{}` |
| `POST` | `/jobs/{id}/uw/decide` | `UW_DECIDED` | Underwriter | `{"approve": true/false, "premium": 0, "collateral_required": 0}` |
| `POST` | `/jobs/{id}/uw/premium` | `PREMIUM_PAID` | Requestor | `{"premium_ref": "..."}` |
| `POST` | `/jobs/{id}/uw/collateral/lock` | `COLLATERAL_LOCKED` | Requestor | `{}` |
| `POST` | `/jobs/{id}/uw/collateral/refuse` | `COLLATERAL_REFUSED` | Requestor | `{}` |
| `POST` | `/jobs/{id}/uw/override` | `OVERRIDE_DECIDED` | Requestor | `{"decision": "proceed"}` |
| `POST` | `/jobs/{id}/release/approve` | `RELEASE_APPROVED` | Requestor | `{}` |
| `POST` | `/jobs/{id}/principal/release` | `PRINCIPAL_RELEASED` | Settlement Layer | `{}` |
| `POST` | `/jobs/{id}/execution-evidence` | `EXECUTION_EVIDENCE_SUBMITTED` | Business Agent | `{"exec_evidence_ref": "..."}` |

### Query Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/jobs/{id}` | Get current job state (derived from event log) |
| `GET` | `/jobs/{id}/events` | Get full event history |

## Error Codes

| Code | Meaning |
|------|---------|
| `400` | Bad request (missing fields, type mismatch, firewall violation) |
| `401` | Signature verification failed |
| `403` | Actor not authorized for this action |
| `404` | Job not found |
| `409` | Invalid state transition (wrong phase, duplicate action, wrong modality) |

## License

Apache 2.0 — see [LICENSE](LICENSE).
