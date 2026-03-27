# Changelog

## 0.1.0 (2026-03-27)

Initial release of the Agentic Risk Standard.

### ars/ (Abstract Protocol)
- Event-sourced state machine with fee and principal tracks
- Ed25519 cryptographic signing with RFC 8785 canonicalization
- SQLite append-only event store
- Escrow and settlement layer ABCs with mock implementations
- Shared APIRouter factory for endpoint reuse
- 18 event types including PREMIUM_REFUSED for full override support

### ap2_ars/ (Concrete AP2 Implementation)
- AP2 mandate authorization layer (IntentMandate, CartMandate, PaymentMandate)
- 6-actor role model with cryptographic agent-payment firewall
- Dual modality: human-present and human-not-present flows
- Constraint engine for autonomous cart validation
- x402 payment rail integration (Coinbase SDK, EIP-3009 USDC)
- ARSEscrow.sol smart contract interface
- Mandate feeds into fee/principal tracks for settlement safety
- `requires_principal` flag on IntentMandate gates UW track

### ars_client/ (Abstract Client SDK)
- RequestorClient, BusinessAgentClient, EvaluatorClient, UnderwriterClient
- Typed Pydantic response models
- httpx-based transport with error handling
- Click CLI for base protocol interactions

### ap2_client/ (Concrete AP2 Client SDK)
- UserClient, MerchantClient, ShoppingAgentClient
- Mandate creation and cart management methods
- AP2 CLI extending base CLI with mandate commands
