# Dual Modality

VI-ARS supports two operating modes that differ in how many credential layers are required and who makes the final purchasing decision. Both modes converge at fee lock for the ARS settlement tracks.

## Immediate Mode

In immediate mode, the user confirms the exact purchase. Only two credential layers are needed (L1 + L2). There is no L3 because the user has already specified the final checkout and payment values.

After the credential provider issues L1 and the user creates L2 with final values, the chain is verified (L1 → L2). The credential track reaches `L2_VERIFIED`, which is sufficient for the fee lock gate.

```
CredProvider: issue L1 → User: create L2 (final values)
    → CredProvider/Network: verify L2 → L2_VERIFIED
    → Fee lock gate opens → ARS fee/principal tracks
```

L3 creation is explicitly rejected in immediate mode. Attempting to submit `L3A_PAYMENT_CREATED` or `L3B_CHECKOUT_CREATED` returns a 409 error.

## Autonomous Mode

In autonomous mode, the user delegates purchasing authority to the agent by setting constraints in L2. The agent then creates L3a (payment) and L3b (checkout) with final values that must satisfy those constraints. All three layers are required.

```
CredProvider: issue L1 → User: create L2 (constraints + agent delegation)
    → Network: verify L2 → L2_VERIFIED
    → Agent: create L3a (payment) + create L3b (checkout)
    → Network: verify full chain (+ constraint check) → L3_CHAIN_VERIFIED
    → Fee lock gate opens → ARS fee/principal tracks
```

L3a and L3b can be created in either order. Both must exist before chain verification.

## Constraint Engine

The constraint engine validates L3 fulfillment values against L2 autonomous constraints during chain verification. It is a pure-logic module with no I/O.

VI supports richer constraint types than AP2:

| Constraint | L2 Field | L3 Field Checked |
|-----------|----------|------------------|
| Payment amount bounds | `payment_amount.min_amount`, `max_amount` | L3a `amount` |
| Allowed merchants | `allowed_merchants.merchant_ids` | L3b `merchant_id` |
| Allowed payees | `allowed_payees.payee_ids` | L3a `payee` |
| Line items | `line_items.items[].product_id`, `max_quantity` | L3b `line_items` |
| Payment budget cap | `payment_budget.max_budget` | L3a `amount` |

Each violation includes the field that failed and a human-readable message:

```json
{
  "allowed": false,
  "violations": [
    {"field": "payment_amount", "message": "Amount 6000 exceeds maximum 5000"},
    {"field": "merchant", "message": "Merchant abc123 not in allowed list"}
  ]
}
```

The constraint check is performed automatically during chain verification (`POST /jobs/{id}/credentials/l3/verify`) in autonomous mode. It can also be queried on demand via `GET /jobs/{id}/constraints/check`.

## Mode in Agreements

The mode is set at job creation as part of the `VIAgreementDraft`:

```json
{
  "mode": "immediate"
}
```

or:

```json
{
  "mode": "autonomous"
}
```

Once set, the mode cannot be changed. All subsequent credential operations are validated against it.

## UW Override Handling by Mode

The `VIAgreementDraft` includes three fields that control UW behavior in autonomous mode:

`requires_principal` (boolean, default false): whether the UW/principal track is needed at all. The server blocks UW requests when false.

`max_premium` (optional integer): the maximum premium the agent is pre-authorized to pay. If the underwriter requires a premium at or below this amount, the server signals auto-payable. If exceeded or not set, the transaction blocks.

`allow_uw_override` (boolean, default false): whether the agent is pre-authorized to override a UW rejection or refused terms.

These fields live on the agreement (not on a separate IntentMandate as in AP2) because VI does not have an IntentMandate model — the L2 credential serves that purpose.

The server returns `auto_action` hints in UW responses:

| auto_action | Meaning |
|---|---|
| `premium_auto_payable` | Premium is within max_premium; agent should post PREMIUM_PAID |
| `override_recommended` | Override is pre-authorized; agent should post OVERRIDE_DECIDED |
| `awaiting_human` | No pre-authorization; transaction blocks until human returns |

In immediate mode, these fields are ignored. The user makes all decisions directly.
