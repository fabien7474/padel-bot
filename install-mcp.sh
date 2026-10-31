#!/usr/bin/env bash
# Connecteur Claude du bot padel (disponibilités des pistes en direct, état du bot), pour l'application Claude,
# y compris à la voix sur le téléphone. Service systemd permanent + adresse HTTPS publique via Tailscale Funnel.
#   ./install-mcp.sh          installe / met à jour et affiche l'adresse à déclarer dans Claude
#   ./install-mcp.sh arret    arrête le service et ferme l'accès Internet
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PORT="$(grep -E '^\s*PADEL_MCP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 || true)"; PORT="${PORT:-8790}"
UNIT="$HOME/.config/systemd/user/padel-mcp.service"

if [ "${1:-}" = "arret" ]; then
  sudo tailscale funnel --https=443 off || true
  systemctl --user disable --now padel-mcp.service || true
  echo "Connecteur arrêté et fermé à Internet."; exit 0
fi

echo "1/4 Dépendances Python..."
.venv/bin/pip install --quiet -r requirements.txt

echo "2/4 Clé secrète..."
touch .env
if ! grep -qE '^\s*PADEL_MCP_TOKEN=.{24,}' .env; then
  echo "PADEL_MCP_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" >> .env
  echo "   nouvelle clé créée dans .env"
fi
TOKEN="$(grep -E '^\s*PADEL_MCP_TOKEN=' .env | tail -1 | cut -d= -f2-)"

echo "3/4 Service permanent (systemd utilisateur, démarre avec le Beelink)..."
mkdir -p "$(dirname "$UNIT")"
cat > "$UNIT" <<UNITEOF
[Unit]
Description=Connecteur Claude du bot padel
After=network-online.target

[Service]
WorkingDirectory=$HERE
ExecStart=$HERE/.venv/bin/python $HERE/padel_mcp.py
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNITEOF
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now padel-mcp.service
systemctl --user restart padel-mcp.service
sleep 3
systemctl --user --no-pager status padel-mcp.service | head -5

echo "4/4 Accès Internet par Tailscale Funnel (HTTPS)..."
sudo tailscale funnel --bg "$PORT"
HOST="$(tailscale status --self --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo
echo "Adresse du connecteur à déclarer dans Claude (à garder secrète, elle sert de mot de passe) :"
echo "   https://$HOST/$TOKEN/mcp"
