# Principal Track

The principal track adds underwriting protection for high-value or high-risk transactions. It runs in parallel with the fee track and activates when the agreement has `job_type: "fund-moving"` or includes a `principal` field.

## Lifecycle

The principal track has more states than the fee track because it involves multi-party negotiation around risk terms:

```
Happy path:
  UW_AWAIT_REQUEST → UW_REVIEW → [PREMIUM_PENDING] → [COLLATERAL_REQUESTED]
                                                          ↓
                                                      RELEASABLE (auto)
                                                          ↓
                                            EXECUTION_PENDING → EXECUTION_EVIDENCE_SUBMITTED

Override path (refused terms):
  ... → OVERRIDE_PENDING → OVERRIDE_DECIDED → RELEASABLE → ...
```

Several states are conditional. `PREMIUM_PENDING` only appears if the underwriter requires a premium. `COLLATERAL_REQUESTED` only appears if the underwriter requires collateral.

## States

**UW_AWAIT_REQUEST** is the initial state after the agreement is bound. The business agent must request underwriting to begin.

**UW_REVIEW** means the underwriter is assessing risk. They will issue a decision with approval status, premium amount, and collateral requirement.

**PREMIUM_PENDING** appears when the underwriter approves with a premium. The requestor must pay the premium or refuse it.

**COLLATERAL_REQUESTED** appears when the underwriter requires collateral. The business agent must lock their own funds as a delivery guarantee, or the requestor can refuse on their behalf.

**RELEASABLE** is reached automatically in the happy path once all coverage conditions are satisfied (premium paid, collateral locked). No user approval is needed. The settlement layer can execute the fund transfer.

**OVERRIDE_PENDING** appears in three scenarios: (1) the underwriter rejects the transaction entirely, (2) the requestor refuses to pay the premium, or (3) the requestor refuses collateral. In all cases, the requestor can override the underwriter's terms and proceed without coverage.

In the override path, once the requestor submits `OVERRIDE_DECIDED` with `decision: "proceed"`, the state moves directly to `RELEASABLE`. No separate approval step is needed. The override IS the authorization.

**EXECUTION_PENDING** means the principal has been released. The business agent must submit execution evidence (proof that the funds were used as intended).

**EXECUTION_EVIDENCE_SUBMITTED** is the terminal state.

## Override Mechanism

The override mechanism ensures the underwriting track is advisory, not blocking. In three situations, the flow can enter `OVERRIDE_PENDING`:

**Underwriter rejects.** The underwriter issues `approve: false`. The requestor can override with `decision: "proceed"` to continue without underwriter backing.

**Premium refused.** The underwriter approves with a premium, but the requestor submits `PREMIUM_REFUSED`. The flow enters `OVERRIDE_PENDING`. The requestor can override to proceed without paying the premium (and without insurance coverage).

**Collateral refused.** The underwriter requires collateral, but the requestor submits `COLLATERAL_REFUSED` on behalf of the business agent. The flow enters `OVERRIDE_PENDING`. The requestor can override to proceed without collateral protection.

In all override cases, the transaction continues without underwriter protection. The requestor explicitly accepts the additional risk. The event log records who refused what and who overrode, providing a complete audit trail for dispute resolution.

## Role Permissions

| Action | Required Role |
|--------|--------------|
| Request UW | Business Agent |
| UW decide | Underwriter |
| Pay premium | Requestor |
| Refuse premium | Requestor |
| Lock collateral | Business Agent |
| Refuse collateral | Business Agent |
| Override | Requestor |
| Release principal | Settlement Layer |
| Submit execution evidence | Business Agent |

## Collateral as Delivery Guarantee

Collateral is locked by the **business agent** (not the requestor). It represents the agent's skin in the game: if they fail to deliver, the collateral is slashed to a protocol treasury. If delivery succeeds, the collateral is returned to the business agent. This aligns incentives: the business agent has a financial stake in successful delivery beyond just the fee.

Collateral resolution is automatic. When the fee is settled (the final step of the fee track), the server checks whether collateral exists and handles it in the same operation. A `release` action (pass verdict) unlocks collateral and returns it. A `refund` action (fail verdict) slashes collateral to treasury. No separate collateral settlement event is needed from any participant.
