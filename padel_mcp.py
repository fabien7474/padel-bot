"""Connecteur Claude (serveur MCP) du bot padel : disponibilités des pistes en direct et état du bot.

Permet de demander à Claude, y compris à la voix depuis le téléphone :
« Quelles pistes de padel sont libres mercredi à 18h45 ? » ou « Est-ce que le bot padel tourne ? »

Écoute sur 127.0.0.1:PADEL_MCP_PORT (8790) ; exposé sur Internet par Tailscale Funnel (install-mcp.sh),
à l'adresse https://<machine>.<tailnet>.ts.net/<PADEL_MCP_TOKEN>/mcp. La clé secrète du chemin fait office
de mot de passe. Aucune donnée personnelle n'est renvoyée : pistes, horaires et types d'occupation uniquement.
"""
import json, os, sys
from datetime import datetime

import padel_bot as bot
import dispo

TOKEN = os.environ.get("PADEL_MCP_TOKEN", "")
PORT = int(os.environ.get("PADEL_MCP_PORT", "8790"))
if len(TOKEN) < 24:
    sys.exit("PADEL_MCP_TOKEN absent ou trop court dans .env : lancez ./install-mcp.sh")

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "Padel Annecy Tennis",
    instructions=("Disponibilités en direct des 5 pistes de padel d'Annecy Tennis (site des Marquisats), lues dans ADOC, "
                  "et état du bot de surveillance des réservations. Créneaux de 1h15 de 7h30 à 22h30 : 7h30, 8h45, 10h00, "
                  "11h15, 12h30, 13h45, 15h00, 16h15, 17h30, 18h45, 20h00, 21h15. Réponds brièvement, en français, "
                  "souvent à l'oral."),
    host="127.0.0.1", port=PORT, streamable_http_path=f"/{TOKEN}/mcp",
    stateless_http=True, json_response=True,
    # l'accès passe par Tailscale Funnel (en-tête Host = nom public) ; la protection est la clé secrète du chemin
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
async def padel_disponibilites(date: str = "aujourd'hui", heure: str = "") -> str:
    """Pistes de padel libres ou occupées, lues en direct dans ADOC.

    date : jour voulu, de préférence AAAA-MM-JJ (2026-11-04) ; acceptés aussi « aujourd'hui », « demain »,
           un jour de la semaine (« mercredi » = le prochain mercredi, aujourd'hui compris) ou JJ/MM.
    heure : heure voulue (« 18h45 », « 18:45 ») ; vide = tous les créneaux libres de la journée.
    """
    try:
        return await dispo.reponse(date, heure)
    except ValueError as e:
        return str(e)
    except Exception as e:
        bot.log(f"MCP disponibilités : erreur {type(e).__name__}: {e}")
        return f"Impossible de lire ADOC pour le moment ({type(e).__name__})."


@mcp.tool()
def padel_statut_bot() -> str:
    """État du bot de surveillance des réservations padel : actif ou non, dernier relevé, session ADOC, cas suspects."""
    try:
        st = json.loads((bot.OUT / "padel-statut.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "Aucun statut disponible : le bot n'a encore fait aucun relevé."
    loc = lambda iso: bot.loc(iso) if iso else "jamais"
    etat = {"actif": "actif", "session": "arrêté, session ADOC expirée (à reconnecter)",
            "echec": f"dernier relevé en échec ({st.get('message')})"}.get(st.get("state"), st.get("state"))
    stale = st.get("staleAfter") and datetime.fromisoformat(st["staleAfter"]) < datetime.now(datetime.fromisoformat(st["staleAfter"]).tzinfo)
    if stale:
        etat = f"ne tourne plus depuis le {loc(st.get('lastRun'))} (Beelink éteint ou cron arrêté ?)"
    ka = bot.DATA / "keepalive.txt"
    return (f"Bot padel : {etat}. Dernier relevé le {loc(st.get('lastRun'))}, dernier relevé réussi le {loc(st.get('lastOk'))}, "
            f"prochain prévu le {loc(st.get('nextRun'))}. Cas suspects : {st.get('alerts7d', 0)} sur 7 jours, "
            f"{st.get('alerts90d', 0)} sur 90 jours. Historique {'intact' if st.get('historyIntact') else 'ALTÉRÉ'}. "
            f"Dernier entretien de session : {ka.read_text(encoding='utf-8')[:16].replace('T', ' ') if ka.exists() else 'aucun'}.")


if __name__ == "__main__":
    bot.log(f"Connecteur MCP démarré sur le port {PORT}")
    mcp.run(transport="streamable-http")
