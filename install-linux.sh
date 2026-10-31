#!/usr/bin/env bash
# Installation du bot padel sous Linux (Linux Mint / Ubuntu / Debian)
# Usage : ./install-linux.sh      (le planning des relevés et de l'entretien de session est posé dans cron, étape 4)
set -euo pipefail
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
grep -E '^\s*PADEL_' .env | grep -v PASSWORD | sed 's/^/   /' || true
grep -qE '^\s*PADEL_ALERTE_EMAIL=' .env || echo "   Alertes e-mail non configurées (PADEL_ALERTE_EMAIL, PADEL_SMTP_PASSWORD : voir .env.example)"

echo "4/4 Tâches planifiées (cron est la seule source du planning ; à modifier ensuite avec crontab -e)..."
# Relevés : toutes les 20 min de 7h à 1h, une seule fois la nuit à 3h30 (heure de la machine, Europe/Paris).
# Entretien de la session ADOC : toutes les 7 min + 0 à 2 min au hasard (soit 5 à 9 min environ), jour et nuit.
RUN="cd $HERE && /usr/bin/flock"
PY=".venv/bin/python padel_bot.py"
CRON="# Bot padel : relevés (jour toutes les 20 min, nuit 3h30) et entretien de session (5 à 9 min)
*/20 0,7-23 * * * sleep \$(shuf -i 0-90 -n 1); $RUN -w 600 /tmp/padel-bot.lock $PY --releve >/dev/null 2>&1
30 3 * * * sleep \$(shuf -i 0-90 -n 1); $RUN -w 600 /tmp/padel-bot.lock $PY --releve >/dev/null 2>&1
*/7 * * * * sleep \$(shuf -i 0-120 -n 1); $RUN -n /tmp/padel-bot.lock $PY --entretien >/dev/null 2>&1"
( crontab -l 2>/dev/null | grep -v -e 'padel_bot.py' -e '^# Bot padel' ; echo "$CRON" ) | crontab -
crontab -l | grep padel_bot.py | sed 's/^/   /'

# Commande « padel » (padel statut, padel cas, padel reconnecter...) dans ~/.local/bin
chmod +x "$HERE/padel"
mkdir -p "$HOME/.local/bin" && ln -sf "$HERE/padel" "$HOME/.local/bin/padel"
echo "   Commande « padel » installée (ouvrir un nouveau terminal si elle n'est pas trouvée)."

# Raccourci « Reconnecter ADOC » sur le bureau (utilisable aussi par bureau à distance depuis un téléphone)
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESK" ]; then
  cat > "$DESK/reconnecter-adoc.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Reconnecter le bot ADOC
Comment=Ouvre ADOC pour reconnecter le bot padel
Exec=$HERE/reconnexion-adoc.sh
Terminal=true
Icon=web-browser
DESKTOP
  chmod +x "$DESK/reconnecter-adoc.desktop"
  gio set "$DESK/reconnecter-adoc.desktop" metadata::xfce-exe-checksum "$(sha256sum "$DESK/reconnecter-adoc.desktop" | cut -d' ' -f1)" 2>/dev/null || true
  echo "   Raccourci « Reconnecter le bot ADOC » créé sur le bureau."
fi

DATA="${PADEL_DATA:-$HOME/.local/share/padel-bot}"
if [ -f "$DATA/session.json" ]; then
  echo; echo "Session ADOC déjà présente ($DATA/session.json)."
else
  echo; echo "Il reste à se connecter à ADOC, depuis le bureau du Beelink (écran ou bureau à distance) :"
  echo "   double-clic sur « Reconnecter le bot ADOC » (ou : $HERE/reconnexion-adoc.sh)"
  echo "ou à copier la session depuis le portable (voir README)."
fi
echo; echo "Rapport consultable depuis le portable et le téléphone (via Tailscale) : ./publier-rapport.sh"
echo; echo "Terminé. Test manuel : .venv/bin/python padel_bot.py --forcer ; echo \$?"
