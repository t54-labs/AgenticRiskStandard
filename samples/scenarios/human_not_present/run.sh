#!/bin/bash
# Run the full human-not-present (autonomous) scenario.

set -e

echo "=== Human-Not-Present (Autonomous) Scenario ==="

# Clean state
rm -f state.json

# Start server in background
echo "Starting server..."
python server.py &
SERVER_PID=$!
sleep 2

cleanup() {
    echo "Stopping server..."
    kill $SERVER_PID 2>/dev/null || true
    rm -f state.json
}
trap cleanup EXIT

# Generate keys for merchant and evaluator
echo ""
echo "--- Generate actor keys ---"
python merchant.py sign 2>/dev/null || true
python evaluator.py 2>/dev/null || true

# User creates job + intent mandate, then walks away
echo ""
echo "--- User: Setup + Intent Mandate ---"
python user.py

# Merchant signs agreement
echo ""
echo "--- Merchant: Sign Agreement ---"
python merchant.py sign

# Merchant proposes and signs cart
echo ""
echo "--- Merchant: Propose & Sign Cart ---"
python merchant.py cart

# Shopping agent orchestrates: constraint check + payment + fee lock
echo ""
echo "--- Shopping Agent: Orchestrate ---"
python agent.py

# Merchant delivers
echo ""
echo "--- Merchant: Deliver ---"
python merchant.py deliver

# Evaluator evaluates
echo ""
echo "--- Evaluator: Pass ---"
python evaluator.py

# Settle fee (agent uses user's pre-authorized key)
echo ""
echo "--- Settle Fee ---"
python -c "
import json
from nacl.signing import SigningKey
from ap2.client.user import UserClient
state = json.load(open('state.json'))
sk = SigningKey(bytes.fromhex(state['user_key']))
client = UserClient(base_url='http://127.0.0.1:8000', signing_key=sk)
resp = client.settle_fee(state['job_id'], state['agreement_hash'], 'release')
print(f'Fee settled: {resp.fee_track_state} (phase: {resp.phase})')
"

echo ""
echo "=== Scenario Complete ==="
