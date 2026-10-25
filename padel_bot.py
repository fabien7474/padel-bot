"""Bot de surveillance des réservations de padel - Annecy Tennis (ADOC).

Usage :
  python padel_bot.py --login   ouvre Edge pour vous connecter une fois à ADOC (à refaire si la session expire)
  python padel_bot.py           un passage (lancé toutes les 10 minutes par le Planificateur de tâches)
  python padel_bot.py --verifier  contrôle que l'historique permanent n'a pas été modifié

Le bot n'enregistre aucun mot de passe : il réutilise la session ouverte dans son propre profil Edge,
rangé hors du dossier synchronisé (Windows : %LOCALAPPDATA%\\padel-bot ; Linux : ~/.local/share/padel-bot).
Fonctionne à l'identique sous Windows (navigateur Edge) et Linux (Chromium de Playwright).
Réglages par variables d'environnement (fichier .env à côté du script) : PADEL_OUT = dossier des résultats.
"""
import csv, json, os, subprocess, sys, traceback
from datetime import datetime, timezone
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
COOKIES = DATA / "session.json"   # cookies de session (hors dossier synchronisé, jamais publiés)
ADOC = os.environ.get("PADEL_ADOC", "https://adoc.app.fft.fr/adoc/")
HOME_URL = ADOC + "accueil.do?method=read"
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


def launch(p, headless):
    PROFILE.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        str(PROFILE), channel=os.environ.get("PADEL_CHANNEL", "msedge" if os.name == "nt" else "") or None,
        headless=headless, locale="fr-FR", timezone_id="Europe/Paris",
        ignore_default_args=["--enable-automation"], args=["--disable-blink-features=AutomationControlled"])


def browser_exe(p):
    """Chemin du navigateur à ouvrir « normalement » (sans pilotage) pour la connexion."""
    if os.environ.get("PADEL_BROWSER"):
        return os.environ["PADEL_BROWSER"]
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            exe = Path(base or "") / "Microsoft" / "Edge" / "Application" / "msedge.exe"
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


def export(res):
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
    html = build(res, alerts, cancels, runs, resas if res.get("ok") else [], PARIS)
    tmp = OUT / "padel-rapport.html.tmp"
    tmp.write_text(html, encoding="utf-8")
    try:
        os.replace(tmp, OUT / "padel-rapport.html")
    except PermissionError:
        log("padel-rapport.html verrouillé : non mis à jour ce passage")
        tmp.unlink(missing_ok=True)


def archive(res, imported, prev):
    """Historique permanent, chaîné et jamais réécrit (voir history.py)."""
    import history
    root = OUT / "historique"
    evs = history.from_result(res, imported)
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


def run_once():
    from playwright.sync_api import sync_playwright
    script = (HERE / "monitor.js").read_text(encoding="utf-8")
    prev = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    with sync_playwright() as p:
        ctx = launch(p, headless=True)
        try:
            load_cookies(ctx)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ensure_session(page)
            opts = {"maxSimultaneous": int(os.environ.get("PADEL_MAX_SIMULT", "2"))}
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
    export(res)
    archive(res, imported, prev)
    if res.get("ok"):
        log(f"OK : {res['activeCount']} réservations suivies, {res['created']} nouvelles, "
            f"{res['cancelled']} annulées, {len(res['alerts'])} cas suspects")
        for a in res["alerts"]:
            notify(f"Bot padel : cas {a['level']}",
                   f"{day(a['date'])} {a['slot']} : {' · '.join(a['before'])} → {' · '.join(a['after'])}")
    else:
        log(f"ÉCHEC {res.get('error')} : {res.get('message')}")
        if res.get("error") == "SESSION" and prev.get("error") != "SESSION":
            notify("Bot padel : session ADOC expirée",
                   "Lancez « python padel_bot.py --login » et reconnectez-vous à ADOC.")
    STATUS.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "ok": res.get("ok"),
                                  "error": res.get("error")}), encoding="utf-8")
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
    print("Session enregistrée, le bot peut tourner." if ok else
          "Je ne vois pas de session ADOC ouverte : relancez et terminez bien la connexion.")
    log("Connexion manuelle : " + ("OK" if ok else "échec"))


if __name__ == "__main__":
    try:
        if "--login" in sys.argv:
            login()
        elif "--verifier" in sys.argv:
            sys.exit(verify_history())
        else:
            sys.exit(run_once())
    except SystemExit:
        raise
    except Exception:
        log("ERREUR\n" + traceback.format_exc())
        sys.exit(1)
