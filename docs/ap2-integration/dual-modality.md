# Dual Modality

AP2-ARS supports two operating modalities that differ in three protocol decision points: cart approval, payment signing, and UW override handling. Both modalities converge at `PAYMENT_SIGNED` for the mandate track, but continue to differ in how UW terms are resolved in the principal track.

## Human-Present Mode

In human-present mode, the user is actively involved in the transaction. This provides the strongest guarantee of informed consent but requires the user to be available during the purchasing flow.

After the merchant proposes and signs a cart, the user reviews the line items, quantities, and prices. The user explicitly approves the cart by submitting a `CART_APPROVED_BY_USER` event. Without this approval, the flow cannot proceed to payment.

The user then signs the PaymentMandate personally. The Credentials Provider creates the mandate (since it holds the payment credentials), but the user's signature authorizes the payment.

```
Merchant: propose cart → sign cart → User: approve cart
    → CredProvider: create payment → User: sign payment → PAYMENT_SIGNED
```

## Human-Not-Present Mode

In human-not-present mode, the user pre-signs an IntentMandate with constraints and the shopping agent operates autonomously. The user does not need to be available for cart approval or payment signing.

When the merchant signs the cart, the constraint engine automatically validates it against the IntentMandate:

- **Budget check**: cart total must not exceed the intent budget.
- **Merchant whitelist**: the cart's merchant must be in the intent's `allowed_merchants` list.
- **SKU patterns**: every line item SKU must match at least one pattern in the intent's `sku_patterns` (using glob/fnmatch).
- **TTL check**: the intent must not have expired.

If all constraints pass, the constraint check result is returned alongside the cart signing response. The Credentials Provider then creates and signs the PaymentMandate without human intervention.

```
Merchant: propose cart → sign cart (+ auto constraint check)
    → CredProvider: create payment → CredProvider: sign payment → PAYMENT_SIGNED
```

## Cart Approval Enforcement

Cart approval (`CART_APPROVED_BY_USER`) is enforced based on modality:

- In **human-present** mode, `CART_APPROVED_BY_USER` is required before the PaymentMandate can be created. The state machine rejects `PAYMENT_MANDATE_CREATED` unless the mandate track is in `CART_APPROVED`.
- In **human-not-present** mode, `CART_APPROVED_BY_USER` is rejected entirely. Attempting to submit it returns a 409 error with "Cart approval only in human-present modality."

## Payment Signing Enforcement

Who signs the PaymentMandate also depends on modality:

- In **human-present** mode, only the User can sign (`PAYMENT_MANDATE_SIGNED` requires the User role).
- In **human-not-present** mode, only the Credentials Provider can sign.

This ensures that in autonomous mode, the user's pre-signed IntentMandate is the sole authorization, and the Credentials Provider executes within those bounds. In interactive mode, the user maintains direct control over every payment decision.

## Constraint Engine

The constraint engine is a pure-logic module with no I/O. It takes an IntentMandate and a CartMandate and returns a result indicating whether the cart is allowed and any violations found.

Each violation includes the field that failed and a human-readable message:

```json
{
  "allowed": false,
  "violations": [
    {"field": "budget", "message": "Cart total 6000 exceeds budget 5000"},
    {"field": "sku", "message": "SKU 'FORBIDDEN-001' does not match any allowed pattern"}
  ]
}
```

The constraint check is performed automatically during cart signing in human-not-present mode. It can also be queried on demand via `GET /jobs/{id}/constraints/check` for debugging or monitoring.

## Modality in Agreements

The modality is set at job creation as part of the `AP2AgreementDraft`:

```json
{
  "modality": "human-present"
}
```

or:

```json
{
  "modality": "human-not-present"
}
```

Once set, the modality cannot be changed. All subsequent mandate operations are validated against it.

## UW Override Handling by Modality

The IntentMandate includes two optional fields that control UW behavior in human-not-present mode:

`max_premium` (optional integer): the maximum premium the agent is pre-authorized to pay. If the underwriter requires a premium at or below this amount, the server signals that it can be auto-paid. If the premium exceeds this threshold or the field is not set, the transaction blocks until the human returns.

`allow_uw_override` (boolean, default false): whether the agent is pre-authorized to override a UW rejection or refused terms. When true, the server signals that an override can proceed automatically. When false, the transaction blocks.

The server does not auto-post events on behalf of the user. Instead, the UW decide and collateral refuse responses include an `auto_action` field that tells the agent what to do next:

| auto_action | Meaning |
|---|---|
| `premium_auto_payable` | Premium is within max_premium; agent should post PREMIUM_PAID |
| `override_recommended` | Override is pre-authorized; agent should post OVERRIDE_DECIDED |
| `awaiting_human` | No pre-authorization; transaction blocks until human returns |

In human-present mode, these fields are ignored. The user makes all decisions directly.

### Collateral Decisions

Collateral is the merchant's money, not the user's. The merchant decides whether to lock or refuse collateral. If the merchant refuses (`COLLATERAL_REFUSED`), the flow enters `OVERRIDE_PENDING`. In human-not-present mode, the server checks `allow_uw_override` and signals accordingly. The user/agent then decides whether to override (proceed without collateral protection, bearing full risk).
