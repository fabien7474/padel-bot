#!/usr/bin/env bash
# Vérifie que tout ce qui doit redémarrer seul avec le Beelink est bien en place et tourne.
#   ./verifier-beelink.sh          (demande le mot de passe sudo pour lire l'état de Tailscale)
cd "$(dirname "$0")"
HERE="$(pwd)"
ok() { printf '  \033[32mOK\033[0m  %s\n' "$*"; }
ko() { printf '  \033[31mKO\033[0m  %s\n' "$*"; KO=1; }
KO=0
echo "Démarrage automatique"
systemctl is-enabled --quiet cron && systemctl is-active --quiet cron && ok "service cron" || ko "service cron  ->  sudo systemctl enable --now cron"
CT="$(crontab -l 2>/dev/null)"
echo "$CT" | grep -q 'padel_bot.py --releve' && echo "$CT" | grep -q 'padel_bot.py --entretien' \
  && ok "tâches cron du bot (relevés + entretien de session)" || ko "tâches cron absentes ou anciennes  ->  ./install-linux.sh"
systemctl is-enabled --quiet tailscaled && systemctl is-active --quiet tailscaled && ok "Tailscale" || ko "Tailscale  ->  sudo systemctl enable --now tailscaled"
loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes && ok "services utilisateur lancés sans ouvrir de session" || ko "linger désactivé  ->  sudo loginctl enable-linger $USER"
if [ -f "$HOME/.config/systemd/user/padel-mcp.service" ]; then
  systemctl --user is-enabled --quiet padel-mcp && systemctl --user is-active --quiet padel-mcp \
    && ok "connecteur Claude (padel-mcp)" || ko "connecteur Claude arrêté  ->  ./install-mcp.sh"
else
  echo "  --  connecteur Claude non installé (./install-mcp.sh)"
fi
SERVE="$(sudo tailscale serve status 2>&1)"
echo "$SERVE" | grep -q "resultats" && ok "rapport web http://$(hostname)/" || ko "rapport web non publié  ->  ./publier-rapport.sh"
if [ -f "$HOME/.config/systemd/user/padel-mcp.service" ]; then
  sudo tailscale funnel status 2>&1 | grep -q "Funnel on" && ok "accès Internet du connecteur (Funnel)" || ko "Funnel inactif  ->  ./install-mcp.sh"
fi
echo
echo "État du bot"
python3 - "$HERE" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
here = Path(sys.argv[1])
out = here / "resultats"
env = here / ".env"
if env.exists():
    for l in env.read_text(encoding="utf-8-sig").splitlines():
        if l.strip().startswith("PADEL_OUT="):
            out = Path(l.split("=", 1)[1].strip().strip('"'))
try:
    st = json.loads((out / "padel-statut.json").read_text(encoding="utf-8"))
except Exception:
    print("  --  aucun relevé encore"); sys.exit()
age = (datetime.now(timezone.utc) - datetime.fromisoformat(st["lastRun"])).total_seconds() / 60
etat = {"actif": "actif", "session": "SESSION ADOC EXPIRÉE -> padel reconnecter (sur le bureau du Beelink)",
        "echec": "dernier relevé en échec"}.get(st.get("state"), st.get("state"))
print(f"  {etat} ; dernier relevé il y a {age:.0f} min")
PY
echo
tail -5 bot.log 2>/dev/null | sed 's/^/  /'
echo
echo "Dernier arrêt de la machine :"
last -x shutdown reboot 2>/dev/null | head -4 | sed 's/^/  /'
[ "$KO" = 0 ] && echo && echo "Tout est en place."
