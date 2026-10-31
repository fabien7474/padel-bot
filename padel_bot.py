"""Bot de surveillance des réservations de padel - Annecy Tennis (ADOC).

Usage :
  python padel_bot.py --login   ouvre Edge pour vous connecter une fois à ADOC (à refaire si la session expire)
  python padel_bot.py --releve    un relevé complet (Linux : lancé par cron, seule source du planning)
  python padel_bot.py --entretien visite légère d'ADOC qui garde la session vivante (Linux : cron, ~toutes les 7 min)
  python padel_bot.py --verifier  contrôle que l'historique permanent n'a pas été modifié
  python padel_bot.py --forcer    relevé immédiat (identique à --releve)
  python padel_bot.py --test-alerte  envoie un e-mail de test à PADEL_ALERTE_EMAIL
  python padel_bot.py           (Windows, Planificateur) relevé toutes les PADEL_INTERVALLE min, entretien sinon

Le bot n'enregistre aucun mot de passe : il réutilise la session ouverte dans son propre profil Edge,
rangé hors du dossier synchronisé (Windows : %LOCALAPPDATA%\\padel-bot ; Linux : ~/.local/share/padel-bot).
Fonctionne à l'identique sous Windows (navigateur Edge) et Linux (Chromium de Playwright).
Réglages par variables d'environnement (fichier .env à côté du script) : PADEL_OUT = dossier des résultats.
"""
import csv, json, os, subprocess, sys, traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
_env = HERE / ".env"
if _env.exists():
    for _l in _env.read_text(encoding="utf-8-sig").splitlines():
        if "=" in _l and not _l.lstrip().startswith("#"):
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"'))
OUT = Path(os.environ.get("PADEL_OUT") or HERE / "resultats")             # où écrire les CSV/JSON
DATA = Path(os.environ.get("PADEL_DATA") or (Path(os.environ["LOCALAPPDATA"]) / "padel-bot" if os.environ.get("LOCALAPPDATA")
            else Path.home() / ".local" / "share" / "padel-bot"))
PROFILE = DATA / "profil"
LOG = HERE / "bot.log"                                                    # journal technique (sans noms)
STATUS = DATA / "statut.json"
HISTORY_YEARS = int(os.environ.get("PADEL_HISTORY_YEARS", "3"))         # conservation de l'historique permanent
INTERVAL = int(os.environ.get("PADEL_INTERVALLE", "30"))                  # minutes entre deux passages (cron / Planificateur)
COOKIES = DATA / "session.json"   # cookies de session (hors dossier synchronisé, jamais publiés)
ADOC = os.environ.get("PADEL_ADOC", "https://adoc.app.fft.fr/adoc/")
HOME_URL = ADOC + "accueil.do?method=read"
SUIVI_URL = ADOC + "suiviReservations.do?method=init"   # page qui charge le service de fiches de réservation
try:
    PARIS = ZoneInfo("Europe/Paris")  # sous Windows, nécessite le paquet tzdata (requirements.txt)
except Exception:
    PARIS = None                      # à défaut : heure locale de l'ordinateur


