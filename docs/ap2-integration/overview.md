# AP2 Integration Overview

Google's Agent Payments Protocol (AP2) provides structured user intent verification for autonomous purchasing. ARS provides settlement safety through escrow, evaluation, and conditional release. We integrate AP2 as a concrete realization of ARS, where AP2 serves as the authorization layer and ARS provides the settlement guarantees.

## The Core Insight

The AP2 mandate flow and the ARS settlement tracks serve complementary purposes. The mandate establishes cryptographic proof of user intent: a budget ceiling, a merchant whitelist, and specific line items at agreed prices. The fee and principal tracks then ensure that the actual fund movement is protected by escrow, evaluated by an independent party, and conditionally released or refunded based on delivery quality.

Neither layer alone is sufficient. Without mandates, the settlement tracks have no structured way to verify that the agent is purchasing what the user intended. Without the settlement tracks, the mandates provide authorization but no mechanism to hold funds, evaluate outcomes, or resolve disputes.

## Architectural Inheritance

AP2-ARS inherits all ARS protocol primitives through clean composition:

`AP2JobStateView` inherits from `JobStateView`, adding mandate track fields. `AP2EventType` is dynamically composed from the base `EventType` plus AP2-specific mandate events, so adding a base event type automatically propagates to AP2 without manual synchronization.

The composite state machine bridges AP2 agreement fields to base ARS format (e.g., `merchant_pubkey` to `business_agent_pubkey`) and delegates base events to the ARS state machine while handling mandate events separately. Both results are merged into a unified job state view.

14 HTTP endpoints are shared between the base ARS server and the AP2 server through a parameterized router factory. Only 5 endpoints with settlement-specific logic (job creation, fee lock/settle, collateral lock, principal release) are defined separately. AP2 adds 8 mandate-specific endpoints.

## Key Design Decisions

**Mandate authorizes, tracks settle.** The mandate flow determines what to buy and from whom. The fee and principal tracks handle the actual money movement with escrow protection.

**Shopping agent is the user's proxy.** The agent negotiates on the user's behalf but never receives payment and never accesses payment credentials. The merchant is the counterparty who receives payment, mapping to the ARS Business Agent role.

**`requires_principal` gates the UW track.** Each IntentMandate specifies whether underwriting is needed. The server blocks UW requests when `requires_principal` is false, preventing unnecessary overhead for simple purchases.

## Further Reading

- [Role Mapping](role-mapping.md) for the 6-actor model and firewall
- [Mandates](mandates.md) for the VDC authorization chain
- [Transaction Flow](transaction-flow.md) for the complete end-to-end flow
- [Dual Modality](dual-modality.md) for human-present vs autonomous modes
