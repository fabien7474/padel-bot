"""Bot de surveillance des réservations de padel - Annecy Tennis (ADOC).

Usage :
  python padel_bot.py --login   ouvre Edge pour vous connecter une fois à ADOC (à refaire si la session expire)
  python padel_bot.py           un passage (lancé toutes les 10 minutes par le Planificateur de tâches)
  python padel_bot.py --verifier  contrôle que l'historique permanent n'a pas été modifié
  python padel_bot.py --forcer    passage immédiat, même pendant la pause nocturne (PADEL_PAUSE)

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
    alerts = sorted((r for r in rows if r["kind"] == "alert"), key=lambda r: r["detected"], reverse=True)
    cancels = sorted((r for r in rows if r["kind"] == "cancel"), key=lambda r: r["detected"], reverse=True)
    runs = sorted((r for r in rows if r["kind"] == "run"), key=lambda r: r["at"], reverse=True)
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


def bot_status(res, prev):
    """État du bot affiché en tête du rapport et écrit dans padel-statut.json (aucun nom d'adhérent)."""
    import history
    now = datetime.now(PARIS) if PARIS else datetime.now().astimezone()
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
            "staleAfter": (nxt + timedelta(minutes=INTERVAL + 15)).astimezone(timezone.utc).isoformat(),
            "intervalMin": INTERVAL, "pause": os.environ.get("PADEL_PAUSE", "00:00-07:00").strip(),
            "host": os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", ""),
            "historyEvents": sum(n for _, n, _, _ in chk), "historyIntact": all(o for _, _, o, _ in chk),
            "details": res.get("detailsRead"), "dwr": res.get("dwr"), "version": ver}


def keepalive():
    """Pendant la pause nocturne : visite légère d'ADOC pour garder la session (FFT + ADOC) active.
    Ne lit aucune réservation et n'écrit aucun résultat. Au plus une visite toutes les 25 minutes."""
    from playwright.sync_api import sync_playwright
    mark = DATA / "keepalive.txt"
    try:
        if mark.exists() and (datetime.now().timestamp() - mark.stat().st_mtime) < 25 * 60:
            return 0
    except OSError:
        pass
    with sync_playwright() as p:
        ctx = launch(p, headless=True)
        try:
            load_cookies(ctx)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ok = ensure_session(page)
            if ok:
                save_cookies(ctx)
        finally:
            ctx.close()
    DATA.mkdir(parents=True, exist_ok=True)
    mark.write_text(datetime.now().isoformat(), encoding="utf-8")
    prev = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    if not ok and prev.get("error") != "SESSION":
        log("Pause nocturne : session ADOC perdue (reconnexion nécessaire)")
        notify("Bot padel : session ADOC expirée", "Lancez connexion-adoc.cmd et reconnectez-vous à ADOC.")
        STATUS.write_text(json.dumps({**prev, "at": datetime.now(timezone.utc).isoformat(), "ok": False, "error": "SESSION"}), encoding="utf-8")
    return 0 if ok else 2


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
    STATUS.write_text(json.dumps({"at": now, "ok": res.get("ok"), "error": res.get("error"),
                                  "last_ok": now if res.get("ok") else prev.get("last_ok")}), encoding="utf-8")
    return 0 if res.get("ok") else 2   # 0x2 dans le Planificateur = session à reconnecter


def login():
    """Ouvre un navigateur NORMAL (non piloté, donc accepté par la page de connexion FFT),
    puis, une fois connecté, s'y raccroche juste le temps de copier la session."""
    import time, urllib.request
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True)
    port = 9333
    with sync_playwright() as p:
        exe = browser_exe(p)
    print("Une fenêtre Edge va s'ouvrir : connectez-vous à ADOC avec le compte du club")
    print("(jusqu'à l'accueil ADOC, votre nom en haut à droite). NE FERMEZ PAS cette fenêtre.")
    close_profile_browsers()
    proc = subprocess.Popen([exe, f"--user-data-dir={PROFILE}", f"--remote-debugging-port={port}",
                             "--no-first-run", "--no-default-browser-check", ADOC])
    input("\nUne fois connecté, revenez ici et appuyez sur Entrée... ")
    ok = False
    for _ in range(10):                      # attend que le port de contrôle réponde
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            break
        except OSError:
            time.sleep(1)
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


if __name__ == "__main__":
    try:
        if "--login" in sys.argv:
            login()
        elif "--verifier" in sys.argv:
            sys.exit(verify_history())
        elif in_pause() and "--forcer" not in sys.argv:
            # pause nocturne : pas de relevé, seulement une visite légère pour ne pas perdre la session
            keep = os.environ.get("PADEL_PAUSE_KEEPALIVE", "oui").strip().lower() not in ("non", "no", "0", "off")
            sys.exit(keepalive() if keep else 0)
        else:
            sys.exit(run_once())
    except SystemExit:
        raise
    except Exception:
        log("ERREUR\n" + traceback.format_exc())
        sys.exit(1)