def log(msg):
    DATA.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(PARIS):%Y-%m-%d %H:%M:%S} {msg}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)
    try:  # garde le journal technique court
        lines = LOG.read_text(encoding="utf-8").splitlines()
        if len(lines) > 2000:
            LOG.write_text("\n".join(lines[-1000:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def publish_log():
    """Copie du journal technique (sans noms d'adhérents) à côté du rapport, plus récent en haut."""
    try:
        if LOG.exists():
            OUT.mkdir(parents=True, exist_ok=True)
            lines = LOG.read_text(encoding="utf-8").splitlines()[-300:]
            ka = DATA / "keepalive.txt"
            head = [f"Journal du bot padel – copié le {datetime.now(PARIS):%d/%m/%Y %H:%M:%S}",
                    f"Dernier entretien de session réussi : {ka.read_text(encoding='utf-8')[:19].replace('T', ' ') if ka.exists() else 'aucun'}", ""]
            (OUT / "bot-log.txt").write_text("\n".join(head + lines[::-1]) + "\n", encoding="utf-8")
    except OSError:
        pass


def notify(title, text):
    """Notification Windows (bulle), sans dépendance."""
    if os.name != "nt":
        try:
            subprocess.Popen(["notify-send", "-u", "critical", title, text[:250]])
        except OSError:
            pass
        return
    t, x = title.replace("'", "’"), text.replace("'", "’")[:250]
    ps = ("[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
          "$n=New-Object System.Windows.Forms.NotifyIcon;$n.Icon=[System.Drawing.SystemIcons]::Warning;"
          f"$n.Visible=$true;$n.ShowBalloonTip(15000,'{t}','{x}','Warning');Start-Sleep -s 16;$n.Dispose()")
    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def send_mail(subject, body):
    """E-mail d'alerte (SMTP, Gmail par défaut). Destinataire et mot de passe d'application dans .env, jamais dans git."""
    import smtplib, ssl
    from email.message import EmailMessage
    to = os.environ.get("PADEL_ALERTE_EMAIL", "").strip()
    pwd = os.environ.get("PADEL_SMTP_PASSWORD", "").replace(" ", "")
    if not to:
        return False
    if not pwd:
        log("Alerte e-mail non envoyée : PADEL_SMTP_PASSWORD absent de .env")
        return False
    user = os.environ.get("PADEL_SMTP_USER", "").strip() or to
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = f"[Bot padel] {subject}", user, to
    host = os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "")
    tail = LOG.read_text(encoding="utf-8").splitlines()[-15:] if LOG.exists() else []
    msg.set_content(f"{body}\n\nMachine : {host}\nHeure : {datetime.now(PARIS):%d/%m/%Y %H:%M}\n\n"
                    "Dernières lignes du journal technique :\n" + "\n".join(tail))
    try:
        with smtplib.SMTP(os.environ.get("PADEL_SMTP_HOST", "smtp.gmail.com"),
                          int(os.environ.get("PADEL_SMTP_PORT", "587")), timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, pwd)
            s.send_message(msg)
        log(f"Alerte e-mail envoyée : {subject}")
        return True
    except Exception as e:
        log(f"Alerte e-mail impossible ({type(e).__name__}: {e})")
        return False


ALERTS = DATA / "alertes.json"


def alert(kind, active, subject="", body=""):
    """Alerte e-mail sans répétition : à l'apparition du problème, rappel toutes les PADEL_ALERTE_RAPPEL_H heures,
    puis un e-mail « rétabli » quand le problème disparaît."""
    try:
        state = json.loads(ALERTS.read_text(encoding="utf-8")) if ALERTS.exists() else {}
    except ValueError:
        state = {}
    cur, now = state.get(kind), datetime.now(timezone.utc)
    if active:
        every = float(os.environ.get("PADEL_ALERTE_RAPPEL_H", "6"))
        if cur and (now - datetime.fromisoformat(cur["sent"])).total_seconds() < every * 3600:
            return
        if not send_mail(subject if not cur else f"{subject} (rappel)", body):
            return                       # e-mail non configuré ou envoi en échec : nouvel essai au passage suivant
        state[kind] = {"since": cur["since"] if cur else now.isoformat(), "sent": now.isoformat(), "subject": subject}
    elif cur:
        since = datetime.fromisoformat(cur["since"]).astimezone(PARIS)
        if not send_mail(f"Rétabli : {cur.get('subject', kind)}", f"Le problème signalé le {since:%d/%m/%Y à %H:%M} est résolu."):
            return
        del state[kind]
    else:
        return
    DATA.mkdir(parents=True, exist_ok=True)
    ALERTS.write_text(json.dumps(state), encoding="utf-8")


def ping_external(code):
    """Signal de vie pour une surveillance externe (healthchecks.io ou compatible) : si les signaux cessent
    (Beelink éteint, Internet coupé, cron vidé), c'est le service externe qui prévient. Adresse dans .env."""
    import urllib.request
    url = os.environ.get("PADEL_HEALTHCHECK_URL", "").strip().rstrip("/")
    if not url:
        return
    try:
        urllib.request.urlopen(url + ("/fail" if code == 1 else ""), timeout=10).read()
    except Exception as e:
        log(f"Surveillance externe injoignable ({e})")


def close_profile_browsers():
    """Ferme les navigateurs restés ouverts sur le profil du bot (sinon le lancement suivant échoue).
    Ne touche pas aux autres fenêtres Edge/Chrome de l'utilisateur."""
    try:
        if os.name == "nt":
            ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" + str(PROFILE).replace("'", "''")
                  + "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            subprocess.run(["pkill", "-f", f"--user-data-dir={PROFILE}"], capture_output=True, timeout=30)
    except Exception as e:
        log(f"Impossible de fermer les navigateurs du profil : {e}")


def launch(p, headless):
    PROFILE.mkdir(parents=True, exist_ok=True)
    close_profile_browsers()
    return p.chromium.launch_persistent_context(
        str(PROFILE), channel=os.environ.get("PADEL_CHANNEL", "msedge" if os.name == "nt" else "") or None,
        headless=headless, locale="fr-FR", timezone_id="Europe/Paris",
        ignore_default_args=["--enable-automation"], args=["--disable-blink-features=AutomationControlled"])


def browser_exe(p):
    """Chemin du navigateur à ouvrir « normalement » (sans pilotage) pour la connexion."""
    if os.environ.get("PADEL_BROWSER"):
        return os.environ["PADEL_BROWSER"]
    if os.name == "nt":
        chrome = os.environ.get("PADEL_CHANNEL", "").startswith("chrome")
        rel = Path("Google", "Chrome", "Application", "chrome.exe") if chrome else Path("Microsoft", "Edge", "Application", "msedge.exe")
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            exe = Path(base or "") / rel
            if base and exe.exists():
                return str(exe)
    return p.chromium.executable_path


def load_cookies(ctx):
    """Le profil ne garde pas les cookies « de session » d'un lancement à l'autre : on les recharge."""
    if COOKIES.exists():
        try:
            ctx.add_cookies(json.loads(COOKIES.read_text(encoding="utf-8")))
        except Exception as e:
            log(f"Cookies non rechargés : {e}")


def save_cookies(ctx):
    COOKIES.write_text(json.dumps(ctx.cookies()), encoding="utf-8")


def logged_in(page):
    return page.locator('a[href*="logout"]').count() > 0


def ensure_session(page):
    page.goto(HOME_URL, wait_until="domcontentloaded")
    if logged_in(page):
        return True
    # Session ADOC expirée : « Se connecter » la rouvre si la connexion FFT est encore valide.
    page.goto(ADOC, wait_until="domcontentloaded")
    btn = page.get_by_role("button", name="Se connecter")
    if btn.count():
        btn.first.click()
        try:
            page.wait_for_url("**/accueil.do**", timeout=15000)
        except Exception:
            pass
    page.wait_for_timeout(2000)
    if not page.url.startswith(ADOC):
        from urllib.parse import urlparse
        u = urlparse(page.url)
        log(f"Reconnexion automatique par la FFT impossible (bloqué sur {u.netloc}{u.path})")
        page.goto(HOME_URL, wait_until="domcontentloaded")
    return logged_in(page)


# ---------- fichiers ----------
def loc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(PARIS).strftime("%d/%m/%Y %H:%M") if iso else ""


def day(ymd):
    return datetime.strptime(ymd, "%Y-%m-%d").strftime("%d/%m/%Y") if ymd else ""


def write_csv(name, header, rows):
    tmp = OUT / (name + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)
    try:
        os.replace(tmp, OUT / name)
    except PermissionError:  # fichier ouvert dans Excel : on réessaiera au prochain passage
        log(f"{name} est ouvert (Excel ?) : non mis à jour ce passage")
        tmp.unlink(missing_ok=True)


def write_json(name, obj):
    tmp = OUT / (name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.replace(tmp, OUT / name)
    except PermissionError:
        log(f"{name} verrouillé : non mis à jour ce passage")
        tmp.unlink(missing_ok=True)


def export(res, status=None):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = res.get("rows") or []
    is_g = lambda p: p.strip().lower().startswith("invit") or p.strip().endswith("*")
    h_alerts, h_cancels = history_views()
    # source de vérité = historique permanent ; la mémoire du navigateur ne fait que compléter
    alerts = {a["key"]: a for a in rows if a["kind"] == "alert"}
    alerts.update(h_alerts)
    cancels = {f'{c["id"]}|{c["detected"]}': c for c in rows if c["kind"] == "cancel"}
    seen_ids = {c["id"] for c in h_cancels.values()}
    cancels = {k: c for k, c in cancels.items() if c["id"] not in seen_ids}
    cancels.update(h_cancels)
    alerts = sorted(alerts.values(), key=lambda r: r["detected"], reverse=True)
    cancels = sorted(cancels.values(), key=lambda r: r["detected"], reverse=True)
    runs = record_run(res)
    resas = res.get("reservations") or []

    write_csv("padel-cas-suspects.csv",
              ["Détecté le", "Niveau", "Score", "Date du créneau", "Horaire", "Piste avant", "Joueurs avant",
               "Piste après", "Joueurs après", "Retirés", "Ajoutés", "Motifs"],
              [[loc(r["detected"]), r["level"], r["score"], day(r["date"]), r["slot"], r["beforeCourt"], r["beforePlayers"],
                r["afterCourt"], r["afterPlayers"], r["removed"], r["added"], r["reasons"]] for r in alerts])
    write_csv("padel-annulations.csv",
              ["Détectée le", "Date du créneau", "Horaire", "Piste", "Joueurs", "Nb invités/externes",
               "Réservée dès J-7", "Heures avant le créneau", "Vue pour la 1re fois le", "Id ADOC"],
              [[loc(r["detected"]), day(r["date"]), r["slot"], r["court"], r["players"], r["guests"],
                "oui" if r["early"] else "non", str(r["hoursBeforeSlot"]).replace(".", ","), loc(r["firstSeen"]), r["id"]] for r in cancels])
    write_csv("padel-passages.csv",
              ["Heure", "État", "Réservations suivies", "Nouvelles", "Annulées", "Cas suspects", "Message"],
              [[loc(r["at"]), "OK" if r.get("ok") else "Échec " + r.get("error", ""), r.get("active", ""), r.get("created", ""),
                r.get("cancelled", ""), r.get("alerts", ""), r.get("message", "")] for r in runs])
    if res.get("ok"):
        write_csv("padel-reservations.csv",
                  ["Date", "Début", "Fin", "Piste", "Joueur 1", "Joueur 2", "Joueur 3", "Joueur 4",
                   "Nb invités/externes", "Ticket invité", "Réservée dès J-7", "Vue pour la 1re fois le", "Id ADOC"],
                  [[day(r["date"]), r["start"], r["end"], r["court"], *(r["players"] + ["", "", "", ""])[:4],
                    sum(map(is_g, r["players"])), "oui" if r["ticket"] else "non", "oui" if r["early"] else "non",
                    "avant le 1er relevé" if r["baseline"] else loc(r["firstSeen"]), r["id"]] for r in resas])
        write_json("padel-reservations.json", {"releve": res.get("run"), "periode": res.get("range"), "reservations": resas})
    write_json("padel-journal.json", {"generated": datetime.now(timezone.utc).isoformat(),
                                      "alerts": alerts, "cancellations": cancels, "runs": runs})
    from report import build
    html = build(res, alerts, cancels, runs, resas if res.get("ok") else [], PARIS, status)
    idx = OUT / "index.html"   # page d'accueil quand le dossier est servi en web (publier-rapport.sh)
    if not idx.exists():
        idx.write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=padel-rapport.html">'
                       '<a href="padel-rapport.html">Rapport padel</a>', encoding="utf-8")
    if status:
        write_json("padel-statut.json", {**status, "alerts7d": sum(1 for a in alerts if _days_ago(a["detected"]) < 7),
                                         "alerts90d": len(alerts)})
    tmp = OUT / "padel-rapport.html.tmp"
    tmp.write_text(html, encoding="utf-8")
    try:
        os.replace(tmp, OUT / "padel-rapport.html")
    except PermissionError:
        log("padel-rapport.html verrouillé : non mis à jour ce passage")
        tmp.unlink(missing_ok=True)


def history_views():
    """Cas suspects (90 j) et annulations (14 j) lus dans l'historique permanent, au format des lignes du rapport."""
    import history
    sp = " · ".join
    al, ca = {}, {}
    try:
        evs = history.read_all(OUT / "historique")
    except Exception as e:
        log(f"Historique illisible pour le rapport : {e}")
        return al, ca
    for e in evs:
        if e["type"] == "cas_suspect" and _days_ago(e["at"]) < 90:
            a = e["cas"]
            b, f = a.get("before") or {}, a.get("after") or {}
            key = a.get("key") or e["hash"]
            if key in al:
                continue
            al[key] = {"kind": "alert", "key": key, "detected": a.get("detected") or e["at"], "date": a["date"],
                       "slot": f'{a.get("start")}-{a.get("end")}', "level": a.get("level"), "score": a.get("score"),
                       "beforeCourt": (b.get("court") or "") + (" (ticket)" if b.get("ticket") else ""), "beforePlayers": sp(b.get("players") or []),
                       "afterCourt": (f.get("court") or "") + (" (ticket)" if f.get("ticket") else ""), "afterPlayers": sp(f.get("players") or []),
                       "removed": sp(a.get("removed") or []), "added": sp(a.get("added") or []), "reasons": " ; ".join(a.get("reasons") or [])}
        elif e["type"] == "reservation_annulee" and _days_ago(e["at"]) < 14:
            c = e["reservation"]
            if any(x["id"] == c.get("id") for x in ca.values()):
                continue
            ps = c.get("players") or []
            ca[f'{c.get("id")}|{e["at"]}'] = {"kind": "cancel", "id": c.get("id"), "date": c["date"], "slot": f'{c.get("start")}-{c.get("end")}',
                                              "court": c.get("court") or "", "players": sp(ps),
                                              "guests": sum(1 for p in ps if p.strip().lower().startswith("invit") or p.strip().endswith("*")),
                                              "early": bool(c.get("early")), "firstSeen": c.get("firstSeen") or e["at"],
                                              "detected": c.get("detected") or e["at"], "hoursBeforeSlot": c.get("hoursBeforeSlot") or 0}
    return al, ca


def record_run(res):
    """Journal des passages tenu côté Python (7 jours), indépendant de la mémoire du navigateur."""
    path = DATA / "passages.json"
    try:
        runs = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except ValueError:
        runs = []
    r = {"at": res.get("run") or datetime.now(timezone.utc).isoformat(), "ok": bool(res.get("ok"))}
    if res.get("ok"):
        r.update(active=res.get("activeCount"), created=res.get("created"), cancelled=res.get("cancelled"), alerts=len(res.get("alerts") or []))
    else:
        r.update(error=res.get("error") or "", message=res.get("message") or "")
    runs = [x for x in runs if _days_ago(x["at"]) < 7] + [r]
    DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runs, ensure_ascii=False), encoding="utf-8")
    return sorted(runs, key=lambda x: x["at"], reverse=True)


