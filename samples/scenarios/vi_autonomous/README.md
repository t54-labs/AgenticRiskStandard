# VI Autonomous Mode Scenario (with Principal Track)

User sets constraints and walks away. Agent fulfills within bounds. Underwriter assesses risk. Premium auto-paid within pre-authorized limit. Collateral locked by merchant.

## Setup

```bash
pip install -e ".[dev,vi]"
```

## Run

```bash
bash run.sh
```

## Flow

1. Merchant, evaluator, credential provider, underwriter generate keys
2. User creates fund-moving job (autonomous mode), creates L2 with constraints, walks away
3. Merchant signs agreement -> TRANSACTION phase
4. Credential provider issues L1 identity credential
5. Credential provider verifies L1 -> L2 chain
6. Agent creates L3a (payment fulfillment) + L3b (checkout fulfillment)
7. Credential provider verifies full chain L1 -> L2 -> L3a + L3b (with constraint check)
8. Merchant requests UW review
9. Underwriter approves with premium=$200, collateral=$5000
10. Agent auto-pays premium ($200 <= max_premium $500)
11. Merchant locks collateral
12. Agent locks fee (pre-authorized by user)
13. Merchant delivers goods
14. Evaluator issues pass verdict
15. Fee settled (release to merchant, collateral auto-unlocked) -> CLOSED
