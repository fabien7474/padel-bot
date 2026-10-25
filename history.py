"""Historique permanent des événements (pour justifier avertissements et sanctions).

- Un fichier par année : historique/padel-evenements-AAAA.jsonl, une ligne JSON par événement, jamais réécrite.
- Chaînage SHA-256 : chaque ligne contient l'empreinte de la ligne précédente ; toute modification ou suppression
  d'une ligne casse la chaîne et se voit avec `python padel_bot.py --verifier`.
- Événements : reservation_creee, reservation_annulee, joueurs_modifies, cas_suspect, passage (échecs uniquement).
- Conservation : PADEL_HISTORY_YEARS années (3 par défaut), à fixer par le bureau et à inscrire au registre RGPD.
"""
import csv, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _last_hash(path):
    if not path.exists():
        return GENESIS
    last = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last = line
    return json.loads(last)["hash"] if last else GENESIS


def _year_file(root, year):
    return root / f"padel-evenements-{year}.jsonl"


def append(root: Path, events):
    """Ajoute des événements (dicts avec au moins 'type' et 'at') à l'historique, en chaînant les empreintes."""
    if not events:
        return 0
    root.mkdir(parents=True, exist_ok=True)
    n = 0
    for ev in sorted(events, key=lambda e: e["at"]):
        path = _year_file(root, ev["at"][:4])
        prev = _last_hash(path)
        rec = {**ev, "prev": prev}
        rec["hash"] = hashlib.sha256((prev + _canon({k: v for k, v in rec.items() if k != "hash"})).encode()).hexdigest()
        with open(path, "a", encoding="utf-8") as f:
            f.write(_canon(rec) + "\n")
        n += 1
    return n


def verify(root: Path):
    """Vérifie la chaîne de chaque fichier annuel. Renvoie une liste de (fichier, nb_lignes, ok, détail)."""
    out = []
    for path in sorted(root.glob("padel-evenements-*.jsonl")):
        prev, ok, detail, n = GENESIS, True, "intact", 0
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                n += 1
                rec = json.loads(line)
                h = hashlib.sha256((prev + _canon({k: v for k, v in rec.items() if k != "hash"})).encode()).hexdigest()
                if rec.get("prev") != prev or rec.get("hash") != h:
                    ok, detail = False, f"rupture à la ligne {i}"
                    break
                prev = rec["hash"]
        out.append((path.name, n, ok, detail))
    return out


def read_all(root: Path):
    evs = []
    for path in sorted(root.glob("padel-evenements-*.jsonl")):
        with open(path, encoding="utf-8") as f:
            evs += [json.loads(l) for l in f if l.strip()]
    return evs


def purge(root: Path, years: int, log):
    """Supprime les fichiers annuels au-delà de la durée de conservation."""
    limit = datetime.now(timezone.utc).year - years
    for path in root.glob("padel-evenements-*.jsonl"):
        try:
            if int(path.stem.rsplit("-", 1)[1]) < limit:
                path.unlink()
                log(f"Historique {path.name} supprimé (conservation {years} ans)")
        except (ValueError, OSError):
            pass


def from_result(res, imported=None):
    """Transforme le résultat d'un passage (et un éventuel import) en événements d'historique."""
    at = res.get("run") or datetime.now(timezone.utc).isoformat()
    ev = res.get("events") or {}
    out = []
    for r in ev.get("created", []):
        out.append({"type": "reservation_creee", "at": r.get("firstSeen") or at, "reservation": r})
    for c in ev.get("cancelled", []):
        out.append({"type": "reservation_annulee", "at": c.get("detected") or at, "reservation": c,
                    "constat": f"vue au passage du {c.get('lastSeen')}, absente au passage du {c.get('detected')}"})
    for m in ev.get("modified", []):
        out.append({"type": "joueurs_modifies", "at": m.get("detected") or at, "modification": m})
    for a in ev.get("alerts", []):
        out.append({"type": "cas_suspect", "at": a.get("detected") or at, "cas": a})
    if not res.get("ok"):
        out.append({"type": "passage_en_echec", "at": at, "erreur": res.get("error"), "message": res.get("message")})
    if imported:
        src = imported.get("source", "import")
        for c in imported.get("cancelled", []):
            out.append({"type": "reservation_annulee", "at": c["detected"], "reservation": c, "source": src})
        for a in imported.get("alerts", []):
            out.append({"type": "cas_suspect", "at": a["detected"], "cas": a, "source": src})
    return out


