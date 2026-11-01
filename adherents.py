"""Adhérents padel de la saison : copie locale de l'export ADOC (nom, prénom, téléphones, offres) et recherche rapide.

- rafraichir() : recherche ADOC « année d'adhésion la plus récente + offres padel », puis export Excel, sans navigateur
  (requêtes HTTP avec les cookies du bot, ~30 s côté serveur ADOC). Lancé par cron (padel_bot.py --adherents).
- chercher(termes) : recherche instantanée dans la copie locale (prénom, nom, téléphone, éventuellement partiels).

La copie (DATA/adherents.json, lisible par le seul utilisateur) contient des données personnelles : elle n'est jamais
écrite dans resultats/ (publié), ni dans bot.log, ni sur GitHub.
"""
import json, os, re, unicodedata, urllib.parse, urllib.request
from datetime import datetime

import padel_bot as b

FILE = b.DATA / "adherents.json"
LISTE = b.ADOC + "membreListe.do"

# Offres padel indiquées par le club (libellés ADOC, comparés sans accents ni casse).
OFFRES_CLUB = ["Adhésion Tennis et Padel à l'année adulte", "Adhésion Padel à l'année adulte",
               "Adhésion Padel à l'année adulte double résa", "Adhésion Tennis et Padel junior 7-18 ans",
               "Adhésion Padel junior 7-18 ans", "Cours padel adulte année", "Cours padel junior année",
               "Accès padel EDT 50€", "Cours padel avec offre tennis 75 €"]
# Autres offres retenues : celles dont le libellé parle de padel, sauf les invitations (qui accompagnent une autre offre).
PADEL = re.compile(r"padel|pad'elle", re.I)
EXCLUES = re.compile(r"invitation", re.I)
COL_OFFRES = ("Adhésion", "Enseignement (Cours)", "Enseignement (Stage)")
COL_TELS = ("Téléphone Portable", "2eme Téléphone portable", "Téléphone Domicile Principal",
            "2eme Téléphone Domicile", "Téléphone Bureau")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]", " ", s)).strip()


def chiffres(tel):
    """Numéro réduit à ses chiffres significatifs : 06 81…, +33 6 81…, 0033 6 81… donnent tous 681…"""
    d = re.sub(r"\D", "", str(tel))
    if d.startswith("0033"):
        d = d[4:]
    elif d.startswith("33") and len(d) == 11:
        d = d[2:]
    return d.lstrip("0")


class SessionPerdue(Exception):
    pass


def _ouvrir(op, url, data=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data, headers or {})
    with op.open(req, timeout=timeout) as r:
        if not r.geturl().startswith(b.ADOC):
            raise SessionPerdue(r.geturl())
        return r.read()


def _dwr(op, jar, service, methode, *params):
    """Appel DWR en texte brut (le jeton anti-CSRF de DWR est le cookie DWRSESSIONID)."""
    ssid = next((c.value for c in jar if c.name == "DWRSESSIONID"), "")
    lignes = ["callCount=1", "nextReverseAjaxIndex=0", f"c0-scriptName={service}", f"c0-methodName={methode}", "c0-id=0"]
    lignes += [f"c0-param{i}={p}" for i, p in enumerate(params)]
    lignes += ["batchId=0", "instanceId=0", "page=" + urllib.parse.quote("/adoc/membreListe.do?method=read", safe=""),
               f"scriptSessionId={ssid}/{os.urandom(6).hex()}"]
    txt = _ouvrir(op, f"{b.ADOC}dwr/call/plaincall/{service}.{methode}.dwr", ("\n".join(lignes) + "\n").encode(),
                  {"Content-Type": "text/plain"}, 60).decode("utf-8", "replace")
    if "handleCallback" not in txt:
        raise RuntimeError(f"DWR {methode} : réponse inattendue")
    return txt


