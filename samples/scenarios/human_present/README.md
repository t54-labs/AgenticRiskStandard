# Human-Present Scenario

A multi-actor demo where the user is actively involved in approving the cart and signing the payment.

## Setup

```bash
pip install -e ".[dev,client]"
```

## Run

```bash
cd samples/scenarios/human_present
bash run.sh
```

Or step by step:

```bash
# Terminal 1: Start the server
python server.py

# Terminal 2: Run the flow
python user.py create          # Creates job, outputs job_id and agreement_hash
python merchant.py sign        # Merchant signs agreement
python user.py intent          # User creates intent mandate
python merchant.py cart        # Merchant proposes and signs cart
python user.py approve-cart    # User approves cart
python user.py sign-payment    # User signs payment mandate
python user.py lock-fee        # User locks fee in escrow
python merchant.py deliver     # Merchant delivers goods
python evaluator.py            # Evaluator passes
python user.py settle          # User settles fee (release to merchant)
```

## Flow

1. User creates job with human-present modality
2. User + Merchant sign agreement
3. User creates IntentMandate (budget, merchant whitelist)
4. Merchant proposes CartMandate with line items
5. Merchant signs cart
6. User reviews and approves cart
7. Credentials provider creates PaymentMandate
8. User signs payment
9. User locks fee (cart total escrowed, merchant is payee)
10. Merchant delivers goods
11. Evaluator issues pass verdict
12. User settles fee (released to merchant)