def _days_ago(iso):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() / 86400


def archive(res, imported, prev):
    """Historique permanent, chaîné et jamais réécrit (voir history.py)."""
    import history
    OUT.mkdir(parents=True, exist_ok=True)
    root = OUT / "historique"
    evs = history.from_result(res, imported)
    if res.get("ok") and not any(root.glob("padel-evenements-*.jsonl")):
        seen = {(e["type"], (e.get("cas") or {}).get("key") or (e.get("reservation") or {}).get("id"), e["at"]) for e in evs}
        evs += [e for e in history.bootstrap(res)
                if (e["type"], (e.get("cas") or {}).get("key") or e["reservation"]["id"], e["at"]) not in seen]
    if not res.get("ok") and prev.get("error") == res.get("error"):
        evs = [e for e in evs if e["type"] != "passage_en_echec"]   # un seul événement par période d'échec
    n = history.append(root, evs)
    history.purge(root, HISTORY_YEARS, log)
    if n or not (OUT / "padel-historique-cas-suspects.csv").exists():
        history.write_cumulative_csv(root, OUT, loc, day, write_csv)
    if n:
        log(f"Historique : {n} événement(s) ajouté(s)")


def verify_history():
    import history
    res = history.verify(OUT / "historique")
    if not res:
        print("Aucun historique pour l'instant.")
    for name, n, ok, detail in res:
        print(f"{name} : {n} événements, {'INTACT' if ok else 'ALTÉRÉ – ' + detail}")
    return 0 if all(r[2] for r in res) else 3


