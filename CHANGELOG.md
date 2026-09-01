# Changelog

## Unreleased

### abstract_ars/ (Abstract Protocol)
- Renamed `ars/` to `abstract_ars/` and `ars_client/` to `abstract_ars_client/` to make the
  abstract layer explicit
- Extracted `vaults.py` (`FeeEscrow` + `CollateralVault` ABCs and mocks) from the settlement layer
- `SettlementLayer` ABC and `MockSettlementLayer` now live in `abstract_ars/settlement.py` so
  concrete implementations depend on the abstract package rather than on `ap2/`

### vi/ (Concrete VI Implementation)
- VI credential authorization layer implementing Mastercard's Verifiable Intent specification
- Three-layer ES256 SD-JWT credential chain: L1 issuer credential, L2 user mandate,
  L3a/L3b agent fulfillment credentials
- Selective disclosure presentations: merchants receive checkout data only, payment networks
  receive payment data only
- 7-actor `VIRoleRegistry` with a cryptographic agent-payment firewall
- Dual modality: immediate (2-layer) and autonomous (3-layer) flows
- VI constraint engine (amount bounds, merchant whitelist, payee list, line items, budget)
- VI client SDK: `VIUserClient`, `VIAgentClient`, `VIMerchantClient`,
  `VICredentialProviderClient`, `VIPaymentNetworkClient`, and a `vi-cli` entry point

### ap2/ (Concrete AP2 Implementation)
- Reorganized into `ap2/server/` and `ap2/client/`
- `LiveFeeEscrow` and `LiveCollateralVault` extracted into `ap2/server/vaults.py`, composed by
  `LiveSettlementLayer`
- Automatic collateral resolution at fee settlement (unlock on `release`, slash on `refund`)
- Automatic principal release once coverage conditions or an override are satisfied

## 0.1.0 (2026-03-27)

Initial release of the Agentic Risk Standard.

### abstract_ars/ (Abstract Protocol)
- Event-sourced state machine with fee and principal tracks
- Ed25519 cryptographic signing with RFC 8785 canonicalization
- SQLite append-only event store
- Escrow and settlement layer ABCs with mock implementations
- Shared APIRouter factory for endpoint reuse
- 16 event types including PREMIUM_REFUSED for full override support

### ap2/server/ (Concrete AP2 Implementation)
- AP2 mandate authorization layer (IntentMandate, CartMandate, PaymentMandate)
- 6-actor role model with cryptographic agent-payment firewall
- Dual modality: human-present and human-not-present flows
- Constraint engine for autonomous cart validation
- x402 payment rail integration (Coinbase SDK, EIP-3009 USDC)
- ARSEscrow.sol smart contract interface
- Mandate feeds into fee/principal tracks for settlement safety
- `requires_principal` flag on IntentMandate gates UW track

### abstract_ars_client/ (Abstract Client SDK)
- RequestorClient, BusinessAgentClient, EvaluatorClient, UnderwriterClient
- Typed Pydantic response models
- httpx-based transport with error handling
- Click CLI for base protocol interactions

### ap2/client/ (Concrete AP2 Client SDK)
- UserClient, MerchantClient, ShoppingAgentClient
- Mandate creation and cart management methods
- AP2 CLI extending base CLI with mandate commands
