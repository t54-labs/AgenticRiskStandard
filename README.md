# Agentic Risk Standard

A settlement-layer protocol for trustworthy AI agent services. ARS provides cryptographically signed, event-sourced job lifecycle management with fee escrow, underwriting, and principal release tracks.

**ARS is designed as an abstract protocol with pluggable concrete implementations.** The `ars/` package defines the protocol primitives — models, state machine, event store, and cryptographic signing. Concrete implementations inherit from these primitives and supply real settlement rails, payment protocols, and role models.

This repo ships with two concrete implementations:
- **`ap2/server/`** — realizes ARS using Google's AP2 (Agent Payments Protocol) with x402 on-chain USDC settlement and an escrow smart contract
- **`vi/server/`** — realizes ARS using Mastercard's Verifiable Intent (VI) specification with ES256/SD-JWT credential chains and selective disclosure

## Abstract vs. Concrete

```
src/
  ars/              Abstract protocol layer (models, state machine, crypto, event store)
  ars_client/       Abstract client SDK (RequestorClient, BusinessAgentClient, ...)
  ap2/
    server/         Concrete AP2 server (mandates, roles, x402, escrow)
    client/         Concrete AP2 client SDK (UserClient, MerchantClient, ...)
  vi/
    server/         Concrete VI server (SD-JWT credentials, roles, selective disclosure)
    client/         Concrete VI client SDK (VIUserClient, VIAgentClient, ...)
```

`ap2/server/` extends `ars/` through proper inheritance:
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
- For high-value fund-moving jobs, an **underwriting track** gates principal release behind risk assessment, collateral, and optional override
- All state is **derived by replaying the event log** — there is no mutable state to corrupt

---

## ars/ — Abstract Protocol

### Roles

ARS defines six participant roles. Each role is identified by an Ed25519 public key and can only perform specific actions:

| Role | Description |
|------|-------------|
| **Requestor** | Creates jobs, locks fee escrow, pays premiums, submits override decisions |
| **Business Agent** | Signs agreements, submits deliverables, requests underwriting, locks collateral, submits execution evidence |
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
   Agent requests    Underwriter      Requestor pays         Business agent locks
   underwriting      decides          premium (if any)       collateral (if any)
                         │
                    Happy path: premium paid + collateral locked ──> RELEASABLE (auto)
                                                                          │
                    If rejected/refused ──> OVERRIDE_PENDING ──> Requestor overrides
                                                                          │
                                                                      RELEASABLE (auto) ──> EXECUTION_PENDING
                                                                          │                        │
                                                                     Settlement              Agent submits
                                                                       layer                  execution
                                                                      releases                evidence
                                                                      principal
```

### Quickstart

```bash
# Install
pip install -e ".[dev]"

# Run the abstract ARS server (mock vaults)
uvicorn ars.server:app --host 0.0.0.0 --port 8000

# Run base tests
pytest tests/test_abstract_ars/ -v
```

### Architecture

```
src/abstract_ars/
  models.py      # Pydantic models, enums (JobPhase, EventType, etc.)
  crypto.py      # Ed25519 signing, RFC 8785 canonicalization, SHA-256 hashing
  routes.py      # Shared APIRouter factory (14 endpoints reused by ap2/)
  server.py      # FastAPI app with override endpoints
  state.py       # Event-sourced state derivation + transition validation
  store.py       # SQLite append-only event store
  vaults.py      # FeeEscrow + CollateralVault ABCs + mocks
  settlement.py  # Settlement layer ABC + MockSettlementLayer
  errors.py      # HTTP error hierarchy
```

**Event sourcing**: The server stores every signed action as an immutable event. Job state is never stored directly — it is always derived by replaying all events for a job through `derive_job_state()`. This makes the system auditable and tamper-evident.

**State machine**: `validate_transition()` enforces that each action is only allowed in the correct phase/state and by the correct role. Invalid transitions return `409 Conflict`; unauthorized actors get `403 Forbidden`.

**Mock vaults**: The abstract implementation uses in-memory mock vaults (`MockEscrowVault`, `MockCollateralVault`, `MockPrincipalVault`). Concrete implementations replace these with real settlement — see `ap2/server/` below.

---

## ap2/server/ — Concrete AP2 Implementation

`ap2/server/` is a concrete realization of ARS using Google's Agent Payments Protocol (AP2). It inherits the abstract `ars/` primitives and adds three layers:

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

In addition to all base ARS endpoints, `ap2/server/` adds mandate endpoints. After mandate completion, the base ARS fee/principal endpoints handle settlement:

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
uvicorn ap2.server.server:app --host 0.0.0.0 --port 8000

# Run AP2 tests
pytest tests/test_ap2/ -v

# Run ALL tests (base + AP2)
pytest tests/ -v
```

For real on-chain settlement, pass a configured `SettlementLayer`:

```python
from ap2.server.server import create_app
from ap2.server.x402 import LiveX402Settlement
from ap2.server.vaults import LiveFeeEscrow, LiveCollateralVault
from ap2.server.settlement import LiveSettlementLayer

x402 = LiveX402Settlement(
    facilitator_url="https://api.developer.coinbase.com/x402/facilitator",
    pay_to="<escrow-contract-address>",
    network="eip155:8453",  # Base Mainnet
)
contract_args = dict(
    rpc_url="https://mainnet.base.org",
    contract_address="<deployed-ARSEscrow-address>",
    abi=...,  # load from ap2/server/contracts/ars_escrow_abi.json
    operator_key="<operator-private-key>",
)
fee_escrow = LiveFeeEscrow(**contract_args)
collateral_vault = LiveCollateralVault(**contract_args)
settlement = LiveSettlementLayer(
    x402=x402, fee_escrow=fee_escrow, collateral_vault=collateral_vault,
)
app = create_app(settlement=settlement)
```

### Architecture

```
src/ap2/
  server/
    models.py        # AP2AgreementDraft, VDC types, AP2EventType, AP2JobStateView
    vdc.py           # VDC creation, Ed25519 signing/verification, TTL enforcement
    roles.py         # 6-actor RoleRegistry + cryptographic firewall
    constraints.py   # IntentMandate constraint engine (budget, merchant, SKU, TTL)
    x402.py          # x402 payment rail (internal transport)
    vaults.py        # LiveFeeEscrow + LiveCollateralVault (web3.py, extend abstract_ars ABCs)
    settlement.py    # LiveSettlementLayer (x402 + vaults)
    state.py         # Composite state machine: mandate authorization + base tracks
    server.py        # FastAPI app: shared router + override + mandate endpoints
  client/
    user.py          # UserClient (extends RequestorClient with mandate methods)
    merchant.py      # MerchantClient (extends BusinessAgentClient with cart methods)
    shopping_agent.py # ShoppingAgentClient (read-only orchestrator)
    cli.py           # AP2 CLI extending base CLI
```

---

## vi/server/ — Concrete VI Implementation

`vi/server/` is a concrete realization of ARS using Mastercard's Verifiable Intent (VI) specification. It inherits the abstract `ars/` primitives and adds three layers:

### 1. SD-JWT Credential Chain (Authorization Layer)

A three-layer credential chain using ES256-signed Selective Disclosure JWTs. The credential flow is the **authorization layer** — it establishes a cryptographically verifiable chain from issuer identity through user mandate to agent fulfillment. After credential verification, actual money movement flows through the base ARS fee/principal tracks.

| Layer | Signer | Purpose |
|-------|--------|---------|
| **L1 Issuer Credential** | Credential Provider | Identity assertion: binds user's ES256 key, ~1 year TTL |
| **L2 User Mandate** | User | Authorization: immediate (final values) or autonomous (constraints + agent delegation) |
| **L3a Payment Fulfillment** | Agent | Agent's final payment values (autonomous only, 5 min TTL) |
| **L3b Checkout Fulfillment** | Agent | Agent's final checkout values (autonomous only, 5 min TTL) |

**Selective disclosure** is the key addition over AP2: the merchant receives only checkout data (L3b), and the payment network receives only payment data (L3a). Neither party sees the other's information.

### 2. Seven-Actor Model with Firewall

VI extends the base ARS roles to seven actors. The **agent is the user's proxy** (never receives payment), and the **merchant is the counterparty** (same mapping as AP2):