def _offres(op, jar, id_annee):
    txt = _dwr(op, jar, "TableRefService", "getListeFormule", f"string:{id_annee}", "null:null")
    txt = re.sub(r"\\u([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), txt)
    toutes = [(i, l.strip()) for i, l in re.findall(r'idFormule:(\d+),intitule:"((?:[^"\\]|\\.)*)"', txt)]
    club = {norm(x) for x in OFFRES_CLUB}
    return [(i, l, norm(l) in club) for i, l in toutes if norm(l) in club or (PADEL.search(l) and not EXCLUES.search(l))]


def _lire_export(contenu, offres_club):
    import xlrd
    sh = xlrd.open_workbook(file_contents=contenu).sheet_by_name("Détaillé")
    hdr = {str(sh.cell_value(1, j)).strip(): j for j in range(sh.ncols)}
    for col in ("Nom", "Prénom", "Téléphone Portable", "Adhésion"):
        if col not in hdr:
            raise RuntimeError(f"export ADOC : colonne « {col} » introuvable")
    club = [norm(x) for x in offres_club]
    membres = []
    for i in range(2, sh.nrows):
        nom, prenom = str(sh.cell_value(i, hdr["Nom"])).strip(), str(sh.cell_value(i, hdr["Prénom"])).strip()
        if not nom or not prenom:          # pied de page « Export du … »
            continue
        offres = []
        for col in COL_OFFRES:
            if col in hdr:
                offres += [o.strip() for o in str(sh.cell_value(i, hdr[col])).split(",") if o.strip()]
        tels = []
        for col in COL_TELS:
            t = str(sh.cell_value(i, hdr[col])).strip() if col in hdr else ""
            if t.endswith(".0"):
                t = t[:-2]
            if t and t not in tels:
                tels.append(t)
        membres.append({"nom": nom, "prenom": prenom, "tels": tels, "offres": offres,
                        "club": any(norm(o).startswith(c) for o in offres for c in club)})
    return membres


def rafraichir():
    """Télécharge la liste des adhérents padel de la saison. Renvoie 0 (OK), 2 (session perdue) ou 1 (erreur)."""
    o = b.adoc_opener()
    if not o:
        b.log("Liste des adhérents : pas de session ADOC enregistrée")
        return 2
    op, jar, _ = o
    try:
        page = _ouvrir(op, LISTE + "?method=read", timeout=60).decode("utf-8", "replace")
        if not re.search(r'href="[^"]*logout', page):
            raise SessionPerdue("accueil")
        sel = re.search(r'name="idAnneeAdhesion".*?</select>', page, re.S)
        annees = [(i, int(a)) for i, a in re.findall(r'value="(\d+)"[^>]*>\s*\{?(\d{4})\}?\s*<', sel.group(0) if sel else "")]
        if not annees:
            raise RuntimeError("années d'adhésion introuvables")
        id_annee, saison = max(annees, key=lambda x: x[1])
        offres = _offres(op, jar, id_annee)
        if not offres:
            raise RuntimeError(f"aucune offre padel pour {saison}")
        form = [("method", "list"), ("saisieNiveauxM11", "0"), ("mode", "R"), ("typeCommunication", ""),
                ("codeTypeLicencePresence", "false"), ("avecEmail", "off"), ("chefDeFamille", "off"), ("lieuLicence", "CA"),
                ("codeTypePratique", "TENNIS"), ("uniquementClassementND", "off"), ("idAnneeAdhesion", id_annee),
                ("nouveauxAdherents", "off"), ("paiementEnAttente", "off"), ("buttonRechercher", "Rechercher")]
        form += [("listeFormuleSelected", i) for i, _, _ in offres]
        res = _ouvrir(op, LISTE, urllib.parse.urlencode(form).encode()).decode("utf-8", "replace")
        m = re.search(r"(\d+) éléments trouvés|(Un) élément trouvé", res)
        attendu = int(m.group(1)) if m and m.group(1) else (1 if m else 0)
        xls = _ouvrir(op, LISTE, urllib.parse.urlencode([("method", "exportAdherent"), ("saisieNiveauxM11", "false"),
                                                          ("mode", "R"), ("typeCommunication", "")]).encode(), timeout=180)
        if xls[:4] != b"\xd0\xcf\x11\xe0":
            raise RuntimeError("l'export ADOC n'est pas un fichier Excel")
        membres = _lire_export(xls, [l for _, l, c in offres if c])
    except SessionPerdue:
        b.log("Liste des adhérents : session ADOC non connectée")
        return 2
    except Exception as e:
        b.log(f"Liste des adhérents : échec ({type(e).__name__}: {e})")
        return 1
    if attendu and len(membres) != attendu:
        b.log(f"Liste des adhérents : {len(membres)} lus pour {attendu} annoncés par ADOC")
    data = {"at": datetime.now(b.PARIS).isoformat(), "saison": saison,
            "offres": [{"id": i, "libelle": l, "club": c} for i, l, c in offres], "membres": membres}
    tmp = FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, FILE)
    os.chmod(FILE, 0o600)
    b.log(f"Liste des adhérents padel {saison} : {len(membres)} adhérents, {len(offres)} offres")   # aucun nom
    return 0


def charger():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _proche(w, ident):
    from difflib import SequenceMatcher
    return w in ident or any(SequenceMatcher(None, w, x).ratio() >= 0.8 for x in ident.split())


def chercher(termes, data=None, approx=False):
    """Membres dont chaque terme correspond : un mot à une partie du nom ou du prénom, un numéro (4 chiffres ou plus)
    à une partie d'un téléphone. Renvoie la liste triée, les correspondances exactes de prénom/nom en premier.
    approx=True tolère une faute de frappe dans les noms (Philipe → Philippe)."""
    data = data or charger() or {"membres": []}
    texte, nums = " ".join(termes), []
    for t in re.findall(r"\+?\d[\d\s.\-()]*\d", texte):     # « +33 6 81 27 09 20 » même sans guillemets
        d = re.sub(r"\D", "", t)
        if len(d) >= 4:
            nums.append(chiffres(t) if len(d) >= 9 else d.lstrip("0") or d)
            texte = texte.replace(t, " ")
    mots = norm(texte).split()
    out = []
    for m in data["membres"]:
        nom, pre = norm(m["nom"]), norm(m["prenom"])
        ident = f"{nom} {pre}"
        if not all((_proche(w, ident) if approx else w in ident) for w in mots):
            continue
        tels = [chiffres(t) for t in m["tels"]]
        if not all(any(n in t for t in tels) for n in nums):
            continue
        exact = sum(w in (nom.split() + pre.split()) for w in mots)
        out.append((-exact, m["nom"], m["prenom"], m))
    return [m for *_, m in sorted(out, key=lambda x: (x[0], norm(x[1]), norm(x[2])))]