def pause_bounds():
    """(début, fin) de la pause nocturne PADEL_PAUSE (par défaut 00:00-07:00), ou None si pas de pause."""
    spec = os.environ.get("PADEL_PAUSE", "00:00-07:00").strip()
    if not spec or spec.lower() in ("non", "aucune", "off"):
        return None
    try:
        a, b = [datetime.strptime(x.strip(), "%H:%M").time() for x in spec.split("-")]
        return a, b
    except ValueError:
        log(f"PADEL_PAUSE invalide ({spec}) : format attendu HH:MM-HH:MM")
        return None


def in_pause(now=None):
    """Pause nocturne (PADEL_PAUSE, par défaut 00:00-07:00, heure locale). Vide ou « non » = pas de pause."""
    pb = pause_bounds()
    if not pb:
        return False
    a, b = pb
    t = (now or (datetime.now(PARIS) if PARIS else datetime.now())).time()
    return a <= t < b if a <= b else (t >= a or t < b)   # gère une pause à cheval sur minuit (ex. 23:00-06:00)


def _cron_field(spec, lo, hi):
    vals = set()
    for part in spec.split(","):
        rng, _, step = part.partition("/")
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            a, b = map(int, rng.split("-"))
        else:
            a = int(rng)
            b = hi if step else a
        vals.update(range(a, b + 1, int(step or 1)))
    return vals


