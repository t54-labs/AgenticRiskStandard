# Transaction Flow

The complete AP2-ARS transaction flow has three phases: job setup, mandate authorization, and settlement through ARS tracks.

## Phase 1: Job Setup

The User creates a job with an `AP2AgreementDraft` specifying all six actors, the modality (human-present or human-not-present), fee terms, and optionally principal terms with an underwriter.

The User and Merchant sign the agreement. Once both signatures are recorded, the job enters the `TRANSACTION` phase. At this point, both the fee track and (if applicable) the principal track become active, and mandate creation can begin.

The agent-payment firewall is enforced at job creation. If the Shopping Agent's key matches the Credentials Provider's or Payment Processor's key, the job is rejected.

## Phase 2: Mandate Authorization

The mandate flow establishes what to buy and from whom:

1. **User creates IntentMandate** with budget, merchant whitelist, SKU patterns, TTL, and `requires_principal` flag.
2. **Merchant proposes CartMandate** with specific line items, quantities, and prices.
3. **Merchant signs the cart**, binding the prices with a short TTL.
4. In human-present mode: **User approves the cart** after reviewing it. In human-not-present mode: the **constraint engine auto-validates** (budget, merchant, SKU patterns, TTL).
5. **Credentials Provider creates PaymentMandate** referencing the cart hash.
6. **User signs the payment** (human-present) or **Credentials Provider signs** (human-not-present).

The mandate track reaches `PAYMENT_SIGNED`. The authorization is complete.

## Phase 3: Fee Track Settlement

After mandate completion, the fee track handles the actual money movement:

1. **User locks fee escrow.** The escrowed amount is the cart total from the mandate (not the pre-agreed fee in the agreement). The payee is the merchant.
2. **Merchant delivers goods** by submitting a deliverable reference (e.g., order confirmation, shipping tracking).
3. **Evaluator evaluates** the delivery and issues a pass or fail verdict.
4. **Fee is settled.** On pass, the escrowed funds are released to the merchant. On fail, they are refunded to the user. If collateral was locked, it is automatically handled: unlocked on pass (returned to merchant) or slashed on fail (seized to treasury).

The job reaches the `CLOSED` phase.

## Phase 3b: Principal Track (Optional)

When the IntentMandate has `requires_principal = True` and the agreement includes principal terms and an underwriter:

1. **Merchant requests UW review** after mandate completion.
2. **Underwriter assesses risk** and issues a decision with premium and collateral terms.
3. **User pays premium** (insurance cost) or refuses and overrides.
4. **Merchant locks collateral** (delivery guarantee) or refuses and the user overrides.
5. In the happy path (premium paid + collateral locked), the **principal is automatically released** to the merchant. In the override path (terms refused), the user must explicitly approve release first.
6. **Merchant submits execution evidence** proving the funds were used as intended.

Collateral handling is automatic: when the fee is settled, the server unlocks collateral on pass (returned to merchant) or slashes it on fail (seized to treasury). No separate action is needed.

## Enforcement Gates

Two enforcement gates connect the mandate layer to the settlement layer:

**Fee lock gate.** When a mandate exists (mandate track state is not `MANDATE_NONE`), the fee lock is blocked until the mandate reaches `PAYMENT_SIGNED`. This prevents escrowing funds before the authorization chain is complete.

**UW gate.** When a mandate exists, UW requests are blocked until `PAYMENT_SIGNED`. Additionally, UW requests are blocked if `requires_principal` is `false` on the IntentMandate, preventing unnecessary underwriting overhead.

## Flow Diagram

```
User creates job → User + Merchant sign agreement
                           ↓
User: IntentMandate → Merchant: CartMandate → Merchant: sign cart
                           ↓
[human-present: User approves cart]  OR  [human-not-present: constraint check]
                           ↓
CredProvider: PaymentMandate → User/CredProvider: sign payment
                           ↓
                    PAYMENT_SIGNED (mandate complete)
                           ↓
User: lock fee (amount = cart total, payee = merchant)
                           ↓
Merchant: deliver goods → Evaluator: pass/fail
                           ↓
User: settle fee → CLOSED (release to merchant or refund to user)
```

With principal track:

```
                    PAYMENT_SIGNED
                           ↓
              ┌────────────┴────────────┐
              ↓                         ↓
    User: lock fee              Merchant: request UW
              ↓                         ↓
    Merchant: deliver          UW: decide (premium, collateral)
              ↓                         ↓
    Evaluator: verdict         User: pay premium / Merchant: lock collateral
              ↓                         ↓
    User: settle fee           Auto-RELEASABLE → principal release
              ↓                         ↓
           CLOSED              Collateral auto-handled at fee settlement
```
