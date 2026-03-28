#!/usr/bin/env bash
# VI Immediate Mode Scenario
# User confirms exact purchase. Two-layer credential chain (L1 → L2).
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
echo "=== Step 5: User creates L2 (immediate, final values) ==="
python user.py l2

echo ""
echo "=== Step 6: Credential provider verifies L2 chain ==="
python credential_provider.py verify-l2

echo ""
echo "=== Step 7: User locks fee ==="
python user.py lock-fee

echo ""
echo "=== Step 8: Merchant delivers ==="
python merchant.py deliver

echo ""
echo "=== Step 9: Evaluator evaluates ==="
python evaluator.py

echo ""
echo "=== Step 10: User settles fee ==="
python user.py settle

echo ""
echo "=== Done. Immediate mode flow completed. ==="
