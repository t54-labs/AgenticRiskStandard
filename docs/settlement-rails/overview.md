# Settlement Rails Overview

ARS is designed to be rail-agnostic. The protocol defines abstract interfaces for escrow and settlement operations, and any payment rail can implement them. The fee and principal tracks operate against these abstractions without knowledge of how funds actually move.

## Design Philosophy

The core idea is separation of concerns. The state machine knows when to lock, release, refund, or slash funds. It does not know how. The settlement layer knows how to move funds on a specific rail. It does not know the business rules for when to do so.

This separation means a single ARS deployment can switch payment rails without changing any protocol logic, state machine code, or API contracts. It also means new rails can be integrated by implementing a small set of async methods.

## Layered Architecture

The settlement stack has two layers:

**EscrowClient** is the lower layer. It provides primitive deposit operations: record a deposit, release funds to the payee, refund funds to the payer, slash collateral to a treasury, and query deposit status. Each deposit is tagged by job ID and type (fee, collateral, or principal).

**SettlementLayer** is the higher layer. It composes escrow operations with optional payment rail transfers. It provides the seven operations that the server calls: `lock_fee`, `release_fee`, `refund_fee`, `lock_collateral`, `slash_collateral`, `unlock_collateral`, and `release_principal`.

The abstract ARS server programs entirely against `SettlementLayer`. Concrete implementations provide live versions that compose a specific payment rail with an escrow backend.

## Mock Implementations

For development and testing, ARS provides `MockEscrowClient` (in-memory deposit tracking) and `MockSettlementLayer` (composes the mock escrow with deterministic references). These are used by the test suite and by default when starting a server without a live settlement layer.

## Implementing a New Rail

To integrate a new payment rail with ARS:

1. Implement `EscrowClient` for your escrow mechanism (database, smart contract, custodial service).
2. Optionally implement a payment rail transfer layer (for moving funds between wallets).
3. Implement `SettlementLayer` by composing your escrow client with your transfer layer.
4. Pass the live settlement layer to `create_app(settlement=your_layer)`.

See [Abstract Interface](abstract-interface.md) for the method signatures and [x402](x402.md) for the reference implementation.
