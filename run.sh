#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Load .env
set -a
[ -f .env ] && source .env
set +a

# Install dashboard deps if needed
if [ ! -d dashboard/node_modules ]; then
    echo "Installing dashboard dependencies..."
    (cd dashboard && npm install)
fi

cleanup() {
    echo "Shutting down..."
    kill $SERVER_PID $DASHBOARD_PID 2>/dev/null || true
    wait $SERVER_PID $DASHBOARD_PID 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Start backend (FastAPI + Claude Agent SDK)
echo "Starting backend on http://localhost:8000 ..."
uv run python server_claude.py &
SERVER_PID=$!

# Start dashboard (Vite dev server)
echo "Starting dashboard on http://localhost:5173 ..."
(cd dashboard && npm run dev) &
DASHBOARD_PID=$!

echo ""
echo "Dashboard: http://localhost:5173"
echo "API:       http://localhost:8000"
echo "Press Ctrl+C to stop."
echo ""

wait
