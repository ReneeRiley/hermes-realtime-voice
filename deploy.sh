#!/usr/bin/env bash
# Deploy Hermes Voice Pipeline
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Hermes Voice Pipeline Deploy ==="

# 1. Check Python
echo "[1/5] Checking Python..."
python3 -c "import sys; assert sys.version_info >= (3, 11), 'Need Python 3.11+'" || {
    echo "ERROR: Python 3.11+ required"
    exit 1
}

# 2. Set up venv
echo "[2/5] Setting up virtual environment..."
if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt

# 3. Check .env
echo "[3/5] Checking configuration..."
if [ ! -f .env ]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill in your keys."
    exit 1
fi

# 4. Stop existing service
echo "[4/5] Stopping existing service..."
sudo systemctl stop hermes-voice 2>/dev/null || true

# 5. Install and start systemd service
echo "[5/5] Installing systemd service..."
sudo cp hermes-voice.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-voice

echo ""
echo "=== Done ==="
echo "Check status:  sudo systemctl status hermes-voice"
echo "View logs:     sudo journalctl -u hermes-voice -f"
echo ""
echo "Cloudflare Tunnel (if you need to update):"
echo "  Edit /etc/cloudflared/config.yml"
echo "  Add:  ingress rules for voice.hermes.local → localhost:8080"
