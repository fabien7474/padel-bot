"""Bot de surveillance des réservations de padel - Annecy Tennis (ADOC).

Usage :
  python padel_bot.py --login   ouvre Edge pour vous connecter une fois à ADOC (à refaire si la session expire)
  python padel_bot.py           un passage (lancé toutes les 10 minutes par le Planificateur de tâches)

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
LOG = DATA / "bot.log"
STATUS = DATA / "statut.json"
ADOC = os.environ.get("PADEL_ADOC", "https://adoc.app.fft.fr/adoc/")
HOME_URL = ADOC + "accueil.do?method=read"
PARIS = ZoneInfo("Europe/Paris")


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
    return p.chromium.launch_persistent_context(str(PROFILE), channel=os.environ.get("PADEL_CHANNEL", "msedge" if os.name == "nt" else "") or None, headless=headless,
                                                locale="fr-FR", timezone_id="Europe/Paris")


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


def run_once():
    from playwright.sync_api import sync_playwright
    script = (HERE / "monitor.js").read_text(encoding="utf-8")
    prev = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    with sync_playwright() as p:
        ctx = launch(p, headless=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ensure_session(page)
            res = page.evaluate(script)  # le script vérifie lui-même la session et renvoie l'échec si besoin
        finally:
            ctx.close()
    export(res)
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


def login():
    from playwright.sync_api import sync_playwright
    print("Une fenêtre Edge va s'ouvrir : connectez-vous à ADOC avec le compte du club,")
    print("puis revenez ici et appuyez sur Entrée.")
    with sync_playwright() as p:
        ctx = launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(ADOC)
        input("\nConnecté ? Appuyez sur Entrée... ")
        page.goto(HOME_URL, wait_until="domcontentloaded")
        ok = logged_in(page)
        ctx.close()
    print("Session enregistrée, le bot peut tourner." if ok else
          "Je ne vois pas de session ADOC ouverte : relancez et terminez bien la connexion.")
    log("Connexion manuelle : " + ("OK" if ok else "échec"))


if __name__ == "__main__":
    try:
        login() if "--login" in sys.argv else run_once()
    except Exception:
        log("ERREUR\n" + traceback.format_exc())
        sys.exit(1)
