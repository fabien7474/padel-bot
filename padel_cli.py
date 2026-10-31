"""Commande « padel » : les opérations courantes du bot en une commande (Linux).

  padel statut                 état du bot : session, derniers passages, prochain relevé, alertes, surveillance
  padel reconnecter            ouvre le navigateur pour se reconnecter à ADOC (sur le bureau du Beelink)
  padel releve                 relevé immédiat
  padel entretien              visite d'entretien de la session ADOC
  padel cas [-j JOURS]         cas suspects (7 derniers jours par défaut, 90 au plus)
  padel annulations [-j JOURS] annulations (7 derniers jours par défaut, 14 au plus)
  padel reservations [JOUR]    réservations suivies (aujourd'hui, demain, ou AAAA-MM-JJ / JJ/MM)
  padel planning               planning cron des relevés et de l'entretien
  padel journal [-n N] [-f]    journal technique (-f : suivre en direct)
  padel rapport                ouvre le rapport HTML
  padel alerte-test            envoie un e-mail de test
  padel verifier               contrôle l'intégrité de l'historique permanent
  padel maj                    met à jour le bot (git pull + dépendances)
"""
import argparse, fcntl, json, os, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import padel_bot as b   # noqa: E402  (charge .env et les chemins du bot)

PY = str(HERE / ".venv" / "bin" / "python")
LOCK = "/tmp/padel-bot.lock"
TTY = sys.stdout.isatty()


def c(text, color):
    codes = {"vert": "32", "rouge": "31", "jaune": "33", "gris": "90", "gras": "1"}
    return f"\033[{codes[color]}m{text}\033[0m" if TTY else str(text)


