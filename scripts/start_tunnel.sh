#!/usr/bin/env bash
# ==============================================================================
# Cloudflare Tunnel Quick-Start Script
# Exposes Poornima University Portal globally through Cloudflare Edge Network
# with free SSL, DDoS protection, and CDN caching without opening firewall ports.
# ==============================================================================

set -e

PORT="${1:-8000}"

echo "=========================================================="
echo " Starting Cloudflare Tunnel for Poornima University Portal"
echo " Target: http://localhost:${PORT}"
echo "=========================================================="

# Check if cloudflared binary is available
if ! command -v cloudflared &> /dev/null; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
    LOCAL_BIN="${BACKEND_DIR}/cloudflared"

    if [ ! -f "${LOCAL_BIN}" ]; then
        echo "[*] 'cloudflared' not found. Downloading standalone binary (Linux x86_64)..."
        curl -L --progress-bar "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" -o "${LOCAL_BIN}"
        chmod +x "${LOCAL_BIN}"
    fi
    CLOUDFLARED_BIN="${LOCAL_BIN}"
else
    CLOUDFLARED_BIN="cloudflared"
fi

echo "[✓] Using: $($CLOUDFLARED_BIN --version)"
echo ""
echo "Creating tunnel to http://localhost:${PORT}..."
echo "A public https://<subdomain>.trycloudflare.com URL will appear below:"
echo "=========================================================="

exec $CLOUDFLARED_BIN tunnel --url "http://localhost:${PORT}"
