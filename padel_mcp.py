"""Connecteur Claude (serveur MCP) du bot padel : disponibilités des pistes en direct et état du bot.

Permet de demander à Claude, y compris à la voix depuis le téléphone :
« Quelles pistes de padel sont libres mercredi à 18h45 ? », « Est-ce que le bot padel tourne ? »
ou « Est-ce que le 06 12 34 56 78 est adhérent padel ? »

Écoute sur 127.0.0.1:PADEL_MCP_PORT (8790) ; exposé sur Internet par Tailscale Funnel (install-mcp.sh),
à l'adresse https://<machine>.<tailnet>.ts.net/<PADEL_MCP_TOKEN>/mcp. La clé secrète du chemin fait office
de mot de passe. Disponibilités et statut : aucune donnée personnelle. Adhérents : la réponse se limite au prénom, au nom
et à l'offre de la personne cherchée (jamais de téléphone, d'e-mail ni de liste complète), et il faut un numéro presque
complet ou un nom assez précis.
"""
import json, os, sys
from datetime import datetime

import padel_bot as bot
import adherents
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
                  "souvent à l'oral. Pour savoir si quelqu'un est adhérent padel, utilise padel_adherent."),
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


MAX_REPONSES = 5


@mcp.tool()
def padel_adherent(recherche: str) -> str:
    """La personne est-elle adhérente padel cette saison à Annecy Tennis ?

    recherche : numéro de téléphone (au moins 8 chiffres, « 06 12 34 56 78 » ou « +33 6 12 34 56 78 »),
                ou prénom et nom (« Jean Dupont »), ou un nom de famille d'au moins 4 lettres.
    Renvoie le prénom, le nom et l'offre padel des personnes trouvées (5 au plus), jamais leurs coordonnées.
    """
    import re
    data = adherents.charger()
    if not data:
        return "La liste des adhérents n'est pas encore disponible sur le Beelink (lancer « padel membre --frais »)."
    chiffres = re.sub(r"\D", "", recherche)
    mots = [w for w in adherents.norm(re.sub(r"[\d+().\-]", " ", recherche)).split() if len(w) >= 2]
    if not (len(chiffres) >= 8 or len(mots) >= 2 or (len(mots) == 1 and len(mots[0]) >= 4)):
        return ("Recherche trop vague : donnez un numéro de téléphone (au moins 8 chiffres), ou le prénom et le nom, "
                "ou un nom de famille d'au moins 4 lettres.")
    termes = recherche.split()
    res, approx = adherents.chercher(termes, data), False
    if not res:
        res, approx = adherents.chercher(termes, data, approx=True), True
    bot.log(f"MCP adhérent : recherche par {'téléphone' if len(chiffres) >= 8 else 'nom'}, {len(res)} résultat(s)")   # sans les termes
    quand = f"liste des adhérents padel {data['saison']} du {bot.loc(data['at'])}"
    if not res:
        return f"Non : personne ne correspond parmi les {len(data['membres'])} adhérents padel ({quand})."
    if len(res) > MAX_REPONSES:
        return f"{len(res)} adhérents padel correspondent : précisez la recherche (prénom et nom, ou numéro complet)."
    lignes = []
    for m in res:
        offres = [re.sub(r"\s*\(.*\)$", "", o).strip() for o in m["offres"]]
        offres = [o for o in offres if adherents.PADEL.search(o)] or offres
        hors = "" if m["club"] else " (offre hors de la liste du club)"
        lignes.append(f"- {m['prenom']} {m['nom']} : {', '.join(dict.fromkeys(offres))}{hors}")
    tete = "Pas de correspondance exacte ; orthographe proche :" if approx else "Oui, adhérent(s) padel :"
    return f"{tete}\n" + "\n".join(lignes) + f"\n({quand})"


if __name__ == "__main__":
    bot.log(f"Connecteur MCP démarré sur le port {PORT}")
    mcp.run(transport="streamable-http")
