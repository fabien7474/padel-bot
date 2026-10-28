#!/usr/bin/env bash
# Rend le rapport HTML consultable à tout moment depuis vos appareils Tailscale (portable, téléphone),
# et uniquement depuis eux : rien n'est publié sur Internet.
#   ./publier-rapport.sh          active (persiste après redémarrage)  ->  http://<nom-machine>/
#   ./publier-rapport.sh arret    désactive
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$(grep -E '^\s*PADEL_OUT=' "$HERE/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' || true)"
OUT="${OUT:-$HERE/resultats}"
command -v tailscale >/dev/null || { echo "Tailscale n'est pas installé sur cette machine."; exit 1; }
if [ "${1:-}" = "arret" ]; then
  sudo tailscale serve reset && echo "Rapport plus accessible (configuration Tailscale Serve effacée)."; exit 0
fi
mkdir -p "$OUT"
sudo tailscale serve --bg --http=80 "$OUT"
sudo tailscale serve status
NAME="$(tailscale status --self --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].split(".")[0])' 2>/dev/null || hostname)"
echo
echo "Rapport : http://$NAME/   (portable ou téléphone avec l'application Tailscale connectée)"
echo "Statut brut (sans noms) : http://$NAME/padel-statut.json"
