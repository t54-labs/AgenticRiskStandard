# Role Mapping

ARS defines abstract roles (Requestor, Business Agent, Evaluator, Underwriter, Settlement Layer). AP2 maps these to a six-actor model with distinct responsibilities and a cryptographic firewall.

## The Six Actors

**User** maps to ARS Requestor. The human who creates jobs, signs mandates, approves carts, locks fee escrow, pays premiums, and can override underwriter decisions. The user holds ultimate payment authority.

**Shopping Agent** has no direct ARS equivalent. It is the user's AI proxy that negotiates with merchants on the user's behalf. The shopping agent never receives payment and never accesses payment credentials. It orchestrates the purchasing flow but is cryptographically separated from the payment path.

**Merchant** maps to ARS Business Agent. This is the key mapping decision in the integration. The merchant is the counterparty: they sign agreements, propose and sign carts, deliver goods, and receive payment. In ARS terms, they are the "business agent" because they are the party being paid for performing work (delivering goods).

**Evaluator** maps directly to ARS Evaluator. An independent party that assesses delivery quality and issues pass/fail verdicts. The evaluator has no financial stake in the outcome.

**Credentials Provider** is a new role with no ARS equivalent. It is a secure wallet service (like Google Pay or a bank's tokenization API) that holds the user's payment credentials. It creates and signs PaymentMandates in human-not-present mode. The credentials provider is server-side infrastructure, not a client SDK participant.

**Payment Processor** maps to ARS Settlement Layer. It routes on-chain transactions via x402 and executes settlement operations. Like the credentials provider, it is server-side infrastructure.

## Agreement Bridging

When AP2 events enter the base ARS state machine, the agreement fields are bridged:

| AP2 Field | ARS Field |
|-----------|-----------|
| `user_pubkey` | `requestor_pubkey` |
| `merchant_pubkey` | `business_agent_pubkey` |
| `payment_processor_pubkey` | `settlement_layer_pubkey` |

Fields unique to AP2 (`shopping_agent_pubkey`, `credentials_provider_pubkey`, `modality`) are stripped during bridging since the base ARS state machine does not know about them.

## Agent-Payment Firewall

The firewall is enforced cryptographically at job creation: the Shopping Agent's Ed25519 public key must differ from both the Credentials Provider's key and the Payment Processor's key.

```python
if agent_pubkey == credentials_provider_pubkey:
    raise BadRequestError("Firewall violation: agent cannot be credentials provider")
if agent_pubkey == payment_processor_pubkey:
    raise BadRequestError("Firewall violation: agent cannot be payment processor")
```

This is not an application-level check that can be bypassed. Since every action requires an Ed25519 signature from the actor's key, and the firewall ensures the agent's key is different from the payment keys, the agent literally cannot sign payment operations. The separation is guaranteed by the cryptographic protocol.

## Why Merchant = Business Agent

In the original ARS design, the "business agent" is the party hired to do work. In AP2, the shopping agent does the work (finding and purchasing goods), but the shopping agent is the user's own proxy. The actual counterparty in the economic transaction is the merchant: they provide goods, take delivery risk, and receive payment. This makes the merchant the natural mapping for the ARS Business Agent role.

This mapping has concrete implications:

- The merchant signs the agreement (not the shopping agent).
- The merchant submits the deliverable (they deliver the goods).
- The merchant locks collateral (their delivery guarantee).
- The merchant receives the fee (the purchase price).
- The merchant requests underwriting (if principal track is needed).