def cron_releves():
    """Horaires des relevés lus dans la crontab, seule source du planning sous Linux (lignes « padel_bot.py --releve »)."""
    if os.name == "nt":
        return []
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    entries = []
    for line in out.splitlines():
        f = line.split()
        if len(f) < 6 or f[0].startswith(("#", "@")) or "padel_bot.py" not in line or "--releve" not in line:
            continue
        try:
            entries.append({"min": _cron_field(f[0], 0, 59), "hour": _cron_field(f[1], 0, 23), "dom": _cron_field(f[2], 1, 31),
                            "mon": _cron_field(f[3], 1, 12), "dow": {d % 7 for d in _cron_field(f[4], 0, 7)},
                            "spec": (f[0], f[1])})
        except ValueError:
            continue
    return entries


def cron_time(entries, start, step):
    """Premier horaire de relevé à partir de start (step = +1 : suivant, -1 : précédent), à la minute près."""
    t = start.replace(second=0, microsecond=0)
    for _ in range(3 * 1440):
        if any(t.minute in e["min"] and t.hour in e["hour"] and t.day in e["dom"] and t.month in e["mon"]
               and t.isoweekday() % 7 in e["dow"] for e in entries):
            return t
        t += timedelta(minutes=step)
    return None


def planning_text(entries):
    parts = []
    for e in entries:
        m, h = e["spec"]
        hours = "toute la journée" if h == "*" else ", ".join(x.replace("-", "h–") + "h" for x in h.split(","))
        if m.startswith("*/"):
            parts.append(f"toutes les {m[2:]} min ({hours})")
        elif m.isdigit() and h.isdigit():
            parts.append(f"{int(h)}h{int(m):02d}")
        else:
            parts.append(f"cron « {m} {h} »")
    return " · ".join(parts)


