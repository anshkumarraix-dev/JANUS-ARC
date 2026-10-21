#!/usr/bin/env bash
# scripts/tunnel.sh — Quick-tunnel wrapper using Cloudflare Tunnels (cloudflared)
set -euo pipefail

PORT="${JANUS_PORT:-8000}"
TARGET_URL="http://127.0.0.1:${PORT}"

echo "==================================================================="
echo "Janus (ElderSync) — Cloudflare Quick-Tunnel Launcher"
echo "==================================================================="

# 1. Verify cloudflared installation
if ! command -v cloudflared &>/dev/null; then
    echo "ERROR: 'cloudflared' CLI tool is not installed or not in PATH."
    echo ""
    echo "To install cloudflared:"
    echo "  - macOS:   brew install cloudflared"
    echo "  - Linux:   curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb && sudo dpkg -i cloudflared.deb"
    echo "  - Windows: winget install --id Cloudflare.cloudflared"
    echo ""
    exit 1
fi

echo "Targeting local Janus server at: $TARGET_URL"
echo ""
echo "Starting Cloudflare quick-tunnel..."
echo "NOTE: Ephemeral trycloudflare.com URLs change on every restart."
echo "Press Ctrl+C to stop the tunnel."
echo "==================================================================="

# Temporary file to capture tunnel log output
LOG_FILE=$(mktemp)
cleanup() {
    rm -f "$LOG_FILE"
}
trap cleanup EXIT INT TERM

# Start cloudflared in background and monitor its output for the trycloudflare.com URL
cloudflared tunnel --url "$TARGET_URL" > "$LOG_FILE" 2>&1 &
TUNNEL_PID=$!

tunnel_cleanup() {
    echo ""
    echo "Shutting down cloudflared tunnel (PID $TUNNEL_PID)..."
    kill "$TUNNEL_PID" 2>/dev/null || true
    rm -f "$LOG_FILE"
}
trap tunnel_cleanup EXIT INT TERM

# Poll log file for trycloudflare.com URL
URL=""
for i in {1..30}; do
    if [ -f "$LOG_FILE" ]; then
        URL=$(grep -o 'https://[-a-zA-Z0-9.]*\.trycloudflare\.com' "$LOG_FILE" | head -n 1 || true)
        if [ -n "$URL" ]; then
            break
        fi
    fi
    sleep 0.5
done

if [ -z "$URL" ]; then
    echo "ERROR: Could not retrieve tunnel URL from cloudflared within 15 seconds."
    echo "Cloudflared logs:"
    cat "$LOG_FILE"
    exit 1
fi

echo ""
echo "==================================================================="
echo "TUNNEL ESTABLISHED!"
echo "Public Base URL:   $URL"
echo "Public MCP URL:    $URL/mcp"
echo "Public Health URL: $URL/health"
echo "==================================================================="
echo ""
echo "Paste the following into your .agents/mcp_config.json:"
echo ""
cat <<EOF
{
  "mcpServers": {
    "janus": {
      "serverUrl": "$URL/mcp"
    }
  }
}
EOF
echo ""
echo "Tunnel is active. Keeping process alive (Ctrl+C to terminate)..."
wait "$TUNNEL_PID"
