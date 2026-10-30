"""Rapport HTML autonome (un seul fichier, aucune ressource externe) généré à chaque passage."""
from datetime import datetime, timezone, timedelta
from html import escape


def _dt(iso, tz):
    if not iso:
        return ""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (d.astimezone(tz) if tz else d.astimezone()).strftime("%d/%m %H:%M")


def _day(ymd):
    jours = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
    d = datetime.strptime(ymd, "%Y-%m-%d")
    return f"{jours[d.weekday()]} {d:%d/%m}"


def _table(headers, rows, empty, cls=""):
    if not rows:
        return f'<p class="empty">{escape(empty)}</p>'
    th = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _players(ps):
    out = []
    for p in ps:
        g = p.strip().lower().startswith("invit") or p.strip().endswith("*")
        out.append(f'<span class="{"guest" if g else "pl"}">{escape(p)}</span>')
    return " ".join(out)


def build(res, alerts, cancels, runs, resas, tz, status=None):
    now = datetime.now(timezone.utc)
    week = now - timedelta(days=7)
    recent = lambda iso: datetime.fromisoformat(iso.replace("Z", "+00:00")) > week
    a7 = [a for a in alerts if recent(a["detected"])]
    c7 = [c for c in cancels if recent(c["detected"])]
    last = runs[0] if runs else None
    ok = bool(res.get("ok"))
    n_guest = sum(1 for r in resas if any(p.strip().lower().startswith("invit") or p.strip().endswith("*") for p in r["players"]))

    if not ok:
        msg = ("La session ADOC a expiré : reconnectez le bot (<b>connexion-adoc.cmd</b> sous Windows, "
               "<b>padel_bot.py --login</b> sur le bureau du Beelink).<br><small>Le bot ne surveille plus rien tant que ce n'est pas fait.</small>"
               if res.get("error") == "SESSION" else f"Dernier passage en échec : {escape(str(res.get('message')))}")
        banner = f'<p class="banner bad">{msg}</p>'
    elif a7:
        banner = f'<p class="banner warn">{len(a7)} cas suspect{"s" if len(a7) > 1 else ""} sur les 7 derniers jours, à examiner ci-dessous.</p>'
    else:
        banner = '<p class="banner good">Aucun cas suspect sur les 7 derniers jours.</p>'

    lvl = {"élevé": "hi", "moyen": "mid", "faible": "lo"}
    alert_rows = [[f'<span class="lvl {lvl.get(a["level"], "lo")}">{escape(a["level"])}</span>',
                   f'{_day(a["date"])} {escape(a["slot"])}',
                   f'<small>{escape(a["beforeCourt"])}</small><br>{_players(a["beforePlayers"].split(" · "))}',
                   f'<small>{escape(a["afterCourt"])}</small><br>{_players(a["afterPlayers"].split(" · "))}',
                   escape(a["reasons"]).replace(" ; ", "<br>"), _dt(a["detected"], tz)] for a in alerts]
    cancel_rows = [[f'{_day(c["date"])} {escape(c["slot"])}', escape(c["court"]), _players(c["players"].split(" · ")),
                    "oui" if c["early"] else "", f'{c["hoursBeforeSlot"]:.0f} h'.replace(".", ","), _dt(c["detected"], tz)]
                   for c in cancels]
    resa_rows = [[_day(r["date"]), f'{escape(r["start"])}–{escape(r["end"])}', escape(r["court"]), _players(r["players"]),
                  "ticket" if r.get("ticket") else "", "dès J-7" if r.get("early") else ""] for r in resas]
    run_rows = [[_dt(r["at"], tz), "OK" if r.get("ok") else f'<span class="ko">Échec {escape(r.get("error", ""))}</span>',
                 str(r.get("active", "")), str(r.get("created", "")), str(r.get("cancelled", "")), str(r.get("alerts", ""))]
                for r in runs[:48]]

    tiles = [("Cas suspects · 7 j", len(a7), "hi" if a7 else ""), ("Annulations · 7 j", len(c7), ""),
             ("Réservations suivies", len(resas) if ok else "—", ""), ("Avec invités/externes", n_guest if ok else "—", "")]
    tiles_html = "".join(f'<div class="tile"><div class="k">{escape(k)}</div><div class="v {c}">{v}</div></div>' for k, v, c in tiles)
    gen = _dt(now.isoformat(), tz)
    status_html = _status(status, res, len(a7), len(alerts), tz) if status else ""
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300">
<title>Rapport padel</title>
<style>
:root{{--bg:#f7f7f5;--panel:#fff;--fg:#1d1d1b;--mut:#6b6b66;--line:#e4e3de;--hi:#c0362c;--mid:#b26a00;--good:#2e7d32;--guest:#7a4fb3}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1b1b1a;--panel:#252523;--fg:#ecebe6;--mut:#a3a29c;--line:#3a3936;--hi:#ff7a6e;--mid:#f0b45a;--good:#7cc87f;--guest:#c3a3ef}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px 16px 48px}}h1{{font:400 28px/1.2 Georgia,serif;margin:0 0 4px}}
.sub{{color:var(--mut);margin:0 0 16px}}h2{{font-size:17px;margin:0 0 4px}}.note{{color:var(--mut);font-size:13px;margin:0 0 12px}}
.banner{{padding:10px 14px;border-radius:8px;border:1px solid var(--line);background:var(--panel)}}.banner.bad{{border-color:var(--hi);color:var(--hi)}}
.banner.warn{{border-color:var(--mid);color:var(--mid)}}.banner.good{{color:var(--good)}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr));gap:12px;margin:16px 0}}
.tile,.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
.k{{color:var(--mut);font-size:13px}}.v{{font:400 30px/1.2 Georgia,serif;font-variant-numeric:tabular-nums;margin-top:4px}}.v.hi{{color:var(--hi)}}
.card{{margin-top:16px}}.scroll{{overflow:auto;max-height:520px}}table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th{{text-align:left;color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:6px 8px;white-space:nowrap}}
td{{border-bottom:1px solid var(--line);padding:6px 8px;vertical-align:top;font-variant-numeric:tabular-nums}}
.guest{{color:var(--guest);font-style:italic}}.pl,.guest{{white-space:nowrap}}.pl:not(:last-child)::after,.guest:not(:last-child)::after{{content:" ·";color:var(--mut);font-style:normal}}
.lvl{{font-weight:700}}.lvl.hi{{color:var(--hi)}}.lvl.mid{{color:var(--mid)}}.lvl.lo{{color:var(--mut)}}.ko{{color:var(--hi)}}
.empty{{color:var(--mut);font-size:13px}}
.st{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr));gap:4px 20px;margin:8px 0 0}}
.st div{{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line);padding:5px 0;font-size:13.5px}}
.st dt{{color:var(--mut)}}.st dd{{margin:0;text-align:right;font-variant-numeric:tabular-nums}}
.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;background:var(--good)}}.dot.bad{{background:var(--hi)}}.dot.warn{{background:var(--mid)}}
.okc{{color:var(--good)}}a{{color:inherit}}small{{color:var(--mut)}}footer{{color:var(--mut);font-size:12px;margin-top:24px}}
</style></head><body><main>
<h1>Surveillance padel</h1><p class="sub">Annecy Tennis · réservations « Joueur » des pistes de padel, J à J+7 · mis à jour le {gen}</p>
<p class="banner bad" id="stale" hidden></p>
{banner}{status_html}<section class="tiles">{tiles_html}</section>
<section class="card"><h2>Cas suspects</h2><p class="note">Annulation puis re-réservation du même créneau avec un joueur en commun, ou joueurs remplacés. À vérifier avant toute décision. 90 derniers jours.</p>
{_table(["Niveau", "Créneau", "Avant", "Après", "Motifs", "Détecté"], alert_rows, "Aucun cas suspect détecté.")}</section>
<section class="card"><h2>Annulations</h2><p class="note">Réservations disparues avant l'heure du créneau, 14 derniers jours.</p>
{_table(["Créneau", "Piste", "Joueurs", "Dès J-7", "Avant le créneau", "Détectée"], cancel_rows, "Aucune annulation détectée.")}</section>
<section class="card"><h2>Réservations en cours</h2><p class="note">Invités et externes en <span class="guest">italique</span>. « dès J-7 » : vue dès l'ouverture de la fenêtre de réservation.</p>
{_table(["Jour", "Horaire", "Piste", "Joueurs", "", ""], resa_rows, "Aucune réservation (ou dernier passage en échec).")}</section>
<section class="card"><h2>Passages du bot</h2>
{_table(["Heure", "État", "Suivies", "Nouvelles", "Annulées", "Suspects"], run_rows, "Aucun passage enregistré.")}</section>
<footer>Document interne du bureau – contient des noms d'adhérents, ne pas diffuser.</footer>
</main>{_script(status) if status else ""}</body></html>"""


def _status(st, res, n7, n90, tz):
    state = st.get("state")
    label = {"actif": ("", "Actif"), "session": ("bad", "Arrêté : session ADOC expirée"),
             "echec": ("bad", "Dernier passage en échec")}.get(state, ("warn", state or "?"))
    hist = (f'<span class="okc">intact</span> · {st["historyEvents"]} événements' if st.get("historyIntact")
            else '<span class="ko">ALTÉRÉ</span> (lancer --verifier)')
    fiches = (f'{st["details"]} lues' if st.get("dwr") else '<span class="ko">indisponibles</span>') if state == "actif" else "—"
    items = [("État", f'<span class="dot {label[0]}" id="dot"></span><span id="state">{escape(label[1])}</span>'),
             ("Dernier passage", _dt(st["lastRun"], tz)),
             ("Dernier passage réussi", _dt(st.get("lastOk"), tz) or "jamais"),
             ("Prochain passage prévu", _dt(st["nextRun"], tz)),
             ("Fréquence", f'toutes les {st["intervalMin"]} min' + (f', pause {escape(st["pause"])}' if st.get("pause") else "")),
             ("Cas suspects", f'{n7} sur 7 j · {n90} sur 90 j'),
             ("Fiches détaillées", fiches),
             ("Historique permanent", hist),
             ("Machine", escape(st.get("host") or "")),
             ("Version", escape(st.get("version") or ""))]
    dl = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in items)
    return (f'<section class="card"><h2>État du bot</h2><dl class="st">{dl}</dl>'
            f'<p class="note" style="margin:10px 0 0"><a href="bot-log.txt">Journal technique</a> (mis à jour toutes les 10 min, '
            f'plus récent en haut)</p></section>')


def _script(st):
    """Signale à l'ouverture de la page que le bot ne tourne plus (rapport figé) ; la page se recharge toutes les 5 min."""
    import json
    data = json.dumps({"stale": st["staleAfter"], "last": st["lastRun"], "pause": st.get("pause") or ""})
    return """<script>(function(){var s=%s;function paris(){var p=new Intl.DateTimeFormat('fr-FR',{timeZone:'Europe/Paris',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date());return p}
function inPause(){if(!/^\\d\\d:\\d\\d-\\d\\d:\\d\\d$/.test(s.pause))return false;var t=paris(),a=s.pause.slice(0,5),b=s.pause.slice(6);return a<=b?(t>=a&&t<b):(t>=a||t<b)}
var now=Date.now(),last=new Date(s.last),ago=Math.round((now-last)/60000),txt=ago<120?ago+' min':Math.round(ago/60)+' h';
if(now>new Date(s.stale).getTime()){var e=document.getElementById('stale');e.hidden=false;e.innerHTML='Le bot ne tourne plus : aucun passage depuis '+txt+'. Vérifier que le Beelink est allumé (et la tâche cron).';
document.getElementById('dot').className='dot bad';document.getElementById('state').textContent='Arrêté ? (rapport figé depuis '+txt+')'}
else if(inPause()&&document.getElementById('state').textContent==='Actif'){document.getElementById('dot').className='dot warn';document.getElementById('state').textContent='En pause nocturne ('+s.pause+')'}})();</script>""" % data