def health_check():
    """Après chaque passage : e-mail si la session ADOC est perdue, si les relevés ou les entretiens ne tournent plus,
    ou si la tâche cron des relevés a disparu. (Si le Beelink est éteint ou cron vidé en entier, rien ne peut partir d'ici.)"""
    try:
        st = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    except ValueError:
        st = {}
    session = st.get("error") == "SESSION"
    alert("session", session, "Session ADOC perdue",
          "Le bot n'est plus connecté à ADOC et n'a pas pu se reconnecter seul.\n"
          "Pour le reconnecter : sur le bureau du Beelink (écran ou bureau à distance), double-clic sur "
          "« Reconnecter le bot ADOC » (ou ./reconnexion-adoc.sh), puis se connecter jusqu'à l'accueil ADOC.")
    alert("echec", st.get("ok") is False and not session, "Relevé en échec",
          f"Le dernier relevé a échoué : {st.get('error')}.")
    if os.name == "nt":
        return
    entries = cron_releves()
    alert("cron", not entries, "Tâche cron des relevés absente",
          "La crontab ne contient plus de ligne « padel_bot.py --releve » : aucun relevé n'est planifié.\n"
          "Pour la remettre : ./install-linux.sh (ou crontab -e).")
    now = datetime.now(PARIS)
    last = st.get("releve_at") or st.get("at")
    due = cron_time(entries, now - timedelta(minutes=12), -1) if entries else None   # marge : délai aléatoire + durée
    missed = bool(due and last and datetime.fromisoformat(last) < due - timedelta(minutes=1))
    alert("releve", missed, "Relevés arrêtés",
          f"Aucun relevé depuis le {datetime.fromisoformat(last).astimezone(PARIS):%d/%m/%Y à %H:%M}"
          f" alors qu'un relevé était prévu à {due:%H:%M}." if missed else "")
    ka = DATA / "keepalive.txt"
    try:
        age = (datetime.now() - datetime.fromisoformat(ka.read_text(encoding="utf-8").strip()[:26])).total_seconds() / 60
    except (OSError, ValueError):
        age = 0
    stale = age > 25 and not session
    alert("entretien", stale, "Entretien de session arrêté",
          f"Aucun contact réussi avec ADOC depuis {int(age)} min (réseau, site ADOC indisponible, ou tâche cron "
          "« --entretien » absente). La session risque d'expirer." if stale else "")