| VI Role | Base ARS Equivalent | Purpose |
|---------|-------------------|---------|
| **User** | Requestor | Creates L2 mandates, locks fee escrow, holds Ed25519 + ES256 keys |
| **Agent** | *(user's proxy)* | Creates L3 fulfillment credentials, **never sees payment data** |
| **Evaluator** | Evaluator | Independent quality verdict |
| **Credential Provider** | *(new)* | Issues L1 identity credentials, verifies chains |
| **Merchant** | Business Agent | Delivers goods, receives payment, gets checkout-only presentation |
| **Payment Network** | Settlement Layer | Verifies chains, settles, gets payment-only presentation |
| **Underwriter** | Underwriter | Risk assessment for fund-moving jobs (optional) |

### 3. Dual Modality

**Immediate** (2-layer): User specifies exact purchase in L2. No L3 needed. Fee lock gate opens at `L2_VERIFIED`.

```
CredProvider: L1 → User: L2 (final values) → verify L2
  → Fee lock → Merchant delivers → Evaluator verdicts → Settle
```

**Autonomous** (3-layer): User sets constraints in L2, agent fulfills in L3a/L3b.

```
CredProvider: L1 → User: L2 (constraints, delegate to agent)
  → verify L2 → Agent: L3a + L3b → verify chain (+ constraint check)
  → Fee lock → Merchant delivers → Evaluator verdicts → Settle
```

### VI-Specific Endpoints

In addition to all base ARS endpoints, `vi/server/` adds credential endpoints:

| Method | Path | Event Type | Actor |
|--------|------|-----------|-------|
| `POST` | `/jobs/{id}/credentials/l1` | `L1_CREDENTIAL_ISSUED` | Credential Provider |
| `POST` | `/jobs/{id}/credentials/l2` | `L2_MANDATE_CREATED` | User |
| `POST` | `/jobs/{id}/credentials/l2/verify` | `L2_MANDATE_VERIFIED` | Credential Provider / Payment Network |
| `POST` | `/jobs/{id}/credentials/l3a` | `L3A_PAYMENT_CREATED` | Agent (autonomous only) |
| `POST` | `/jobs/{id}/credentials/l3b` | `L3B_CHECKOUT_CREATED` | Agent (autonomous only) |
| `POST` | `/jobs/{id}/credentials/l3/verify` | `L3_CHAIN_VERIFIED` | Credential Provider / Payment Network |
| `POST` | `/jobs/{id}/credentials/settlement/initiate` | `SETTLEMENT_VI_INITIATED` | Payment Network |
| `POST` | `/jobs/{id}/credentials/settlement/confirm` | `SETTLEMENT_VI_CONFIRMED` | Payment Network |
| `GET` | `/jobs/{id}/credentials` | — | Any |
| `GET` | `/jobs/{id}/credentials/present/merchant` | — | Any (checkout data only) |
| `GET` | `/jobs/{id}/credentials/present/network` | — | Any (payment data only) |
| `GET` | `/jobs/{id}/constraints/check` | — | Any |

### Quickstart

```bash
# Install with VI extras (cryptography for ES256)
pip install -e ".[dev,vi]"

# Run the VI server (mock settlement for development)
uvicorn vi.server.server:app --host 0.0.0.0 --port 8000

# Run VI tests
pytest tests/test_vi/ -v

# Run ALL tests (base + AP2 + VI)
pytest tests/ -v
```

### Architecture

```
src/vi/
  server/
    models.py        # VIAgreementDraft, credential track types, VIEventType, VIJobStateView
    crypto.py        # ES256 key management, SD-JWT creation/verification, JWK conversion
    credentials.py   # L1/L2/L3 creation, chain verification, sd_hash binding
    roles.py         # 7-actor VIRoleRegistry + cryptographic firewall
    constraints.py   # VI constraint engine (amount, merchant, payee, line items, budget)
    state.py         # Composite state machine: credential authorization + base tracks
    server.py        # FastAPI app: shared router + override + credential endpoints
    settlement.py    # Re-exports SettlementLayer from abstract_ars.settlement
  client/
    user.py          # VIUserClient (extends RequestorClient with L2 methods)
    agent.py         # VIAgentClient (L3 creation, credential queries)
    merchant.py      # VIMerchantClient (extends BusinessAgentClient with presentation)
    credential_provider.py  # VICredentialProviderClient (L1 issuance, chain verification)
    payment_network.py      # VIPaymentNetworkClient (chain verification, settlement)
    cli.py           # VI CLI extending base CLI
```

---

## Building Your Own Concrete Implementation

To build a new realization of ARS (e.g., using a different payment rail or blockchain):

1. **Import from `ars/`**: Use `SignedActionEnvelope`, `Event`, `EventStore`, `JobStateView`, `derive_job_state()`, `validate_transition()` directly
2. **Define your agreement model**: Map your domain's actors to ARS roles via a bridging function (see `ap2/server/state.py:_to_base_agreement()`)
3. **Extend `JobStateView`**: Add fields for your protocol-specific state
4. **Implement `SettlementLayer`**: Wire your payment rail (the ABC is in `ap2/server/settlement.py`)
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

In `ap2/server/`, the fee lock uses the **cart total** from the completed mandate as the escrow amount, with the **merchant** as payee. The fee lock and UW request are gated on mandate completion (`PAYMENT_SIGNED`).

Settlement rules: `pass` verdict requires `release` action; `fail` verdict requires `refund`. When collateral is locked, fee settlement automatically handles it: `release` unlocks collateral (returned to business agent), `refund` slashes collateral (seized to treasury).

### Principal Track Endpoints (fund-moving jobs)

| Method | Path | Event Type | Actor | Required Payload |
|--------|------|-----------|-------|------------------|
| `POST` | `/jobs/{id}/uw/request` | `UW_REQUESTED` | Business Agent | `{}` |
| `POST` | `/jobs/{id}/uw/decide` | `UW_DECIDED` | Underwriter | `{"approve": true/false, "premium": 0, "collateral_required": 0}` |
| `POST` | `/jobs/{id}/uw/premium` | `PREMIUM_PAID` | Requestor | `{"premium_ref": "..."}` |
| `POST` | `/jobs/{id}/uw/premium/refuse` | `PREMIUM_REFUSED` | Requestor | `{}` |
| `POST` | `/jobs/{id}/uw/collateral/lock` | `COLLATERAL_LOCKED` | Business Agent | `{}` |
| `POST` | `/jobs/{id}/uw/collateral/refuse` | `COLLATERAL_REFUSED` | Business Agent | `{}` |
| `POST` | `/jobs/{id}/uw/override` | `OVERRIDE_DECIDED` | Requestor | `{"decision": "proceed"}` |
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