def bootstrap(res):
    """Premier lancement : reprend dans l'historique les cas et annulations déjà connus du bot (vue glissante)."""
    sp = lambda x: [p for p in (x or "").split(" · ") if p]
    out = []
    for r in res.get("rows") or []:
        if r["kind"] == "alert":
            st, _, en = r["slot"].partition("-")
            out.append({"type": "cas_suspect", "at": r["detected"], "source": "reprise de l'état existant",
                        "cas": {"key": r["key"], "level": r["level"], "score": r["score"], "date": r["date"], "start": st, "end": en,
                                "reasons": r["reasons"].split(" ; "), "removed": sp(r["removed"]), "added": sp(r["added"]),
                                "before": {"court": r["beforeCourt"], "players": sp(r["beforePlayers"])},
                                "after": {"court": r["afterCourt"], "players": sp(r["afterPlayers"])}}})
        elif r["kind"] == "cancel":
            st, _, en = r["slot"].partition("-")
            out.append({"type": "reservation_annulee", "at": r["detected"], "source": "reprise de l'état existant",
                        "reservation": {"id": r["id"], "date": r["date"], "start": st, "end": en, "court": r["court"],
                                        "players": sp(r["players"]), "early": r["early"], "firstSeen": r["firstSeen"],
                                        "detected": r["detected"], "hoursBeforeSlot": r["hoursBeforeSlot"]}})
    return out


def write_cumulative_csv(root: Path, out: Path, fmt_dt, fmt_day, write_csv):
    """Régénère les CSV cumulés (tout l'historique conservé) à partir des fichiers annuels."""
    evs = read_all(root)
    alerts = [e for e in evs if e["type"] == "cas_suspect"]
    cancels = [e for e in evs if e["type"] == "reservation_annulee"]
    write_csv("padel-historique-cas-suspects.csv",
              ["Détecté le", "Niveau", "Score", "Date du créneau", "Horaire", "Piste avant", "Joueurs avant",
               "Piste après", "Joueurs après", "Retirés", "Ajoutés", "Motifs", "Source", "Empreinte"],
              [[fmt_dt(e["at"]), e["cas"].get("level"), e["cas"].get("score"), fmt_day(e["cas"].get("date")),
                f'{e["cas"].get("start")}-{e["cas"].get("end")}', (e["cas"]["before"].get("court") or "") + (" (ticket)" if e["cas"]["before"].get("ticket") else ""),
                " · ".join(e["cas"]["before"].get("players", [])), (e["cas"]["after"].get("court") or "") + (" (ticket)" if e["cas"]["after"].get("ticket") else ""),
                " · ".join(e["cas"]["after"].get("players", [])), " · ".join(e["cas"].get("removed", [])),
                " · ".join(e["cas"].get("added", [])), " ; ".join(e["cas"].get("reasons", [])),
                e.get("source", "bot local"), e["hash"][:12]] for e in reversed(alerts)])
    write_csv("padel-historique-annulations.csv",
              ["Détectée le", "Date du créneau", "Horaire", "Piste", "Joueurs", "Réservée dès J-7",
               "Heures avant le créneau", "Constat", "Id ADOC", "Source", "Empreinte"],
              [[fmt_dt(e["at"]), fmt_day(e["reservation"].get("date")),
                f'{e["reservation"].get("start")}-{e["reservation"].get("end")}', e["reservation"].get("court"),
                " · ".join(e["reservation"].get("players", [])), "oui" if e["reservation"].get("early") else "non",
                str(e["reservation"].get("hoursBeforeSlot", "")).replace(".", ","), e.get("constat", ""),
                e["reservation"].get("id"), e.get("source", "bot local"), e["hash"][:12]] for e in reversed(cancels)])
    return len(alerts), len(cancels)