def fmt(iso, naive_local=False):
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    d = d.replace(tzinfo=b.PARIS) if d.tzinfo is None else d.astimezone(b.PARIS)
    mins = int((datetime.now(b.PARIS) - d).total_seconds() // 60)
    rel = f"dans {-mins} min" if mins < 0 else (f"il y a {mins} min" if mins < 120 else f"il y a {mins // 60} h")
    return f"{d:%d/%m %H:%M} ({rel})"


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default if default is not None else {}


def run_bot(*args, wait=True):
    """Lance padel_bot.py sous le même verrou que cron (attend la fin d'un passage en cours)."""
    cmd = ["/usr/bin/flock", "-w" if wait else "-n", "600" if wait else "", LOCK, PY, str(HERE / "padel_bot.py"), *args]
    cmd = [x for x in cmd if x != ""]
    if busy():
        print(c("Un passage du bot est en cours : j'attends qu'il se termine...", "gris"))
    return subprocess.call(cmd, cwd=HERE)


def busy():
    try:
        with open(LOCK, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


# ---------- commandes ----------
def cmd_statut(a):
    st = read_json(b.STATUS)
    pub = read_json(b.OUT / "padel-statut.json")
    alerts = read_json(b.ALERTS)
    ka = b.DATA / "keepalive.txt"
    ka_iso = ka.read_text(encoding="utf-8").strip() if ka.exists() else None
    cron = b.cron_releves()
    tab = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    entretien = any("padel_bot.py" in l and "--entretien" in l and not l.lstrip().startswith("#") for l in tab.splitlines())

    if st.get("error") == "SESSION":
        etat = c("SESSION ADOC PERDUE : lancer « padel reconnecter » sur le bureau du Beelink", "rouge")
    elif st.get("ok") is False:
        etat = c(f"dernier relevé en échec ({st.get('error')})", "rouge")
    elif st.get("ok"):
        etat = c("actif, connecté à ADOC", "vert")
    else:
        etat = c("inconnu (aucun relevé enregistré)", "jaune")
    nxt = b.cron_time(cron, datetime.now(b.PARIS) + timedelta(minutes=1), 1) if cron else None

    rows = [("État", etat),
            ("Passage en cours", c("oui", "jaune") if busy() else "non"),
            ("Dernier relevé", fmt(st.get("releve_at") or st.get("at"))),
            ("Dernier relevé réussi", fmt(st.get("last_ok"))),
            ("Dernier contact ADOC réussi", fmt(ka_iso)),
            ("Prochain relevé", fmt(nxt.isoformat()) if nxt else c("aucun (pas de ligne --releve dans cron)", "rouge")),
            ("Planning", b.planning_text(cron) if cron else c("absent", "rouge")),
            ("Entretien de session (cron)", "planifié (5 à 9 min)" if entretien else c("ABSENT de la crontab", "rouge")),
            ("Alertes e-mail", ("vers " + os.environ["PADEL_ALERTE_EMAIL"]) if os.environ.get("PADEL_ALERTE_EMAIL") and os.environ.get("PADEL_SMTP_PASSWORD")
             else c("non configurées", "jaune")),
            ("Surveillance externe", "configurée" if os.environ.get("PADEL_HEALTHCHECK_URL") else c("non configurée", "jaune")),
            ("Historique permanent", (c("intact", "vert") if pub.get("historyIntact") else c("ALTÉRÉ (padel verifier)", "rouge"))
             + f" · {pub.get('historyEvents', '?')} événements" if pub else "—"),
            ("Cas suspects", f"{pub.get('alerts7d', '?')} sur 7 j · {pub.get('alerts90d', '?')} sur 90 j" if pub else "—")]
    w = max(len(k) for k, _ in rows)
    print(c("Bot padel – état", "gras"))
    for k, v in rows:
        print(f"  {k.ljust(w)}  {v}")
    if alerts:
        print(c("\nAlertes en cours (e-mail envoyé) :", "rouge"))
        for k, v in alerts.items():
            print(f"  - {v.get('subject', k)} (depuis {fmt(v.get('since'))})")
    return 0


def cmd_reconnecter(a):
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print(c("Pas d'écran graphique dans ce terminal : lancez la commande depuis le bureau du Beelink "
                "(sur place ou par bureau à distance), ou double-cliquez sur « Reconnecter le bot ADOC ».", "jaune"))
        return 2
    return subprocess.call([PY, str(HERE / "padel_bot.py"), "--login"], cwd=HERE)   # --login prend lui-même le verrou


def cmd_releve(a):
    return run_bot("--releve")


def cmd_entretien(a):
    return run_bot("--entretien")


def cmd_cas(a):
    alerts, _ = b.history_views()
    rows = sorted((r for r in alerts.values() if b._days_ago(r["detected"]) < a.jours), key=lambda r: r["detected"], reverse=True)
    print(c(f"Cas suspects des {a.jours} derniers jours : {len(rows)}", "gras"))
    for r in rows:
        lvl = c(r["level"] or "?", {"élevé": "rouge", "moyen": "jaune"}.get(r["level"], "gris"))
        print(f"\n{lvl}  score {r['score']}  ·  créneau {b.day(r['date'])} {r['slot']}  ·  détecté {b.loc(r['detected'])}")
        print(f"  avant : {r['beforeCourt']} – {r['beforePlayers']}")
        print(f"  après : {r['afterCourt']} – {r['afterPlayers']}")
        if r["removed"] or r["added"]:
            print(f"  retirés : {r['removed'] or '—'}   ajoutés : {r['added'] or '—'}")
        if r["reasons"]:
            print(c(f"  motifs : {r['reasons']}", "gris"))
    return 0


def cmd_annulations(a):
    _, cancels = b.history_views()
    rows = sorted((r for r in cancels.values() if b._days_ago(r["detected"]) < a.jours), key=lambda r: r["detected"], reverse=True)
    print(c(f"Annulations des {a.jours} derniers jours : {len(rows)}", "gras"))
    for r in rows:
        print(f"  {b.loc(r['detected'])}  créneau {b.day(r['date'])} {r['slot']}  {r['court']}  –  {r['players']}"
              + (c(f"  ({r['hoursBeforeSlot']} h avant)", "gris") if r.get("hoursBeforeSlot") else ""))
    return 0


def cmd_reservations(a):
    data = read_json(b.OUT / "padel-reservations.json")
    resas = data.get("reservations") or []
    today = datetime.now(b.PARIS).date()
    j = (a.jour or "").lower()
    if j in ("", "aujourdhui", "aujourd'hui", "auj"):
        day = today
    elif j in ("demain", "dem"):
        day = today + timedelta(days=1)
    elif j in ("tout", "toutes", "semaine"):
        day = None
    else:
        try:
            day = datetime.strptime(j, "%Y-%m-%d").date() if "-" in j else datetime.strptime(f"{j}/{today.year}", "%d/%m/%Y").date()
        except ValueError:
            print("Jour non compris : aujourdhui, demain, tout, AAAA-MM-JJ ou JJ/MM.")
            return 1
    rows = [r for r in resas if day is None or r["date"] == day.isoformat()]
    rows.sort(key=lambda r: (r["date"], r["start"], r["court"]))
    title = "toutes" if day is None else f"{day:%d/%m/%Y}"
    print(c(f"Réservations suivies ({title}) : {len(rows)}", "gras") + c(f"   relevé du {b.loc(data.get('releve'))}", "gris"))
    cur = None
    for r in rows:
        if day is None and r["date"] != cur:
            cur = r["date"]
            print(c(f"\n{b.day(cur)}", "gras"))
        print(f"  {r['start']}-{r['end']}  {r['court']:<10} {' · '.join(r['players'])}" + (c("  (ticket)", "gris") if r.get("ticket") else ""))
    return 0


def cmd_planning(a):
    tab = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    lines = [l for l in tab.splitlines() if "padel_bot.py" in l or l.startswith("# Bot padel")]
    cron = b.cron_releves()
    print(c("Relevés : ", "gras") + (b.planning_text(cron) if cron else c("aucun", "rouge")))
    if cron:
        t, nxt = datetime.now(b.PARIS), []
        for _ in range(5):
            t = b.cron_time(cron, t + timedelta(minutes=1), 1)
            nxt.append(f"{'lun mar mer jeu ven sam dim'.split()[t.weekday()]} {t:%H:%M}")
        print("Prochains relevés : " + ", ".join(nxt))
    print(c("\nLignes cron (crontab -e pour modifier) :", "gras"))
    print("\n".join("  " + l for l in lines) if lines else c("  aucune ligne du bot dans la crontab !", "rouge"))
    return 0


def cmd_journal(a):
    if a.suivre:
        return subprocess.call(["tail", "-n", str(a.n), "-f", str(b.LOG)])
    lines = b.LOG.read_text(encoding="utf-8").splitlines()[-a.n:] if b.LOG.exists() else []
    for l in lines:
        print(c(l, "rouge") if any(w in l for w in ("ÉCHEC", "ERREUR", "perdue", "impossible", "injoignable")) else l)
    return 0


def cmd_rapport(a):
    path = b.OUT / "padel-rapport.html"
    if not path.exists():
        print("Pas encore de rapport : lancez « padel releve ».")
        return 1
    print(path)
    return subprocess.call(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_alerte_test(a):
    return subprocess.call([PY, str(HERE / "padel_bot.py"), "--test-alerte"], cwd=HERE)


def cmd_verifier(a):
    return subprocess.call([PY, str(HERE / "padel_bot.py"), "--verifier"], cwd=HERE)


def cmd_maj(a):
    code = subprocess.call(["git", "-C", str(HERE), "pull", "--ff-only"])
    if code == 0:
        code = subprocess.call([PY, "-m", "pip", "install", "--quiet", "-r", str(HERE / "requirements.txt")])
    print("Bot à jour." if code == 0 else c("Échec de la mise à jour.", "rouge"))
    return code


def main(argv=None):
    p = argparse.ArgumentParser(prog="padel", description="Commandes du bot padel ADOC.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n", 2)[2])
    sp = p.add_subparsers(dest="cmd", metavar="COMMANDE")
    def add(name, fn, help, aliases=()):
        s = sp.add_parser(name, help=help, aliases=list(aliases))
        s.set_defaults(fn=fn)
        return s
    add("statut", cmd_statut, "état du bot", ["status", "etat", "état"])
    add("reconnecter", cmd_reconnecter, "se reconnecter à ADOC (bureau du Beelink)", ["reconnecte", "connexion", "login"])
    add("releve", cmd_releve, "relevé immédiat", ["relevé", "scan"])
    add("entretien", cmd_entretien, "visite d'entretien de la session", ["keepalive"])
    add("cas", cmd_cas, "cas suspects", ["suspects"]).add_argument("-j", "--jours", type=int, default=7)
    add("annulations", cmd_annulations, "annulations", ["annul"]).add_argument("-j", "--jours", type=int, default=7)
    add("reservations", cmd_reservations, "réservations suivies", ["réservations", "resas"]).add_argument("jour", nargs="?")
    add("planning", cmd_planning, "planning cron", ["cron"])
    j = add("journal", cmd_journal, "journal technique", ["log", "logs"])
    j.add_argument("-n", type=int, default=25)
    j.add_argument("-f", "--suivre", action="store_true")
    add("rapport", cmd_rapport, "ouvrir le rapport HTML", ["report"])
    add("alerte-test", cmd_alerte_test, "e-mail de test", ["test-alerte"])
    add("verifier", cmd_verifier, "intégrité de l'historique", ["vérifier"])
    add("maj", cmd_maj, "mettre à jour le bot", ["update"])
    a = p.parse_args(argv)
    if not getattr(a, "fn", None):
        p.print_help()
        return 0
    try:
        return a.fn(a) or 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
