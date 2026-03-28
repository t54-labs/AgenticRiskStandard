# VI Integration Overview

Mastercard's Verifiable Intent (VI) specification provides SD-JWT-based credential chains for agent authorization in commerce. ARS provides settlement safety through escrow, evaluation, and conditional release. We integrate VI as a concrete realization of ARS, where VI serves as the authorization layer and ARS provides the settlement guarantees.

## The Core Insight

AP2 and VI solve the same problem — proving that an AI agent's purchase was authorized by a human — but with different cryptographic foundations. AP2 uses Ed25519-signed flat JSON mandates. VI uses ES256-signed Selective Disclosure JWTs (SD-JWTs) with key binding. The critical addition VI brings is **selective disclosure**: the merchant sees only checkout data, and the payment network sees only payment data. Neither party needs to see the other's information.

This privacy separation is enforced cryptographically, not by access control. The SD-JWT format allows the holder to reveal only the disclosures relevant to each verifier. The full credential exists, but each party receives a mathematically verifiable subset.

## Architectural Inheritance

VI-ARS inherits all ARS protocol primitives through the same composition pattern as AP2:

`VIJobStateView` inherits from `JobStateView`, adding credential track fields. `VIEventType` is dynamically composed from the base `EventType` plus VI-specific credential events. The 14 shared HTTP endpoints are reused through the parameterized router factory.

The composite state machine bridges VI agreement fields to base ARS format (e.g., `payment_network_pubkey` to `settlement_layer_pubkey`) and delegates base events to the ARS state machine while handling credential events separately.

## Key Design Decisions

**Credentials authorize, tracks settle.** The credential chain (L1 → L2 → L3) determines what to buy and from whom. The fee and principal tracks handle the actual money movement with escrow protection. This is the same separation as AP2's mandate-then-settle pattern.

**Dual-key architecture.** Each actor holds an Ed25519 key for ARS event signing and an ES256 key for VI credential operations. The base ARS event store and state machine are unchanged — VI credentials are stored as opaque SD-JWT strings inside event payloads.

**Issuer credential (L1) is new.** Unlike AP2, where public keys are trusted directly, VI introduces a credential provider who vouches for the user's identity via an L1 credential. This L1 has a long lifetime (~1 year) and is brought to each job, not created per-job.

**Tree-shaped L3 flow.** AP2's mandate track is linear (intent → cart → payment). VI's credential track forks at L3: the agent creates L3a (payment fulfillment) and L3b (checkout fulfillment) independently, then both are verified together in a chain verification step.

## Further Reading

- [Role Mapping](role-mapping.md) for the 7-actor model and firewall
- [Credentials](credentials.md) for the SD-JWT authorization chain
- [Transaction Flow](transaction-flow.md) for the complete end-to-end flow
- [Dual Modality](dual-modality.md) for immediate vs autonomous modes
