# ARS Protocol Overview

The Agentic Risk Standard (ARS) is an event-sourced settlement protocol for trustworthy AI agent transactions. It addresses a fundamental trust problem: when a human delegates a task to an AI agent, both sides need guarantees. The human needs assurance the agent will deliver. The agent (or its operator) needs assurance it will be paid. And for high-value transactions, both sides need protection against fraud, non-delivery, and disputes.

ARS solves this by introducing a structured protocol where every action is a cryptographically signed event appended to an immutable log. There is no mutable state to corrupt. Job state is always derived by replaying the event log, making the system auditable and tamper-evident. Any party can independently verify the state of a job by replaying events and checking every signature.

## Two Settlement Tracks

ARS provides two parallel settlement tracks that can operate independently or together within a single job.

The **fee track** handles the primary transaction. A fee is locked in escrow at the start of work, an independent evaluator assesses delivery quality, and the fee is released to the counterparty on pass or refunded to the payer on fail. Every job uses the fee track.

The **principal track** adds underwriting protection for higher-value or higher-risk transactions. An underwriter assesses risk and may require a premium (insurance cost paid by the requestor) and collateral (locked by the business agent as a delivery guarantee). If the business agent fails to deliver, the collateral can be slashed to a treasury. The principal track is optional and activates only for fund-moving jobs.

## Roles

ARS defines five participant roles, each identified by an Ed25519 public key:

**Requestor** creates jobs, locks fee escrow, pays premiums, and can override underwriter decisions. Principal release is always automatic once conditions are met (coverage satisfied or override accepted).

**Business Agent** signs agreements, submits deliverables, requests underwriting, locks collateral, and submits execution evidence.

**Evaluator** independently evaluates deliverable quality and issues pass/fail verdicts.

**Underwriter** assesses risk for fund-moving jobs, sets premium and collateral terms, and approves or rejects.

**Settlement Layer** executes principal fund transfers after all approvals are in place. This is an infrastructure role operated server-side, not a human actor.

## Event Sourcing

Every action in the protocol produces a signed event. The server stores events in an append-only SQLite database. Job state is never written directly. Instead, the state derivation function replays all events for a job through a deterministic accumulator, producing the current phase, fee track state, principal track state, signatures, and all associated data.

This design has several advantages. The event log is a complete audit trail. State can be reconstructed at any point in time by replaying events up to that point. There is no risk of state corruption from partial writes or race conditions. And any party can verify the log independently by checking signatures and replaying events.

## Abstract Protocol

ARS is designed as an abstract protocol with pluggable concrete implementations. The `ars/` package defines the protocol primitives: data models, state machine, cryptographic signing, event store, and escrow/settlement abstractions. Concrete implementations inherit from these primitives and supply real settlement rails, payment protocols, and role models.

The first concrete implementation is AP2-ARS, which realizes ARS using Google's Agent Payments Protocol (AP2) with x402 on-chain USDC settlement and an escrow smart contract. See [AP2 Integration](../ap2-integration/overview.md) for details.

## Further Reading

- [Fee Track](fee-track.md) for the escrow lifecycle
- [Principal Track](principal-track.md) for underwriting and collateral
- [State Machine](state-machine.md) for phases and transition rules
- [Cryptography](cryptography.md) for signing and hashing details
