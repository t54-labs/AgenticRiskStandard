# Settlement Rails Overview

ARS is designed to be rail-agnostic. The protocol defines abstract interfaces for vaults and settlement operations, and any payment rail can implement them. The fee and principal tracks operate against these abstractions without knowledge of how funds actually move.

## Design Philosophy

The core idea is separation of concerns. The state machine knows when to lock, release, refund, or slash funds. It does not know how. The settlement layer knows how to move funds on a specific rail. It does not know the business rules for when to do so.

This separation means a single ARS deployment can switch payment rails without changing any protocol logic, state machine code, or API contracts. It also means new rails can be integrated by implementing a small set of async methods.

## Layered Architecture

The settlement stack has two layers:

**Vaults** are the lower layer. Two separate abstractions handle two types of conditional fund-holding: `FeeEscrow` holds service fees in trust (released on pass, refunded on fail), and `CollateralVault` holds delivery guarantee bonds (returned on success, slashed to the requestor on failure).

**SettlementLayer** is the higher layer. It composes vault operations with optional payment rail transfers and adds direct transfer operations for premium and principal. It provides the eight operations that the server calls: `lock_fee`, `release_fee`, `refund_fee`, `lock_collateral`, `slash_collateral`, `unlock_collateral`, `pay_premium`, and `release_principal`.

The abstract ARS server programs entirely against `SettlementLayer`. Concrete implementations provide live versions that compose a specific payment rail with vault backends.

## Mock Implementations

For development and testing, ARS provides `MockFeeEscrow` and `MockCollateralVault` (in-memory deposit tracking) and `MockSettlementLayer` (composes the mock vaults with deterministic references). These are used by the test suite and by default when starting a server without a live settlement layer.

## Implementing a New Rail

To integrate a new payment rail with ARS:

1. Implement `FeeEscrow` for your fee escrow mechanism (database, smart contract, card authorization).
2. Implement `CollateralVault` for your collateral mechanism.
3. Optionally implement a payment rail transfer layer (for moving funds between wallets).
4. Implement `SettlementLayer` by composing your vaults with your transfer layer.
5. Pass the live settlement layer to `create_app(settlement=your_layer)`.

See [Abstract Interface](abstract-interface.md) for the method signatures and [x402](x402.md) for the reference implementation.
