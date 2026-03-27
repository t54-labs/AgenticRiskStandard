# AP2 Mandates

AP2 introduces three Verifiable Digital Credentials (VDCs) that form a cryptographic chain of authorization. Each mandate is Ed25519-signed over canonicalized JSON and includes a VDC header with issuer, subject (job ID), timestamps, and expiry.

## IntentMandate

Signed by the **User**. The intent mandate pre-authorizes purchases within specified constraints:

- **budget**: maximum spend in the smallest currency unit (e.g., cents)
- **currency**: currency code (default USD)
- **allowed_merchants**: whitelist of merchant public keys authorized for this purchase
- **sku_patterns**: glob patterns for permitted SKUs (e.g., `["WIDGET-*", "GADGET-*"]`)
- **description**: natural language description of the purchasing intent
- **TTL**: time-to-live after which the intent expires (default 1 hour)
- **requires_principal**: boolean flag indicating whether the UW/principal track is needed

The intent represents the user's high-level purchasing goal and the boundaries within which the shopping agent may operate.

## CartMandate

Signed by the **Merchant**. The cart mandate binds specific line items with quantities and unit prices:

- **line_items**: list of SKU, description, quantity, and unit price
- **total**: computed sum of quantity * unit_price for all items
- **cart_hash**: SHA-256 of the canonicalized line items for integrity verification
- **merchant_id**: the merchant's public key

The cart has a short TTL (typically 5 to 15 minutes) to prevent price manipulation. The total from the cart mandate becomes the amount escrowed in the fee track.

## PaymentMandate

Signed by the **User** (human-present mode) or **Credentials Provider** (human-not-present mode). The payment mandate authorizes the final payment:

- **cart_mandate_hash**: SHA-256 of the CartMandate, binding this payment to specific goods at specific prices
- **payment_token_hash**: hash of the payment method token (the agent never sees the plaintext credentials)
- **amount**: the payment amount (matches the cart total)

## Mandate Track State Machine

The mandate track progresses through these states:

```
MANDATE_NONE → INTENT_CREATED → CART_PROPOSED → CART_SIGNED
    → [CART_APPROVED] → PAYMENT_CREATED → PAYMENT_SIGNED
```

`CART_APPROVED` is required only in human-present modality. In human-not-present mode, the constraint engine validates the cart automatically when it is signed.

`PAYMENT_SIGNED` is the terminal state. After this, the mandate authorization is complete and the transaction enters the ARS fee/principal tracks.

## Cross-References

The PaymentMandate references the CartMandate via hash, creating a verifiable chain: intent (what the user wants) -> cart (what the merchant offers) -> payment (authorization to pay for that specific cart). Any party can verify this chain by checking the hashes.

However, there is no hash link from CartMandate back to IntentMandate. The connection between intent and cart is enforced by the constraint engine (budget, merchant whitelist, SKU patterns) rather than by cryptographic chaining.

## Signing Pattern

All mandates follow the same sign-then-patch pattern:

1. Create the mandate with `signature=""` as a placeholder (the Pydantic model requires the field).
2. Extract all fields except `signature` as the signable claims.
3. Canonicalize and sign the claims with Ed25519.
4. Return a copy of the mandate with the real signature patched in.

This ensures the signature never covers itself, and the same mandate always produces the same signature given the same key.