def bot_status(res, prev):
    """État du bot affiché en tête du rapport et écrit dans padel-statut.json (aucun nom d'adhérent)."""
    import history
    now = datetime.now(PARIS) if PARIS else datetime.now().astimezone()
    cron = cron_releves()
    nxt = cron_time(cron, now + timedelta(minutes=1), 1) if cron else None
    if not nxt:
        nxt = now + timedelta(minutes=INTERVAL)
        pb = pause_bounds()
        if pb and in_pause(nxt):        # prochain passage repoussé à la fin de la pause nocturne
            end = nxt.replace(hour=pb[1].hour, minute=pb[1].minute, second=0, microsecond=0)
            nxt = end if end >= nxt else end + timedelta(days=1)
    chk = history.verify(OUT / "historique")
    try:
        ver = subprocess.run(["git", "-C", str(HERE), "log", "-1", "--format=%h %cd", "--date=format:%d/%m/%Y"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        ver = ""
    ok = bool(res.get("ok"))
    return {"generated": now.astimezone(timezone.utc).isoformat(),
            "state": "actif" if ok else ("session" if res.get("error") == "SESSION" else "echec"),
            "error": None if ok else res.get("error"), "message": None if ok else res.get("message"),
            "lastRun": now.astimezone(timezone.utc).isoformat(),
            "lastOk": now.astimezone(timezone.utc).isoformat() if ok else prev.get("last_ok"),
            "nextRun": nxt.astimezone(timezone.utc).isoformat(),
            # au-delà de cette heure sans nouveau passage, la page signale que le bot semble arrêté
            "staleAfter": (nxt + timedelta(minutes=35 if cron else INTERVAL + 15)).astimezone(timezone.utc).isoformat(),
            "intervalMin": INTERVAL, "planning": planning_text(cron) if cron else None,
            "pause": "" if cron else os.environ.get("PADEL_PAUSE", "00:00-07:00").strip(),
            "host": os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", ""),
            "historyEvents": sum(n for _, n, _, _ in chk), "historyIntact": all(o for _, _, o, _ in chk),
            "details": res.get("detailsRead"), "dwr": res.get("dwr"), "version": ver}


def http_keepalive():
    """Visite légère d'ADOC sans navigateur, avec les cookies de session.json. Renvoie True si la session est vivante.
    Le serveur ADOC (Java) ferme une session restée ~30 min sans requête : cron lance le bot toutes les 10 min."""
    import http.cookiejar, urllib.request
    from urllib.parse import urlparse
    if not COOKIES.exists():
        return False
    raw = json.loads(COOKIES.read_text(encoding="utf-8"))
    jar = http.cookiejar.CookieJar()
    for c in raw:
        dom = c.get("domain") or ""
        jar.set_cookie(http.cookiejar.Cookie(0, c["name"], c["value"], None, False, dom, True, dom.startswith("."),
                                             c.get("path") or "/", True, bool(c.get("secure")),
                                             int(c["expires"]) if (c.get("expires") or -1) > 0 else None,
                                             False, None, None, {}))
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
                     ("Accept-Language", "fr-FR,fr;q=0.9")]
    try:
        with op.open(HOME_URL, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
            final = r.geturl()
    except Exception as e:
        log(f"Entretien de session : ADOC injoignable ({e})")
        return None          # réseau : on ne conclut rien
    import re
    ok = final.startswith(ADOC) and re.search(r'href="[^"]*logout', html) is not None
    if ok:   # reporte d'éventuels cookies renouvelés par le serveur
        new = {(c.domain, c.path, c.name): c.value for c in jar}
        for c in raw:
            c["value"] = new.get((c.get("domain"), c.get("path") or "/", c["name"]), c["value"])
        COOKIES.write_text(json.dumps(raw), encoding="utf-8")
    else:
        log(f"Entretien de session : déconnecté (page {urlparse(final).netloc}{urlparse(final).path})")
    return ok


def keepalive():
    """Entre deux relevés et pendant la pause nocturne : garde la session ADOC vivante, sans rien relever.
    Si elle est perdue, tente une reconnexion par la FFT ; sinon signale la session expirée dans le rapport."""
    ok = http_keepalive()
    if ok is None:
        return 0
    if ok:
        (DATA / "keepalive.txt").write_text(datetime.now().isoformat(), encoding="utf-8")
        return 0
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = launch(p, headless=True)
        try:
            load_cookies(ctx)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ok = ensure_session(page)
            if ok:
                save_cookies(ctx)
                log("Entretien de session : session rouverte par la FFT")
        finally:
            ctx.close()
    if ok:
        return 0
    prev = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    if prev.get("error") != "SESSION":
        log("Session ADOC perdue (reconnexion nécessaire)")
        notify("Bot padel : session ADOC expirée", "Reconnectez le bot à ADOC (padel_bot.py --login).")
        res = {"ok": False, "error": "SESSION", "message": "Session ADOC perdue entre deux relevés.",
               "run": datetime.now(timezone.utc).isoformat()}
        archive(res, None, prev)
        export(res, bot_status(res, prev))
        STATUS.write_text(json.dumps({**prev, "at": res["run"], "ok": False, "error": "SESSION"}), encoding="utf-8")
    return 2


def scan_due():
    """Vrai si le dernier relevé réussi date d'au moins PADEL_INTERVALLE minutes (marge de 3 min pour cron)."""
    try:
        st = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not st.get("ok"):
        return True
    return _days_ago(st["at"]) * 1440 >= INTERVAL - 3


def history_seed():
    """Cas suspects (90 j) et annulations (14 j) de l'historique permanent, pour recharger une mémoire de travail vierge."""
    try:
        import history
        now = datetime.now(timezone.utc)
        recent = lambda iso, days: (now - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days < days
        evs = history.read_all(OUT / "historique")
        fix = lambda d, at: {**d, "detected": d.get("detected") or at}
        return {"alerts": [fix(e["cas"], e["at"]) for e in evs if e["type"] == "cas_suspect" and recent(e["at"], 90)],
                "cancelled": [fix(e["reservation"], e["at"]) for e in evs if e["type"] == "reservation_annulee" and recent(e["at"], 14)]}
    except Exception as e:
        log(f"Historique illisible pour la reprise : {e}")
        return {}


def run_once():
    from playwright.sync_api import sync_playwright
    script = (HERE / "monitor.js").read_text(encoding="utf-8")
    prev = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    with sync_playwright() as p:
        ctx = launch(p, headless=True)
        try:
            load_cookies(ctx)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if ensure_session(page):
                try:
                    page.goto(SUIVI_URL, wait_until="load")
                except Exception as e:
                    log(f"Page de suivi inaccessible ({e}) : passage sans fiches détaillées")
            opts = {"maxDetails": int(os.environ.get("PADEL_MAX_DETAILS", "60"))}
            opts["seed"] = history_seed()
            imp = HERE / "import-historique.json"
            if imp.exists():
                opts["import"] = json.loads(imp.read_text(encoding="utf-8"))
            res = page.evaluate(script, opts)  # le script vérifie lui-même la session et renvoie l'échec si besoin
            imported = opts.get("import") if res.get("ok") else None
            if res.get("ok") and imp.exists():
                imp.replace(imp.with_suffix(".importe"))
                log(f"Historique importé : {res.get('imported', 0)} éléments")
            if res.get("ok"):
                save_cookies(ctx)        # garde la session à jour pour le passage suivant
                (DATA / "keepalive.txt").write_text(datetime.now().isoformat(), encoding="utf-8")
        finally:
            ctx.close()
    archive(res, imported, prev)
    export(res, bot_status(res, prev))
    if res.get("ok"):
        log(f"OK : {res['activeCount']} réservations suivies, {res['created']} nouvelles, "
            f"{res['cancelled']} annulées, {len(res['alerts'])} cas suspects, {res.get('detailsRead', 0)} fiches lues"
            + ("" if res.get("dwr") else " (fiches indisponibles)"))
        for a in res["alerts"]:
            notify(f"Bot padel : cas {a['level']}",
                   f"{day(a['date'])} {a['slot']} : {' · '.join(a['before'])} → {' · '.join(a['after'])}")
    else:
        log(f"ÉCHEC {res.get('error')} : {res.get('message')}")
        if res.get("error") == "SESSION" and prev.get("error") != "SESSION":
            notify("Bot padel : session ADOC expirée",
                   "Lancez « python padel_bot.py --login » et reconnectez-vous à ADOC.")
    now = datetime.now(timezone.utc).isoformat()
    STATUS.write_text(json.dumps({"at": now, "releve_at": now, "ok": res.get("ok"), "error": res.get("error"),
                                  "last_ok": now if res.get("ok") else prev.get("last_ok")}), encoding="utf-8")
    return 0 if res.get("ok") else 2   # 0x2 dans le Planificateur = session à reconnecter


def login():
    """Ouvre un navigateur NORMAL (non piloté, donc accepté par la page de connexion FFT),
    puis, une fois connecté, s'y raccroche juste le temps de copier la session."""
    import time, urllib.request
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True)
    port = 9333
    if os.name != "nt":   # même verrou que la tâche cron : aucun passage ne fermera la fenêtre de connexion
        import fcntl
        global _LOCK
        _LOCK = open("/tmp/padel-bot.lock", "w")
        print("Attente de la fin d'un éventuel passage du bot...")
        fcntl.flock(_LOCK, fcntl.LOCK_EX)
    with sync_playwright() as p:
        exe = browser_exe(p)
    print("Une fenêtre de navigateur va s'ouvrir : connectez-vous à ADOC avec le compte du club")
    print("(jusqu'à l'accueil ADOC, votre nom en haut à droite). NE FERMEZ PAS cette fenêtre.")
    close_profile_browsers()
    proc = subprocess.Popen([exe, f"--user-data-dir={PROFILE}", f"--remote-debugging-port={port}",
                             "--no-first-run", "--no-default-browser-check", ADOC])
    print("\nJ'attends la connexion (jusqu'à 15 minutes)...")
    ok = False
    for _ in range(180):                     # surveille les onglets sans piloter le navigateur (la FFT l'accepte)
        time.sleep(5)
        if proc.poll() is not None:
            break
        try:
            tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=3).read())
        except (OSError, ValueError):
            continue
        if any(t.get("url", "").startswith(ADOC) and "accueil.do" in t.get("url", "") for t in tabs):
            time.sleep(3)
            break
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0]
            page = ctx.new_page()
            page.goto(HOME_URL, wait_until="domcontentloaded")
            ok = logged_in(page)
            if ok:
                save_cookies(ctx)
            page.close()
            browser.close()
    except Exception as e:
        print(f"Impossible de lire la session : {e}")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        close_profile_browsers()   # Edge garde parfois des processus en arrière-plan
    print("Session enregistrée, le bot peut tourner." if ok else
          "Je ne vois pas de session ADOC ouverte : relancez et terminez bien la connexion.")
    log("Connexion manuelle : " + ("OK" if ok else "échec"))
    if ok:
        print("Relevé de contrôle en cours...")
        code = run_once()
        print("Le bot fonctionne : rapport à jour." if code == 0 else "Le relevé de contrôle a échoué : voir bot.log.")
    return 0 if ok else 2


