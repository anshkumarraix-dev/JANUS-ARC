#!/usr/bin/env bash
# scripts/smoke.sh — End-to-end smoke test for Janus (ElderSync) FastMCP Server
set -euo pipefail

echo "==================================================================="
echo "Janus (ElderSync) — 3-Command Reviewer Smoke Test"
echo "==================================================================="

# 1. Determine Python executable (bypassing WindowsApps redirector)
if command -v python &>/dev/null && command -v python | grep -vq "WindowsApps"; then
    PYTHON_CMD="python"
elif command -v python3 &>/dev/null && command -v python3 | grep -vq "WindowsApps"; then
    PYTHON_CMD="python3"
elif command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "ERROR: Python is not installed or not in PATH."
    exit 1
fi

echo "[1/6] Using Python: $($PYTHON_CMD --version)"

# 2. Create fresh virtual environment
SMOKE_VENV=".smoke_venv"
echo "[2/6] Creating fresh virtual environment at $SMOKE_VENV..."
rm -rf "$SMOKE_VENV"
"$PYTHON_CMD" -m venv "$SMOKE_VENV"

# Locate venv binary directory (cross-platform handling for Unix / Windows Git Bash)
if [ -d "$SMOKE_VENV/Scripts" ]; then
    VENV_BIN="$SMOKE_VENV/Scripts"
else
    VENV_BIN="$SMOKE_VENV/bin"
fi

if [ -f "$VENV_BIN/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV_BIN/activate" || true
fi

# 3. Install project in editable mode with dev dependencies
echo "[3/6] Installing dependencies via pip install -e '.[dev]'..."
"$VENV_BIN/python" -m pip install --quiet -e ".[dev]"

# 4. Run pytest suite
echo "[4/6] Running pytest suite..."
"$VENV_BIN/pytest" -q

# 5. Start Janus FastMCP server in background
PORT="${JANUS_PORT:-8000}"
HOST="${JANUS_HOST:-127.0.0.1}"
export JANUS_PORT="$PORT"
export JANUS_HOST="$HOST"
export JANUS_LOG_LEVEL="warning"

echo "[5/6] Starting Janus server in background on http://$HOST:$PORT..."
"$VENV_BIN/python" -m janus.server &
SERVER_PID=$!

cleanup() {
    echo "Shutting down Janus server (PID $SERVER_PID)..."
    kill "$SERVER_PID" 2>/dev/null || true
    if command -v taskkill.exe &>/dev/null; then
        taskkill.exe //F //PID "$SERVER_PID" 2>/dev/null || true
    elif command -v taskkill &>/dev/null; then
        taskkill //F //PID "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# Wait for server readiness
READY=0
for i in {1..30}; do
    if curl -sf "http://$HOST:$PORT/health" > /dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 0.5
done

if [ "$READY" -ne 1 ]; then
    echo "ERROR: Server failed to start on http://$HOST:$PORT within 15 seconds."
    exit 1
fi

# 6. Verify /health and MCP tools/list
echo "[6/6] Probing endpoints..."

echo "-> Probing GET http://$HOST:$PORT/health"
HEALTH_RESP=$(curl -sf "http://$HOST:$PORT/health")
echo "   Response: $HEALTH_RESP"
if ! echo "$HEALTH_RESP" | grep -q '"healthy"'; then
    echo "ERROR: /health did not return healthy status."
    exit 1
fi

echo "-> Probing POST http://$HOST:$PORT/mcp (tools/list)"
TOOLS_RESP=$(curl -sf -X POST "http://$HOST:$PORT/mcp" \
    -H "Content-Type: application/json" \
    -H "MCP-Protocol-Version: 2025-11-25" \
    -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}')

echo "   Verifying tool registrations in response..."
for tool in "log_daily_routine" "get_caregiver_summary" "verify_routine_state" "flag_missed_routine"; do
    if ! echo "$TOOLS_RESP" | grep -q "\"$tool\""; then
        echo "ERROR: Expected tool '$tool' not found in tools/list response."
        exit 1
    fi
    echo "   [OK] Found tool: $tool"
done

echo ""
echo "==================================================================="
echo "SMOKE TEST PASSED! All endpoints, contracts, and tests succeeded."
echo "==================================================================="
