# Human-Not-Present Scenario

A multi-actor demo where the user pre-signs an IntentMandate and walks away. The shopping agent orchestrates the purchase autonomously within the user's constraints.

## Setup

```bash
pip install -e ".[dev,client]"
```

## Run

```bash
cd samples/scenarios/ap2_human_not_present
bash run.sh
```

## Flow

1. User creates job with human-not-present modality
2. User + Merchant sign agreement
3. User creates IntentMandate with budget and constraints, then walks away
4. Shopping agent coordinates: merchant proposes cart
5. Merchant signs cart (constraint engine auto-validates)
6. Credentials provider creates and signs PaymentMandate
7. Shopping agent confirms mandate is complete
8. User's pre-authorized fee lock executes (cart total escrowed)
9. Merchant delivers goods
10. Evaluator issues pass verdict
11. Fee settled (released to merchant)
