#!/usr/bin/env bash
# Installation du bot padel sous Linux (Linux Mint / Ubuntu / Debian)
# Usage : ./install-linux.sh [minutes]      (fréquence des relevés, 30 par défaut ; cron toutes les 10 min
#                                           pour entretenir la session ADOC entre deux relevés)
set -euo pipefail
MINUTES="${1:-30}"
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

echo "1/4 Paquets système (Python)..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip libnotify-bin >/dev/null

echo "2/4 Environnement Python et Playwright (Chromium)..."
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
sudo .venv/bin/playwright install-deps chromium >/dev/null
.venv/bin/playwright install chromium >/dev/null

echo "3/4 Configuration..."
touch .env
if grep -qE '^\s*PADEL_INTERVALLE=' .env; then sed -i "s/^\s*PADEL_INTERVALLE=.*/PADEL_INTERVALLE=$MINUTES/" .env
else echo "PADEL_INTERVALLE=$MINUTES" >> .env; fi
if [ -f .env ]; then grep -E '^\s*PADEL_' .env | sed 's/^/   /' || true
else echo "   Résultats dans : $HERE/resultats (modifiable via .env, voir .env.example)"; fi

echo "4/4 Tâche planifiée (cron toutes les 10 min : relevé toutes les $MINUTES min, entretien de session sinon)..."
LINE="*/10 * * * * cd $HERE && /usr/bin/flock -n /tmp/padel-bot.lock .venv/bin/python padel_bot.py >/dev/null 2>&1"
( crontab -l 2>/dev/null | grep -v 'padel_bot.py' ; echo "$LINE" ) | crontab -
crontab -l | grep padel_bot.py | sed 's/^/   /'

DATA="${PADEL_DATA:-$HOME/.local/share/padel-bot}"
if [ -f "$DATA/session.json" ]; then
  echo; echo "Session ADOC déjà présente ($DATA/session.json)."
else
  echo; echo "Il reste à se connecter à ADOC, depuis le bureau du Beelink (écran ou bureau à distance) :"
  echo "   cd $HERE && .venv/bin/python padel_bot.py --login"
  echo "ou à copier la session depuis le portable (voir README)."
fi
echo; echo "Rapport consultable depuis le portable et le téléphone (via Tailscale) : ./publier-rapport.sh"
echo; echo "Terminé. Test manuel : .venv/bin/python padel_bot.py --forcer ; echo \$?"
