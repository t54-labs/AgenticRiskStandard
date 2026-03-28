# VI Immediate Mode Scenario

User confirms the exact purchase. Two-layer credential chain (L1 → L2), no agent delegation.

## Setup

```bash
pip install -e ".[dev,vi]"
```

## Run

```bash
bash run.sh
```

## Flow

1. Merchant, evaluator, credential provider generate keys
2. User creates job (immediate mode) and signs agreement
3. Merchant signs agreement → TRANSACTION phase
4. Credential provider issues L1 identity credential
5. User creates L2 mandate with final checkout/payment values
6. Credential provider verifies L1 → L2 chain
7. User locks fee in escrow
8. Merchant delivers goods
9. Evaluator issues pass verdict
10. User settles fee (release to merchant) → CLOSED
