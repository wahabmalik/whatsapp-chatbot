#!/usr/bin/env bash
# =============================================================================
# setup-server.sh — One-shot production setup for Ubuntu 22.04 / 24.04
# Run as root (or with sudo) on a fresh droplet:
#   chmod +x setup-server.sh && sudo bash setup-server.sh
# =============================================================================
set -euo pipefail

APP_USER="botuser"
APP_DIR="/opt/whatsapp-bot"
REPO_URL=""   # Set this to your git remote, e.g. git@github.com:you/python-whatsapp-bot.git
              # OR leave blank — the script will remind you to copy files manually.

echo "=== [1/8] System update ==="
apt-get update -qq && apt-get upgrade -y -qq

echo "=== [2/8] Install system packages ==="
apt-get install -y -qq \
  python3.11 python3.11-venv python3.11-dev \
  python3-pip git curl nginx ufw fail2ban

echo "=== [3/8] Install Docker + Docker Compose ==="
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
if ! command -v docker-compose &>/dev/null; then
  curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
    -o /usr/local/bin/docker-compose
  chmod +x /usr/local/bin/docker-compose
fi

echo "=== [4/8] Create app user ==="
id "$APP_USER" &>/dev/null || useradd -m -s /bin/bash "$APP_USER"
usermod -aG docker "$APP_USER"

echo "=== [5/8] Clone / copy application ==="
mkdir -p "$APP_DIR"
if [ -n "$REPO_URL" ]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  echo ""
  echo "  ⚠  REPO_URL not set. Copy your project files manually:"
  echo "     scp -r /path/to/python-whatsapp-bot/* root@SERVER_IP:$APP_DIR/"
  echo "  Then re-run: bash $APP_DIR/deploy/setup-server.sh (it will skip steps already done)"
  echo ""
fi
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

echo "=== [6/8] Python venv + dependencies ==="
sudo -u "$APP_USER" bash -c "
  cd $APP_DIR
  python3.11 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
"

echo "=== [7/8] Start Evolution API (Docker Compose) ==="
if [ -f "$APP_DIR/deploy/evolution-docker-compose.yml" ]; then
  sudo -u "$APP_USER" docker-compose -f "$APP_DIR/deploy/evolution-docker-compose.yml" up -d
else
  echo "  ⚠  $APP_DIR/deploy/evolution-docker-compose.yml not found — skip Evolution API start."
  echo "     Copy C:\\evolution-api\\docker-compose.yml to $APP_DIR/deploy/evolution-docker-compose.yml"
fi

echo "=== [8/8] Install services + firewall ==="
# systemd service
cp "$APP_DIR/deploy/bot.service" /etc/systemd/system/whatsapp-bot.service
systemctl daemon-reload
systemctl enable whatsapp-bot
systemctl start whatsapp-bot

# nginx
cp "$APP_DIR/deploy/nginx-bot.conf" /etc/nginx/sites-available/whatsapp-bot
ln -sf /etc/nginx/sites-available/whatsapp-bot /etc/nginx/sites-enabled/whatsapp-bot
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# UFW firewall
ufw allow OpenSSH
ufw allow 'Nginx HTTP'
ufw --force enable

echo ""
echo "============================================="
echo "  ✅  Setup complete"
echo ""
echo "  Next manual steps:"
echo "  1. Copy your .env file:"
echo "     scp .env root@SERVER_IP:$APP_DIR/.env"
echo "     systemctl restart whatsapp-bot"
echo ""
echo "  2. Update Evolution API key in:"
echo "     $APP_DIR/deploy/evolution-docker-compose.yml"
echo "     → AUTHENTICATION_API_KEY must match .env EVOLUTION_API_KEY"
echo ""
echo "  3. Set EVOLUTION_API_URL in .env to http://localhost:8080"
echo "     (Evolution runs on the same server)"
echo ""
echo "  4. Check bot status:   systemctl status whatsapp-bot"
echo "  5. Check bot logs:     journalctl -u whatsapp-bot -f"
echo "  6. Check Evolution:    curl http://localhost:8080"
echo "============================================="
