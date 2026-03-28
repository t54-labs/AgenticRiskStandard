#!/usr/bin/env bash
# VI Autonomous Mode Scenario (with Principal Track)
# User sets constraints and walks away. Agent fulfills within bounds.
# Underwriter assesses risk. Premium auto-paid. Collateral locked.
set -e
cd "$(dirname "$0")"

cleanup() { kill "$SERVER_PID" 2>/dev/null; rm -f state.json; }
trap cleanup EXIT

rm -f state.json

echo "=== Starting VI server ==="
python server.py &
SERVER_PID=$!
sleep 2

echo ""
echo "=== Step 1: Generate actor keys ==="
python merchant.py keys 2>/dev/null || true
python evaluator.py 2>/dev/null || true
python credential_provider.py keys 2>/dev/null || true
python underwriter.py 2>/dev/null || true

echo ""
echo "=== Step 2: User creates job + signs agreement ==="
python user.py create

echo ""
echo "=== Step 3: Merchant signs agreement ==="
python merchant.py sign

echo ""
echo "=== Step 4: Credential provider issues L1 ==="
python credential_provider.py l1

echo ""
echo "=== Step 5: User creates L2 constraints (then walks away) ==="
python user.py l2

echo ""
echo "=== Step 6: Credential provider verifies L2 ==="
python credential_provider.py verify-l2

echo ""
echo "=== Step 7: Agent creates L3a + L3b fulfillment ==="
python agent.py

echo ""
echo "=== Step 8: Credential provider verifies full chain ==="
python credential_provider.py verify-chain

echo ""
echo "=== Step 9: Merchant requests UW review ==="
python merchant.py uw-request

echo ""
echo "=== Step 10: Underwriter decides (approve, premium=\$200, collateral=\$5000) ==="
python underwriter.py

echo ""
echo "=== Step 11: Agent auto-pays premium (\$200 <= max_premium \$500) ==="
python -c "
import json
from nacl.signing import SigningKey
from vi.client.user import VIUserClient
state = json.load(open('state.json'))
sk = SigningKey(bytes.fromhex(state['user_key']))
client = VIUserClient(base_url='http://127.0.0.1:8000', signing_key=sk)
resp = client.pay_premium(state['job_id'], state['agreement_hash'], 'premium-auto-001')
print(f'Premium paid: {resp.principal_track_state}')
"

echo ""
echo "=== Step 12: Merchant locks collateral ==="
python merchant.py lock-collateral

echo ""
echo "=== Step 13: Agent locks fee (pre-authorized) ==="
python -c "
import json
from nacl.signing import SigningKey
from vi.client.user import VIUserClient
state = json.load(open('state.json'))
sk = SigningKey(bytes.fromhex(state['user_key']))
client = VIUserClient(base_url='http://127.0.0.1:8000', signing_key=sk)
resp = client.lock_fee(state['job_id'], state['agreement_hash'])
print(f'Fee locked: {resp.lock_ref}')
"

echo ""
echo "=== Step 14: Merchant delivers ==="
python merchant.py deliver

echo ""
echo "=== Step 15: Evaluator evaluates ==="
python evaluator.py

echo ""
echo "=== Step 16: Settle fee (auto-unlocks collateral) ==="
python -c "
import json
from nacl.signing import SigningKey
from vi.client.user import VIUserClient
state = json.load(open('state.json'))
sk = SigningKey(bytes.fromhex(state['user_key']))
client = VIUserClient(base_url='http://127.0.0.1:8000', signing_key=sk)
resp = client.settle_fee(state['job_id'], state['agreement_hash'], 'release')
print(f'Fee settled: {resp.fee_track_state} (phase: {resp.phase})')
"

echo ""
echo "=== Done. Autonomous mode + principal track completed. ==="
