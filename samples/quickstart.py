#!/usr/bin/env python3
"""
ARS Quickstart: Full AP2-ARS fund-moving transaction flow in a single script.

This demo runs a currency exchange scenario exercising all three layers:
  1. Job setup (create + sign agreement)
  2. Mandate authorization (intent + cart + payment)
  3. Fee track (escrow the exchange amount)
  4. Principal track (underwriting + collateral)

No external server needed — runs in-process with mock settlement.

Usage:
    python samples/quickstart.py
"""

from nacl.signing import SigningKey
from fastapi.testclient import TestClient

from ap2.server.server import create_app
from ap2.client.user import UserClient
from ap2.client.merchant import MerchantClient
from ars_client.evaluator import EvaluatorClient
from ars_client.underwriter import UnderwriterClient
from ars_client._transport import Transport


def make_client(cls, test_client):
    sk = SigningKey.generate()
    client = cls.__new__(cls)
    client._sk = sk
    t = Transport.__new__(Transport)
    t._client = test_client
    client._transport = t
    return client


def main():
    print("=" * 60)
    print("ARS Quickstart: Currency Exchange (Fund-Moving)")
    print("=" * 60)

    # ── Setup: create server and actors ──────────────────────────
    app = create_app(db_path=":memory:")
    test_client = TestClient(app).__enter__()

    user = make_client(UserClient, test_client)
    merchant = make_client(MerchantClient, test_client)  # exchange service
    evaluator = make_client(EvaluatorClient, test_client)
    underwriter = make_client(UnderwriterClient, test_client)
    cred_provider = make_client(UserClient, test_client)

    print(f"\nUser (sender):     {user.pubkey[:16]}...")
    print(f"Exchange service:  {merchant.pubkey[:16]}...")
    print(f"Evaluator:         {evaluator.pubkey[:16]}...")
    print(f"Underwriter:       {underwriter.pubkey[:16]}...")

    # ── Phase 1: Job Setup ───────────────────────────────────────
    print("\n--- Phase 1: Job Setup ---")

    agreement = {
        "version": "ap2_ars/0.1",
        "job_type": "exchange_money",
        "description": "Exchange 100 USD to CAD",
        "modality": "human-present",
        "user_pubkey": user.pubkey,
        "shopping_agent_pubkey": SigningKey.generate().verify_key.encode().hex(),
        "evaluator_pubkey": evaluator.pubkey,
        "credentials_provider_pubkey": cred_provider.pubkey,
        "merchant_pubkey": merchant.pubkey,
        "payment_processor_pubkey": SigningKey.generate().verify_key.encode().hex(),
        "underwriter_pubkey": underwriter.pubkey,
        "fee": {"amount": 100, "currency": "USD"},  # $1.00 service fee
        "principal": {
            "amount": 10000,
            "currency": "USD",
            "destination": "CAD_wallet_0x1234",
        },  # $100 to exchange
    }

    job = user.create_job(agreement)
    print(f"Job created: {job.job_id[:8]}... (phase: {job.phase})")
    print(f"  Type: exchange_money | Exchange 100 USD to CAD")

    user.sign_agreement(job.job_id, job.agreement_hash)
    sig = merchant.sign_agreement(job.job_id, job.agreement_hash)
    print(f"Agreement signed by user + exchange service (phase: {sig.phase})")

    # ── Phase 2: Mandate Authorization ───────────────────────────
    print("\n--- Phase 2: Mandate Authorization ---")

    intent = user.create_intent_mandate(
        job.job_id,
        job.agreement_hash,
        budget=100,
        allowed_merchants=[merchant.pubkey],
        description="Exchange 100 USD to CAD, service fee up to $1",
        requires_principal=True,
    )
    print(f"IntentMandate created (requires_principal=True)")
    print(f"  Service fee budget: $1.00 | Merchant: exchange service")

    line_items = [
        {
            "sku": "FX-USD-CAD",
            "description": "Exchange service fee for USD/CAD at 1.36",
            "quantity": 1,
            "unit_price": 100,
        },
    ]
    cart = merchant.propose_cart(job.job_id, job.agreement_hash, line_items, total=100,)
    print(f"CartMandate proposed: exchange service fee = $1.00")

    merchant.sign_cart(job.job_id, job.agreement_hash)
    print("Cart signed by exchange service")

    user.approve_cart(job.job_id, job.agreement_hash)
    print("Exchange approved by user")

    cred_provider._post_envelope(
        f"/jobs/{job.job_id}/mandates/payment",
        "PAYMENT_MANDATE_CREATED",
        job.job_id,
        job.agreement_hash,
        payload={"payment_token_hash": "tok_bank_transfer"},
    )
    print("PaymentMandate created by credentials provider")

    payment = user.sign_payment(job.job_id, job.agreement_hash)
    print(f"Payment signed by user (state: {payment.mandate_track_state})")

    # ── Phase 3: Fee Track (escrow the service fee) ────────────
    print("\n--- Phase 3: Fee Track (Service Fee) ---")

    lock = user.lock_fee(job.job_id, job.agreement_hash)
    print(f"$1.00 service fee locked in escrow (payee: exchange service)")

    # ── Phase 4: Principal Track (underwriting the $100 exchange) ─
    print("\n--- Phase 4: Principal Track ($100 Exchange Amount) ---")

    merchant.request_uw(job.job_id, job.agreement_hash)
    print("Exchange service requested underwriting for $100 principal")

    uw = underwriter.uw_decide(
        job.job_id,
        job.agreement_hash,
        approve=True,
        premium=200,
        collateral_required=5000,
    )
    print(f"Underwriter approved: premium=$2.00, collateral=$50.00")
    print(f"  (state: {uw.principal_track_state})")

    user.pay_premium(job.job_id, job.agreement_hash, "premium_ref_bank_001")
    print("User paid $2.00 insurance premium")

    merchant.lock_collateral(job.job_id, job.agreement_hash)
    print("Exchange service locked $50.00 collateral (delivery guarantee)")
    print("  If exchange fails, collateral is slashed")

    user.approve_release(job.job_id, job.agreement_hash)
    print("User approved $100 principal release to exchange service")
    print("  Exchange service now has $100 to convert to CAD")

    # ── Phase 5: Delivery + Evaluation ───────────────────────────
    print("\n--- Phase 5: Delivery + Evaluation ---")

    merchant.submit_deliverable(
        job.job_id,
        job.agreement_hash,
        deliverable_ref="fx_confirmation:TXN-20260327-USDCAD-136.42",
    )
    print("Exchange service delivered: 136.42 CAD sent to CAD_wallet_0x1234")

    evaluator.evaluate(job.job_id, job.agreement_hash, verdict="pass")
    print("Evaluator verdict: PASS (exchange rate confirmed correct)")

    result = user.settle_fee(job.job_id, job.agreement_hash, action="release")
    print(f"Fee settled: {result.fee_track_state}")
    print(f"  $1.00 service fee released to exchange service")
    print(
        f"  $50.00 collateral automatically unlocked and returned to exchange service"
    )

    # ── Final State ──────────────────────────────────────────────
    print("\n--- Final State ---")
    state = user.get_job(job.job_id)
    print(f"Phase: {state['phase']}")
    print(f"Fee track: {state['fee_track_state']}")
    print(f"Mandate track: {state['mandate_track_state']}")
    print(f"Principal track: {state['principal_track_state']}")

    print("\n" + "=" * 60)
    print("Transaction complete!")
    print("  Principal: $100.00 USD released to exchange service")
    print("  Delivery:  136.42 CAD sent to user's CAD wallet")
    print("  Fee:       $1.00 service fee released to exchange service")
    print("  Premium:   $2.00 paid to underwriter")
    print("  Collateral: $50.00 returned to exchange service")
    print("=" * 60)


if __name__ == "__main__":
    main()