if __name__ == "__main__":
    args, code = sys.argv[1:], 1
    if "--test-alerte" in args:
        ok = send_mail("Test d'alerte", "Ceci est un test : les alertes du bot padel arrivent bien.")
        print("E-mail de test envoyé." if ok else "Échec de l'envoi : voir bot.log (PADEL_ALERTE_EMAIL / PADEL_SMTP_PASSWORD dans .env).")
        sys.exit(0 if ok else 1)
    try:
        if "--login" in args:
            code = login()
        elif "--verifier" in args:
            sys.exit(verify_history())
        elif "--releve" in args or "--forcer" in args:
            code = run_once()
        elif "--entretien" in args:
            code = keepalive()
        # sans option (Planificateur Windows) : ancien planning interne PADEL_INTERVALLE / PADEL_PAUSE
        elif in_pause():
            keep = os.environ.get("PADEL_PAUSE_KEEPALIVE", "oui").strip().lower() not in ("non", "no", "0", "off")
            code = keepalive() if keep else 0
        elif scan_due():
            code = run_once()
        else:
            code = keepalive()
    except Exception:
        tb = traceback.format_exc()
        log("ERREUR\n" + tb)
        alert("erreur", True, "Erreur du bot", "Le bot s'est arrêté sur une erreur :\n\n" + tb[-2000:])
    finally:
        publish_log()
    try:
        if code == 0:
            alert("erreur", False)
        health_check()
    except Exception:
        log("Contrôle de santé impossible\n" + traceback.format_exc())
    ping_external(code)   # 1 = plantage : signalé comme échec ; 0 ou 2 (session) : le bot tourne
    sys.exit(code)
