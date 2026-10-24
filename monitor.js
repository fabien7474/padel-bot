async () => {
  const VERSION = '1.0';
  const KEY = 'annecyPadelMonitor.v1';
  const DAYS_AHEAD = 7;            // fenêtre de réservation du club
  const EARLY_LEAD_DAYS = 6.5;     // vue pour la 1re fois à ≥ 6,5 j du créneau = réservée dès l'ouverture
  const MATCH_WINDOW_H = 4;        // écart max entre annulation et nouvelle réservation
  const KEEP_CANCELLED_DAYS = 14;
  const now = new Date();
  const nowIso = now.toISOString();

  // ---------- helpers ----------
  const pad = n => String(n).padStart(2, '0');
  const frDate = d => `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
  const isoDate = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const slotStart = r => new Date(`${r.date}T${r.start}:00`);
  const slotEnd = r => new Date(`${r.date}T${r.end}:00`);
  const norm = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\*/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  const isGuest = name => /^invit/i.test(name.trim());
  const isExternal = name => /\*$/.test(name.trim());
  const members = r => r.players.filter(p => !isGuest(p) && !isExternal(p));
  const hoursBetween = (a, b) => Math.abs(new Date(a) - new Date(b)) / 36e5;

  // ---------- état et journal ----------
  let state;
  try { state = JSON.parse(localStorage.getItem(KEY)) || null; } catch { state = null; }
  const baseline = !state;
  if (!state) state = { created: nowIso, lastRun: null, active: {}, cancelled: [], removedCounts: {}, alertKeys: [] };
  state.runs = state.runs || []; state.alertsLog = state.alertsLog || [];
  const DAY = 864e5;
  const exportRows = () => {
    const keep = (iso, days) => Date.now() - new Date(iso) < days * DAY;
    state.runs = state.runs.filter(r => keep(r.at, 7));
    state.cancelled = state.cancelled.filter(c => keep(c.detected, KEEP_CANCELLED_DAYS));
    state.alertsLog = state.alertsLog.filter(a => keep(a.detected, 90));
    state.alertKeys = state.alertKeys.slice(-500);
    localStorage.setItem(KEY, JSON.stringify(state));
    const g = ps => ps.filter(p => isGuest(p) || isExternal(p)).length;
    return [
      ...state.runs.map(r => ({ kind: 'run', ...r })),
      ...state.cancelled.map(c => ({ kind: 'cancel', id: c.id, date: c.date, slot: `${c.start}-${c.end}`, court: c.court,
        players: c.players.join(' · '), guests: g(c.players), early: !!c.early, firstSeen: c.firstSeen, detected: c.detected, hoursBeforeSlot: c.hoursBeforeSlot })),
      ...state.alertsLog.map(a => ({ kind: 'alert', key: a.key, detected: a.detected, date: a.date, slot: `${a.start}-${a.end}`, level: a.level, score: a.score,
        beforeCourt: a.before.court, beforePlayers: a.before.players.join(' · '), afterCourt: a.after.court, afterPlayers: a.after.players.join(' · '),
        removed: a.removed.join(' · '), added: a.added.join(' · '), reasons: a.reasons.join(' ; ') }))
    ];
  };
  const fail = (error, message) => {
    if (!baseline) { state.runs.push({ at: nowIso, ok: false, error, message }); }
    return { ok: false, version: VERSION, error, message, rows: baseline ? [] : exportRows() };
  };

  // ---------- session ----------
  if (!document.querySelector('a[href*="logout"]')) return fail('SESSION', "Session ADOC non connectée.");

  // ---------- scrape ----------
  async function fetchDay(d) {
    const body = new URLSearchParams({
      method: 'search', reservationRecurrente: '', option: '', dateDebut: frDate(d), idCourt: '',
      dateFin: frDate(d), typeReservation: 'JOUEUR', texteRecherche: '', buttonRechercher: 'Rechercher'
    });
    const res = await fetch('/adoc/suiviReservations.do', { method: 'POST', body, credentials: 'include' });
    if (!res.ok) throw new Error(`HTTP ${res.status} pour le ${frDate(d)}`);
    const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
    if (/session a expir/i.test(doc.body.textContent)) throw Object.assign(new Error('SESSION'), { session: true });
    const banner = (doc.body.textContent.match(/(\d+)\s+éléments? trouvés?/) || [])[1];
    const out = [];
    for (const tr of doc.querySelectorAll('table tbody tr')) {
      const cb = tr.querySelector('input[name="tab"]');
      const btn = tr.querySelector('fft-edit-button');
      const tds = tr.querySelectorAll('td');
      if (!cb || tds.length < 7) continue;
      const court = tds[3].textContent.trim();
      if (!/^padel/i.test(court)) continue;
      const [start, end] = tds[2].textContent.trim().split(/\s*-\s*/);
      const players = [...tds[4].querySelectorAll('p')].map(p => p.textContent.trim()).filter(Boolean);
      out.push({
        id: (btn && btn.getAttribute('resa-id-ponctuelle')) || cb.value.split('@@')[1],
        date: (btn && btn.getAttribute('resa-date')) || isoDate(d),
        start, end, court, players,
        ticket: cb.getAttribute('data-ticket-reservation') === 'true'
      });
    }
    const allRows = doc.querySelectorAll('table tbody tr input[name="tab"]').length;
    if (banner && Number(banner) > allRows) throw new Error(`Résultats tronqués le ${frDate(d)} (${allRows}/${banner})`);
    return out;
  }

  const days = [];
  for (let i = 0; i <= DAYS_AHEAD; i++) { const d = new Date(now); d.setHours(12, 0, 0, 0); d.setDate(d.getDate() + i); days.push(d); }
  const scraped = {};
  try {
    for (const d of days) for (const r of await fetchDay(d)) scraped[r.id] = r;
  } catch (e) {
    return fail(e.session ? 'SESSION' : 'SCRAPE', e.session ? "Session ADOC expirée pendant la lecture." : String(e.message || e));
  }
  const firstDay = isoDate(days[0]), lastDay = isoDate(days[days.length - 1]);
  const prevRun = state.lastRun;

  const created = [], cancelled = [], modified = [], alerts = [];

  // nouvelles réservations et modifications
  for (const r of Object.values(scraped)) {
    const old = state.active[r.id];
    if (!old) {
      const lead = (slotStart(r) - now) / 864e5;
      const rec = { ...r, firstSeen: nowIso, lastSeen: nowIso, leadDays: Math.round(lead * 100) / 100, early: !baseline && lead >= EARLY_LEAD_DAYS, baseline };
      state.active[r.id] = rec;
      if (!baseline) created.push(rec);
    } else {
      const before = old.players.map(norm).sort().join('|'), after = r.players.map(norm).sort().join('|');
      if (before !== after || old.court !== r.court || old.start !== r.start) {
        modified.push({ id: r.id, date: r.date, start: r.start, end: r.end, court: r.court, oldCourt: old.court, before: old.players, after: r.players, early: old.early, detected: nowIso });
      }
      Object.assign(old, r, { lastSeen: nowIso });
    }
  }

  // annulations (disparues avant l'heure du créneau) et créneaux joués
  for (const [id, r] of Object.entries(state.active)) {
    if (scraped[id]) continue;
    if (r.date < firstDay || r.date > lastDay) { if (slotEnd(r) < now) delete state.active[id]; continue; }
    delete state.active[id];
    if (slotStart(r) > now) {
      const c = { ...r, cancelledAfter: r.lastSeen, detected: nowIso, hoursBeforeSlot: Math.round((slotStart(r) - now) / 36e5 * 10) / 10 };
      cancelled.push(c);
      state.cancelled.push(c);
    }
  }

  // ---------- détection des substitutions ----------
  const overlap = (a, b) => a.date === b.date && slotStart(a) < slotEnd(b) && slotStart(b) < slotEnd(a);
  const newRecent = Object.values(state.active).filter(r => !r.baseline && hoursBetween(r.firstSeen, nowIso) <= MATCH_WINDOW_H);
  const cancRecent = state.cancelled.filter(c => hoursBetween(c.detected, nowIso) <= MATCH_WINDOW_H);
  for (const c of cancRecent) {
    for (const n of newRecent) {
      if (!overlap(c, n)) continue;
      const cm = new Set(members(c).map(norm)), nm = new Set(members(n).map(norm));
      const common = [...cm].filter(x => nm.has(x));
      if (!common.length) continue;
      const cAll = c.players.map(norm).sort().join('|'), nAll = n.players.map(norm).sort().join('|');
      if (cAll === nAll) continue;
      if (hoursBetween(c.cancelledAfter, n.firstSeen) > MATCH_WINDOW_H + 1) continue;
      const key = `${c.id}>${n.id}`;
      if (state.alertKeys.includes(key)) continue;
      const removed = c.players.filter(p => !n.players.map(norm).includes(norm(p)));
      const added = n.players.filter(p => !c.players.map(norm).includes(norm(p)));
      const guestsBefore = c.players.filter(p => isGuest(p) || isExternal(p)).length;
      let score = 3; const reasons = ['Annulation puis re-réservation du même créneau avec un joueur commun'];
      if (c.early) { score += 2; reasons.push('Réservation initiale faite dès l\'ouverture (J-7)'); }
      if (!n.early) { score += 1; reasons.push('Nouvelle réservation faite après l\'ouverture'); }
      if (guestsBefore) { score += 2; reasons.push(`${guestsBefore} invité(s)/externe(s) dans la réservation initiale`); }
      for (const p of removed) {
        if (isGuest(p)) continue;
        const k = norm(p); state.removedCounts[k] = (state.removedCounts[k] || 0) + 1;
        if (state.removedCounts[k] >= 2) { score += 1; reasons.push(`${p} déjà retiré ${state.removedCounts[k]} fois`); }
      }
      state.alertKeys.push(key);
      alerts.push({
        key, score, level: score >= 7 ? 'élevé' : score >= 5 ? 'moyen' : 'faible', reasons,
        date: c.date, start: c.start, end: c.end,
        before: { id: c.id, court: c.court, players: c.players, firstSeen: c.firstSeen, early: c.early, cancelledBetween: [c.cancelledAfter, c.detected] },
        after: { id: n.id, court: n.court, players: n.players, firstSeen: n.firstSeen, early: n.early },
        common: c.players.filter(p => common.includes(norm(p))), removed, added, detected: nowIso
      });
    }
  }
  // modification directe des joueurs sur une réservation faite dès l'ouverture
  for (const m of modified) {
    const removed = m.before.filter(p => !m.after.map(norm).includes(norm(p)));
    if (!removed.length) continue;
    const key = `mod:${m.id}:${m.after.map(norm).sort().join('|')}`;
    if (state.alertKeys.includes(key)) continue;
    let score = 3; const reasons = ['Joueurs modifiés sur une réservation existante'];
    if (m.early) { score += 2; reasons.push('Réservation faite dès l\'ouverture (J-7)'); }
    if (removed.some(p => isGuest(p) || isExternal(p))) { score += 2; reasons.push('Invité(s)/externe(s) remplacé(s)'); }
    state.alertKeys.push(key);
    alerts.push({ key, score, level: score >= 7 ? 'élevé' : score >= 5 ? 'moyen' : 'faible', reasons, date: m.date, start: m.start, end: m.end,
      before: { id: m.id, court: m.oldCourt, players: m.before, early: m.early }, after: { id: m.id, court: m.court, players: m.after },
      common: m.after.filter(p => m.before.map(norm).includes(norm(p))), removed, added: m.after.filter(p => !m.before.map(norm).includes(norm(p))), detected: nowIso });
  }

  // ---------- sauvegarde et résumé ----------
  state.lastRun = nowIso;
  state.alertsLog.push(...alerts);
  state.runs.push({ at: nowIso, ok: true, active: Object.keys(scraped).length, created: created.length, cancelled: cancelled.length, alerts: alerts.length, baseline });
  const rows = exportRows();
  return {
    ok: true, version: VERSION, run: nowIso, previousRun: prevRun, baseline,
    range: [firstDay, lastDay], activeCount: Object.keys(scraped).length,
    created: created.length, cancelled: cancelled.length, modified: modified.length,
    alerts: alerts.map(a => ({ level: a.level, score: a.score, date: a.date, slot: `${a.start}-${a.end}`, before: a.before.players, after: a.after.players, reasons: a.reasons })),
    rows,
    reservations: Object.values(state.active).sort((a, b) => (a.date + a.start + a.court).localeCompare(b.date + b.start + b.court))
      .map(r => ({ id: r.id, date: r.date, start: r.start, end: r.end, court: r.court, players: r.players, ticket: !!r.ticket, firstSeen: r.firstSeen, early: !!r.early, baseline: !!r.baseline }))
  };
}
