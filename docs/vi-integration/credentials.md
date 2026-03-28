# VI Credentials

VI introduces a three-layer SD-JWT credential chain that replaces AP2's three VDC mandates. Each layer is ES256-signed and cryptographically bound to the previous layer via `sd_hash`. The key addition over AP2 is **selective disclosure**: different verifiers receive different subsets of the credential data.

## L1: Issuer Credential

Signed by the **Credential Provider**. The L1 asserts user identity and binds the user's ES256 public key:

- **vct**: `VerifiedIdentity`
- **cnf.jwk**: the user's ES256 public key (key binding)
- **pan_last_four**: last four digits of payment card (selectively disclosable)
- **scheme**: card scheme (selectively disclosable)
- **TTL**: approximately 1 year

The L1 is a long-lived credential. It is not created per-job — the user brings an existing L1 to each transaction. The `L1_CREDENTIAL_ISSUED` event records the presentation of an L1, not necessarily its creation.

## L2: User Mandate

Signed by the **User**. The L2 delegates purchasing authority and binds to L1 via `sd_hash`:

- **sd_hash**: SHA-256 of the serialized L1 (cryptographic binding)
- **mode**: `immediate` or `autonomous`

In **immediate mode**, the L2 contains final checkout and payment values:
- checkout_jwt, amount, currency, payee

In **autonomous mode**, the L2 contains constraints and delegates to the agent:
- **cnf.jwk**: the agent's ES256 public key (delegation)
- **constraints**: payment amount bounds, allowed merchants, allowed payees, line items, budget caps

Disclosures are split by concern: checkout constraints are disclosed to the merchant, payment constraints are disclosed to the payment network.

## L3a: Agent Payment Fulfillment

Signed by the **Agent** (autonomous mode only). The L3a contains the agent's final payment values:

- **sd_hash**: SHA-256 of the serialized L2 (cryptographic binding)
- **transaction_id**, **payee**, **amount**, **currency**
- **TTL**: 5 minutes (per VI spec)

## L3b: Agent Checkout Fulfillment

Signed by the **Agent** (autonomous mode only). The L3b contains the agent's final checkout values:

- **sd_hash**: SHA-256 of the serialized L2 (cryptographic binding)
- **checkout_jwt**, **merchant_id**, optional **line_items**
- **TTL**: 5 minutes

## Credential Track State Machine

```
CREDENTIAL_NONE → L1_ISSUED → L2_CREATED → L2_VERIFIED
    → [autonomous: L3A_CREATED → L3B_CREATED → L3_CHAIN_VERIFIED]
    → [immediate: directly to fee lock after L2_VERIFIED]
```

L3A and L3B can be created in either order. Both must exist before chain verification.

## Cross-References via sd_hash

Each layer binds to the previous via `sd_hash` — the SHA-256 of the serialized SD-JWT string:

```
L1 (issuer signs)
  ↓ sd_hash(L1)
L2 (user signs, references L1)
  ↓ sd_hash(L2)
L3a (agent signs, references L2)    L3b (agent signs, references L2)
```

Chain verification checks that each `sd_hash` matches and that no credentials have expired.

## Selective Disclosure

The merchant and payment network each receive a different view of the credential chain:

**Merchant presentation** (`GET /jobs/{id}/credentials/present/merchant`):
- L1 credential (identity)
- L3b checkout fulfillment (items, merchant ID)
- No payment data

**Network presentation** (`GET /jobs/{id}/credentials/present/network`):
- L1 credential (identity)
- L3a payment fulfillment (amount, payee, transaction ID)
- No checkout data

This separation is enforced by the SD-JWT format. The full L2 contains both checkout and payment constraints as separate disclosures. Each presentation reveals only the relevant disclosures.

## Comparison with AP2 VDCs

| Aspect | AP2 VDCs | VI Credentials |
|--------|----------|----------------|
| Crypto | Ed25519 over canonical JSON | ES256 over SD-JWT |
| Layers | 3 flat mandates (intent → cart → payment) | 3 hierarchical layers (L1 → L2 → L3a/L3b) |
| Chaining | SHA-256 hash references | sd_hash binding + key binding (cnf) |
| Privacy | Full disclosure to all parties | Selective disclosure per verifier |
| Identity | Trust public keys directly | Issuer credential (L1) vouches for user |
| L3 shape | Linear (single PaymentMandate) | Fork: L3a (payment) + L3b (checkout) |
