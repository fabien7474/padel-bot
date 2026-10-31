"""Disponibilités des pistes de padel, lues en direct dans le « Tableau de réservation » d'ADOC.

Utilise la session du bot (cookies de session.json) dans un navigateur headless séparé : le profil du bot n'est
pas touché. Seuls le court, l'heure et le type d'occupation sortent de la page : aucun nom, aucun e-mail.
"""
import asyncio, json, re, time
from datetime import date as Date, datetime, timedelta

import padel_bot as bot

PADEL = {49643: "Padel 1", 49739: "Padel 2", 59856: "Padel 3", 59857: "Padel 4", 59859: "Padel 5"}
TABLEAU_URL = bot.ADOC + "tableauReservation.do?method=load"
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


class SessionExpiree(Exception):
    pass


# Exécuté dans la page ADOC : appelle le service du tableau pour chaque piste et ne renvoie que des horaires et des types.
_JS = """async ([day, ids]) => {
  const call = id => new Promise((res, rej) => ReservationTableauxService.getTableauReservation(day, id,
      {callback: res, errorHandler: m => rej(new Error(String(m))), timeout: 20000}));
  const out = {};
  for (const id of ids) {
    const t = await call(id) || {};
    out[id] = {
      interruption: !!t.interruption,
      grid: (t.creneaux || []).map(c => [c.heureDebut, c.heureFin, c.increment]),
      occ: (t.reservations || []).map(r => ({d: r.debut, f: r.fin, type: r.type,
        club: r.libelleTypeReservationClub || null,
        cours: !!(r.enseignants && r.enseignants.length), externe: !!r.identifiantPersonneMorale}))
    };
  }
  return out;
}"""

_cache, _lock = {}, asyncio.Lock()


def _min(hhmm):
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def _hh(minutes):
    return f"{minutes // 60}h{minutes % 60:02d}"


def _label(o):
    if o["cours"]:
        return "cours"
    if o["externe"]:
        return "réservation externe"
    if o["type"] in ("PONC_CLUB", "PERM_CLUB"):
        return o["club"].lower() if o.get("club") else "réservation du club"
    if o["type"] == "MRT":
        return "réservé en ligne"
    return "réservé"


def parse_date(txt, today=None):
    """AAAA-MM-JJ, JJ/MM(/AAAA), « aujourd'hui », « demain », « après-demain » ou un jour de la semaine (le prochain)."""
    today = today or datetime.now(bot.PARIS).date()
    t = (txt or "").strip().lower()
    if not t or t in ("aujourd'hui", "aujourdhui", "ce jour"):
        return today
    if t == "demain":
        return today + timedelta(days=1)
    if t in ("après-demain", "apres-demain", "après demain"):
        return today + timedelta(days=2)
    for i, j in enumerate(JOURS):
        if t.startswith(j) or t.startswith("ce " + j):
            return today + timedelta(days=(i - today.weekday()) % 7)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        return Date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?", t)
    if m:
        y = int(m[3]) if m[3] else today.year
        d = Date(y + 2000 if y < 100 else y, int(m[2]), int(m[1]))
        return d if m[3] or d >= today - timedelta(days=1) else Date(d.year + 1, d.month, d.day)
    raise ValueError(f"Date non comprise : « {txt} » (exemples : 2026-11-04, 04/11, mercredi, demain)")


def parse_heure(txt):
    m = re.fullmatch(r"\s*(\d{1,2})\s*(?:[h:]\s*(\d{2})?)?\s*", (txt or "").lower())
    if not m:
        raise ValueError(f"Heure non comprise : « {txt} » (exemples : 18h45, 18:45, 18h)")
    return int(m[1]) * 60 + int(m[2] or 0)


async def _fetch(day):
    from playwright.async_api import async_playwright
    if not bot.COOKIES.exists():
        raise SessionExpiree()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, ignore_default_args=["--enable-automation"],
                                          args=["--disable-blink-features=AutomationControlled"])
        try:
            ctx = await browser.new_context(locale="fr-FR", timezone_id="Europe/Paris")
            await ctx.add_cookies(json.loads(bot.COOKIES.read_text(encoding="utf-8")))
            page = await ctx.new_page()
            await page.goto(TABLEAU_URL, wait_until="domcontentloaded")
            if not await page.locator('a[href*="logout"]').count():
                raise SessionExpiree()
            await page.wait_for_function("typeof ReservationTableauxService !== 'undefined'", timeout=20000)
            return await page.evaluate(_JS, [day.isoformat(), list(PADEL)])
        finally:
            await browser.close()


