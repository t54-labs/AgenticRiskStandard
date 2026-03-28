# Role Mapping

ARS defines abstract roles (Requestor, Business Agent, Evaluator, Underwriter, Settlement Layer). VI maps these to a seven-actor model with distinct responsibilities and a cryptographic firewall.

## The Seven Actors

**User** maps to ARS Requestor. The human who creates jobs, creates L2 mandates, locks fee escrow, pays premiums, and can override underwriter decisions. The user holds both an Ed25519 key (for ARS events) and an ES256 key (for signing L2 credentials).

**Agent** has no direct ARS equivalent. It is the user's AI proxy that selects goods and creates L3 fulfillment credentials within the constraints set by the user's L2 mandate. The agent never receives payment and never accesses payment credentials. It is cryptographically separated from the payment path.

**Merchant** maps to ARS Business Agent. The counterparty who signs agreements, delivers goods, receives payment, and locks collateral. The merchant receives a selective presentation containing only checkout-related credential data.

**Evaluator** maps directly to ARS Evaluator. An independent party that assesses delivery quality and issues pass/fail verdicts.

**Credential Provider** is a new role with no base ARS equivalent. It issues L1 identity credentials (vouching for the user) and can verify credential chains. In VI, the credential provider replaces the concept of direct public key trust with an issuer-backed identity layer.

**Payment Network** maps to ARS Settlement Layer. It verifies credential chains, initiates and confirms VI settlement, and receives a selective presentation containing only payment-related credential data.

**Underwriter** maps to ARS Underwriter (optional, for fund-moving jobs).

## Agreement Bridging

When VI events enter the base ARS state machine, the agreement fields are bridged:

| VI Field | ARS Field |
|----------|-----------|
| `user_pubkey` | `requestor_pubkey` |
| `merchant_pubkey` | `business_agent_pubkey` |
| `payment_network_pubkey` | `settlement_layer_pubkey` |

Fields unique to VI (`agent_pubkey`, `credential_provider_pubkey`, `mode`, all `*_jwk` fields, `requires_principal`, `max_premium`, `allow_uw_override`) are stripped during bridging since the base ARS state machine does not know about them.

## Agent-Credential Firewall

The firewall is enforced cryptographically at job creation: the Agent's Ed25519 public key must differ from both the Credential Provider's key and the Payment Network's key.

```python
if agent_pubkey == credential_provider_pubkey:
    raise BadRequestError("Firewall violation: agent cannot be credential provider")
if agent_pubkey == payment_network_pubkey:
    raise BadRequestError("Firewall violation: agent cannot be payment network")
```

The firewall is only enforced when `agent_pubkey` is provided. If the user operates without a separate agent, the firewall check is skipped.

## Why Merchant = Business Agent

The same reasoning as AP2 applies. The merchant is the economic counterparty: they provide goods, take delivery risk, and receive payment. The agent is the user's own proxy. This mapping means the merchant signs agreements, submits deliverables, locks collateral, and receives the escrowed fee.

## Comparison with AP2 Roles

| VI Role | AP2 Equivalent | Key Difference |
|---------|---------------|----------------|
| User | User | Also holds ES256 key for L2 credentials |
| Agent | Shopping Agent | Creates L3 SD-JWT credentials (not just orchestrates) |
| Credential Provider | Credentials Provider | Issues L1 identity credentials (new capability) |
| Merchant | Merchant | Receives selective presentation (checkout only) |
| Payment Network | Payment Processor | Receives selective presentation (payment only) |
| Evaluator | Evaluator | Identical |
| Underwriter | Underwriter | Identical |
