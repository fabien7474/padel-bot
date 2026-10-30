#!/usr/bin/env bash
# Reconnecte le bot à ADOC (à lancer sur le bureau du Beelink, sur place ou par bureau à distance).
# Un navigateur s'ouvre : connectez-vous à ADOC ; le bot détecte la connexion tout seul, puis fait un relevé.
cd "$(dirname "$0")"
.venv/bin/python padel_bot.py --login
echo
read -rp "Appuyez sur Entrée pour fermer cette fenêtre..." _