async def tableau(day):
    """{piste: {"slots": [(début_min, fin_min, None|libellé)], "ferme": bool}} pour un jour (cache 60 s)."""
    async with _lock:
        hit = _cache.get(day)
        if hit and time.time() - hit[0] < 60:
            raw = hit[1]
        else:
            raw = await _fetch(day)
            _cache[day] = (time.time(), raw)
    out = {}
    for cid, name in PADEL.items():
        t = raw.get(str(cid)) or raw.get(cid) or {}
        occ = [(_min(o["d"]), _min(o["f"]), _label(o)) for o in t.get("occ", [])]
        slots = []
        for d, f, inc in t.get("grid", []):
            s, e = _min(d), _min(f)
            while inc and s + inc <= e:
                busy = next((lab for a, b, lab in occ if a < s + inc and b > s), None)
                slots.append((s, s + inc, busy))
                s += inc
        out[name] = {"slots": slots, "ferme": bool(t.get("interruption"))}
    return out


def jour_fr(day):
    return f"{JOURS[day.weekday()]} {day.day} {MOIS[day.month - 1]}"


async def reponse(date_txt="", heure_txt=""):
    """Texte court, adapté à une réponse orale."""
    day = parse_date(date_txt)
    try:
        tab = await tableau(day)
    except SessionExpiree:
        return ("Je ne peux pas lire ADOC : la session du bot a expiré. "
                "Il faut reconnecter le bot (raccourci « Reconnecter le bot ADOC » sur le Beelink).")
    titre = jour_fr(day)
    if not any(v["slots"] for v in tab.values()):
        return f"Aucun créneau de padel trouvé pour {titre} (hors période de réservation ?)."
    if heure_txt:
        h = parse_heure(heure_txt)
        libres, occupes, debut = [], [], None
        for name, v in tab.items():
            slot = next((s for s in v["slots"] if s[0] <= h < s[1]), None)
            if v["ferme"]:
                occupes.append(f"{name} (fermé)")
            elif not slot:
                occupes.append(f"{name} (hors horaires)")
            elif slot[2]:
                occupes.append(f"{name} ({slot[2]})")
            else:
                libres.append(name)
            debut = debut or slot
        when = f"{titre}, créneau de {_hh(debut[0])} à {_hh(debut[1])}" if debut else f"{titre} à {_hh(h)}"
        txt = f"{when} : " + ("toutes les pistes de padel sont libres." if len(libres) == len(PADEL) else
                              f"libres : {', '.join(libres)}." if libres else "aucune piste de padel libre.")
        if occupes:
            txt += f" Occupées : {', '.join(occupes)}."
        if not libres:   # propose les créneaux libres les plus proches
            prox = {}
            for name, v in tab.items():
                for s, e, busy in v["slots"]:
                    if not busy and not v["ferme"]:
                        prox.setdefault(s, []).append(name)
            near = sorted(prox, key=lambda s: abs(s - h))[:3]
            if near:
                txt += " Créneaux libres les plus proches : " + " ; ".join(
                    f"{_hh(s)} ({', '.join(prox[s])})" for s in sorted(near)) + "."
        return txt
    par_heure = {}
    for name, v in tab.items():
        for s, e, busy in v["slots"]:
            if not busy and not v["ferme"]:
                par_heure.setdefault(s, []).append(name)
    now = datetime.now(bot.PARIS)
    if day == now.date():
        par_heure = {s: v for s, v in par_heure.items() if s + 75 > now.hour * 60 + now.minute}
    if not par_heure:
        return f"{titre} : plus aucune piste de padel libre."
    fmt = lambda v: "toutes les pistes" if len(v) == len(PADEL) else ", ".join(v)
    return f"{titre}, créneaux libres : " + " ; ".join(f"{_hh(s)} : {fmt(v)}" for s, v in sorted(par_heure.items())) + "."


if __name__ == "__main__":
    import sys
    print(asyncio.run(reponse(*(sys.argv[1:3]))))
