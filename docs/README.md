# ARS Documentation

Start with the [protocol overview](ars-protocol/overview.md) for the abstract layer, then read the
concrete implementation that matches your payment stack.

## Abstract protocol

The layer every implementation inherits: models, state machine, event store, and signing.

- [Overview](ars-protocol/overview.md) — roles, two-track design, event sourcing
- [Fee Track](ars-protocol/fee-track.md) — escrow lifecycle, settlement rules, collateral resolution
- [Principal Track](ars-protocol/principal-track.md) — underwriting, premium, collateral, override
- [State Machine](ars-protocol/state-machine.md) — phases, transition validation, event types
- [Cryptography](ars-protocol/cryptography.md) — Ed25519 signing, RFC 8785 canonicalization, hashing

## AP2 integration

Concrete realization over Google's Agent Payments Protocol.

- [Overview](ap2-integration/overview.md)
- [Role Mapping](ap2-integration/role-mapping.md) — 6-actor model and the agent-payment firewall
- [Mandates](ap2-integration/mandates.md) — Intent, Cart, and Payment mandate chain
- [Transaction Flow](ap2-integration/transaction-flow.md) — end-to-end flow and enforcement gates
- [Dual Modality](ap2-integration/dual-modality.md) — human-present vs. human-not-present

## VI integration

Concrete realization over Mastercard's Verifiable Intent specification.

- [Overview](vi-integration/overview.md)
- [Role Mapping](vi-integration/role-mapping.md) — 7-actor model and the agent-credential firewall
- [Credentials](vi-integration/credentials.md) — L1/L2/L3 SD-JWT chain and selective disclosure
- [Transaction Flow](vi-integration/transaction-flow.md) — end-to-end flow and enforcement gates
- [Dual Modality](vi-integration/dual-modality.md) — immediate vs. autonomous

## Settlement rails

How value actually moves once a track authorizes it.

- [Overview](settlement-rails/overview.md)
- [Abstract Interface](settlement-rails/abstract-interface.md) — the `SettlementLayer` seam
- [x402](settlement-rails/x402.md) — EIP-3009 gasless USDC via the Coinbase facilitator
- [Escrow Contract](settlement-rails/escrow-contract.md) — `ARSEscrow.sol` hold/release/refund/slash

## Context

- [Protocol Landscape](protocol-landscape.md) — where ARS sits among AP2, VI, Visa TAP, ACP, UCP,
  MPP, and the FIDO agentic working groups

## Elsewhere in the repo

- [README](../README.md) — quickstart, API reference, error codes
- [CONTRIBUTING](../CONTRIBUTING.md) — layout, style, and test conventions
- `samples/scenarios/` — runnable end-to-end scenarios, one per modality
