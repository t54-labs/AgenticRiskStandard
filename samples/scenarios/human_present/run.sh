#!/bin/bash
# Run the full human-present scenario end-to-end.
# Starts the server in background, runs all actors, then stops the server.

set -e

echo "=== Human-Present Scenario ==="

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

# Generate keys for merchant and evaluator first
echo ""
echo "--- Generating actor keys ---"
python merchant.py sign 2>/dev/null || true  # generates key, may fail (no job yet)
python evaluator.py 2>/dev/null || true       # generates key, may fail (no job yet)

# Create job (user generates keys + creates job + signs)
echo ""
echo "--- User: Create Job ---"
python user.py create

# Merchant signs agreement
echo ""
echo "--- Merchant: Sign Agreement ---"
python merchant.py sign

# User creates intent mandate
echo ""
echo "--- User: Create Intent Mandate ---"
python user.py intent

# Merchant proposes and signs cart
echo ""
echo "--- Merchant: Propose & Sign Cart ---"
python merchant.py cart

# User approves cart
echo ""
echo "--- User: Approve Cart ---"
python user.py approve-cart

# User signs payment (credentials provider creates mandate first)
echo ""
echo "--- User: Sign Payment ---"
python user.py sign-payment

# User locks fee
echo ""
echo "--- User: Lock Fee ---"
python user.py lock-fee

# Merchant delivers
echo ""
echo "--- Merchant: Deliver ---"
python merchant.py deliver

# Evaluator evaluates
echo ""
echo "--- Evaluator: Pass ---"
python evaluator.py

# User settles
echo ""
echo "--- User: Settle Fee ---"
python user.py settle

echo ""
echo "=== Scenario Complete ==="
