"use strict";
/* Fonctionnalités : conseiller, fiche équipe, scores en direct, évolution des cotes,
   meilleures stratégies de mise, taux de réussite par niveau de confiance.
   (utilise les utilitaires définis dans app.js, uniquement à l'exécution) */

const ordinal = (n) => (n === 1 ? "1er" : n + "e");

/* ================================================================== liens équipes */
function teamLink(id, name) {
  return id ? `<a class="teamlink" href="#" data-team="${esc(id)}" title="Voir la fiche de ${esc(name)}">${esc(name)}</a>` : esc(name);
}
document.addEventListener("click", (e) => {
  const a = e.target.closest("a.teamlink");
  if (!a) return;
  e.preventDefault();
  e.stopPropagation();
  openTeam(a.dataset.team);
}, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeTeam(); });

/* ================================================================== fiche équipe */
let TEAM = null;
const TEAM_SORT = { key: "minutes", dir: -1 };
function closeTeam() { const m = document.getElementById("team-modal"); if (m) m.remove(); }

async function openTeam(id) {
  closeTeam();
  const back = document.createElement("div");
  back.className = "modal-back";
  back.id = "team-modal";
  back.innerHTML = `<div class="modal" role="dialog" aria-modal="true"><button class="btn close" title="Fermer (Échap)">✕</button><p class="muted">Chargement…</p></div>`;
  back.addEventListener("click", (e) => { if (e.target === back || e.target.closest(".close")) closeTeam(); });
  document.getElementById("app").appendChild(back);
  TEAM = await api(`/api/team/${id}`);
  renderTeam();
}

function renderTeam() {
  const t = TEAM, box = document.querySelector("#team-modal .modal");
  if (!box || !t) return;
  const st = t.standing, r = t.ratings || {};
  const wdl = (x) => x ? `${x.w} V · ${x.d} N · ${x.l} D` : "–";
  const split = (x) => x ? `<td class="num r">${x.n}</td><td class="num r">${wdl(x)}</td><td class="num r">${x.gf}-${x.ga}</td><td class="num r">${num(x.ppg)}</td><td class="num r">${num(x.xgf)}</td><td class="num r">${num(x.xga)}</td>` : `<td colspan="6" class="muted">–</td>`;
  const tot = t.home && t.away ? { w: t.home.w + t.away.w, d: t.home.d + t.away.d, l: t.home.l + t.away.l } : null;
  const PKEYS = { name: (p) => p.name.toLowerCase(), position: (p) => POS_ORDER[p.position] ?? 9, minutes: (p) => p.minutes || 0, goals: (p) => p.goals || 0,
    xg: (p) => p.xg || 0, assists: (p) => p.assists || 0, xa: (p) => p.xa || 0, rating: (p) => p.rating ?? -1 };
  const players = sortRows(t.players, TEAM_SORT, PKEYS);
  const ph = (k, l, cls = "r", tp = "") => `<th class="${cls} sortable" data-psort="${k}">${l}${TEAM_SORT.key === k ? `<span class="sort-ind">${TEAM_SORT.dir > 0 ? "▲" : "▼"}</span>` : ""}${tp ? tip(tp) : ""}</th>`;
  const cal = t.calendar || {};
  box.innerHTML = `<button class="btn close" title="Fermer (Échap)">✕</button>
    <div class="lbl">${esc(t.league_name)} · fiche équipe</div>
    <h2 class="team-title">${esc(t.name)}</h2>
    <div class="kpis" style="margin-top:14px">
      <div class="card pad kpi"><div class="lbl">Classement</div><div class="v">${st.pos ? ordinal(st.pos) : "–"}</div><div class="sub">sur ${st.n_teams} · ${st.pts ?? 0} pts en ${st.played ?? 0} matchs</div></div>
      <div class="card pad kpi"><div class="lbl">Bilan</div><div class="v" style="font-size:22px">${tot ? `${tot.w}-${tot.d}-${tot.l}` : "–"}</div><div class="sub">victoires-nuls-défaites · diff. ${st.gd > 0 ? "+" : ""}${st.gd ?? 0}</div></div>
      <div class="card pad kpi"><div class="lbl">Force (cotes)${tip("mratings")}</div><div class="v">${r.odds_rank ? ordinal(r.odds_rank) : "–"}</div><div class="sub">attaque ${num(r.odds?.att)} · défense ${num(r.odds?.def)}</div></div>
      <div class="card pad kpi"><div class="lbl">Force (xG)${tip("poisson")}</div><div class="v" style="font-size:22px">${num(r.xg?.att)} / ${num(r.xg?.def)}</div><div class="sub">attaque / défense (1 = moyenne)</div></div>
      <div class="card pad kpi"><div class="lbl">Forme · 10 matchs${tip("formVsExp")}</div><div class="v" style="font-size:22px">${t.form?.vs_expected != null ? (t.form.vs_expected > 0 ? "+" : "") + num(t.form.vs_expected) + " pt" : "–"}</div>
        <div class="sub">${t.form ? `<span class="formdots">${t.form.seq.split("").map((l) => `<span class="f${l}">${l}</span>`).join("")}</span>` : ""}</div></div>
    </div>
    <div class="cols">
      <div class="card pad"><h3 class="big">Domicile / extérieur</h3><div class="scroll-x"><table class="tbl"><tr><th></th><th class="r">Matchs</th><th class="r">Bilan</th><th class="r">Buts</th><th class="r">Pts/match</th><th class="r">xG pour${tip("xg")}</th><th class="r">xG contre</th></tr>
        <tr><td>Domicile</td>${split(t.home)}</tr><tr><td>Extérieur</td>${split(t.away)}</tr></table></div>
        ${r.xg ? `<div class="note">Force à domicile${tip("homeadv")} : marque ×${num(r.xg.home_att)} et encaisse ×${num(r.xg.home_def)} par rapport à l'attendu.</div>` : ""}</div>
      ${ChartKit.card("t-xg", "xG match par match", [["line", "Lignes"], ["bar", "Barres"], ["diff", "Écart xG"]], { tipKey: "xg" })}
    </div>
    <div class="cols">
      <div class="card pad"><h3 class="big">Résultats de la saison</h3><div class="scroll-x"><table class="tbl"><tr><th>Date</th><th>Adversaire</th><th class="c">Score</th><th class="r">xG</th></tr>
        ${[...t.results].reverse().map((g) => { const res = g.gf > g.ga ? "V" : g.gf === g.ga ? "N" : "D";
          return `<tr><td class="num muted">${dateF.format(new Date(g.kickoff))}</td><td>${g.home ? "vs" : "à"} ${teamLink(g.opponent_id, g.opponent)}</td>
          <td class="num c"><span class="formdots" style="display:inline-flex;vertical-align:middle"><span class="f${res}">${res}</span></span> ${g.gf}-${g.ga}</td><td class="num r muted">${num(g.xgf, 1)} - ${num(g.xga, 1)}</td></tr>`; }).join("")}</table></div></div>
      <div class="card pad"><h3 class="big">À venir</h3><table class="tbl">
        ${[...t.upcoming.map((g) => ({ kickoff: g.kickoff, comp: "Championnat", label: `${g.home ? "vs" : "à"} ${esc(g.opponent)}` })),
           ...t.cups.filter((c) => !c.score).map((c) => ({ kickoff: c.kickoff, comp: c.comp, label: `vs ${esc(c.opponent)}` }))]
          .sort((a, b) => a.kickoff.localeCompare(b.kickoff)).slice(0, 8)
          .map((g) => `<tr><td class="num muted">${dtF.format(new Date(g.kickoff))}</td><td><span class="tag ${g.comp === "Championnat" ? "t-muted" : "t-home"}">${esc(g.comp)}</span></td><td>${g.label}</td></tr>`).join("") || `<tr><td class="muted">Aucun match programmé.</td></tr>`}
        </table>
        ${t.cups.some((c) => c.score) ? `<h4 class="lbl" style="margin-top:14px">Coupes &amp; Europe (joués)${tip("calendar")}</h4><table class="tbl">${t.cups.filter((c) => c.score).reverse().map((c) =>
          `<tr><td class="num muted">${dateF.format(new Date(c.kickoff))}</td><td>${esc(c.comp)}</td><td>vs ${esc(c.opponent)}</td><td class="num">${c.score}</td></tr>`).join("")}</table>` : ""}
        <h4 class="lbl" style="margin-top:14px">Blessés &amp; suspendus${tip("unavailable")}</h4>
        ${t.injuries.length ? `<table class="tbl">${t.injuries.map((u) => `<tr><td>${esc(u.name)}</td><td class="muted">${esc({ injury: "blessé", suspension: "suspendu" }[u.type] || u.type || "")}</td><td class="muted">${esc(u.expected_return || "")}</td></tr>`).join("")}</table>`
          : `<p class="muted" style="margin:0;font-size:13px">Aucun indisponible signalé.</p>`}
      </div>
    </div>
    <div class="card scroll-x" style="margin-bottom:var(--gap)"><div class="pad" style="padding:12px 14px 0"><h3 class="big" style="margin:0">Effectif <span class="muted" style="font-family:var(--body);font-size:12.5px;font-weight:400">· cliquez sur un en-tête pour trier</span></h3></div>
      <table class="tbl" style="min-width:760px"><tr>${ph("name", "Joueur", "")}${ph("position", "Poste", "")}${ph("minutes", "Minutes")}${ph("goals", "Buts")}${ph("xg", "xG", "r", "xg")}${ph("assists", "Passes déc.")}${ph("xa", "xA", "r", "xa")}${ph("rating", "Note", "r", "rating")}</tr>
      ${players.map((p) => `<tr><td style="font-weight:600">${esc(p.name)}</td><td class="lbl">${esc(p.position)}</td><td class="num r">${p.minutes}</td><td class="num r">${p.goals}</td>
        <td class="num r">${num(p.xg, 1)}</td><td class="num r">${p.assists}</td><td class="num r">${num(p.xa, 1)}</td><td class="num r">${p.rating ? num(p.rating, 1) : "–"}</td></tr>`).join("")}</table></div>
    <div class="card pad scroll-x"><h3 class="big">Classement ${esc(t.league_name)}</h3><table class="tbl"><tr><th class="r">#</th><th>Équipe</th><th class="r">J</th><th class="r">Diff.</th><th class="r">Pts</th></tr>
      ${t.table.map((x) => `<tr class="${x.team_id === t.id ? "me" : ""}"><td class="num r">${x.pos}</td><td>${teamLink(x.team_id, x.team)}</td><td class="num r">${x.played}</td><td class="num r">${x.gd > 0 ? "+" : ""}${x.gd}</td><td class="num r">${x.pts}</td></tr>`).join("")}</table></div>`;
  box.querySelectorAll("[data-psort]").forEach((h) => h.addEventListener("click", () => { toggleSort(TEAM_SORT, h.dataset.psort); renderTeam(); }));
  ChartKit.mount("t-xg", (type, c) => {
    const g = t.results;
    if (!g.length) return null;
    const lab = g.map((x) => shortF.format(new Date(x.kickoff)));
    if (type === "diff") return { type: "bar", data: { labels: lab, datasets: [{ label: "xG pour − contre", data: g.map((x) => (x.xgf || 0) - (x.xga || 0)), backgroundColor: g.map((x) => ((x.xgf || 0) >= (x.xga || 0) ? c.ok : c.ko)) }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { title: (it) => `${g[it[0].dataIndex].home ? "vs" : "à"} ${g[it[0].dataIndex].opponent} (${g[it[0].dataIndex].gf}-${g[it[0].dataIndex].ga})` } } } } };
    return { type: type === "bar" ? "bar" : "line", data: { labels: lab, datasets: [
      { label: "xG pour", data: g.map((x) => x.xgf), borderColor: c.home, backgroundColor: c.home, tension: .3 },
      { label: "xG contre", data: g.map((x) => x.xga), borderColor: c.away, backgroundColor: c.away, tension: .3 },
      { label: "Buts marqués", data: g.map((x) => x.gf), borderColor: c.ok, backgroundColor: c.ok, borderDash: [4, 3], tension: .3, hidden: type === "bar" }] },
      options: { plugins: { tooltip: { callbacks: { title: (it) => `${g[it[0].dataIndex].home ? "vs" : "à"} ${g[it[0].dataIndex].opponent} (${g[it[0].dataIndex].gf}-${g[it[0].dataIndex].ga})` } } } } };
  });
}

/* ================================================================== scores en direct */
let LIVE = {};
async function pollLive() {
  try { LIVE = await api("/api/live"); } catch (e) { LIVE = {}; }
  applyLive();
}
function liveBadge(st) {
  if (!st || (!st.started && !st.finished)) return "";
  if (st.finished) return `<span class="live done">Terminé ${esc(st.score || "")}</span>`;
  return `<span class="live" title="Score en direct">${esc(st.minute || "en cours")} · ${esc(st.score || "")}</span>`;
}
function applyLive() {
  document.querySelectorAll(".mrow[data-id]").forEach((row) => {
    const st = LIVE[row.dataset.id];
    let el = row.querySelector(".live-slot");
    if (!el) { el = document.createElement("span"); el.className = "live-slot"; row.children[0].appendChild(el); }
    el.innerHTML = liveBadge(st);
  });
  const slot = document.getElementById("detail-live");
  if (slot) {
    const st = LIVE[slot.dataset.id];
    slot.innerHTML = st && st.started ? `<div class="live-big"><span class="score-big">${esc(st.score || "")}</span>${liveBadge(st)}</div>` : "";
  }
}
function startLive() {
  pollLive();
  setInterval(pollLive, 60000);
}

/* ================================================================== évolution des cotes */
function oddsHistoryCard(res) {
  const h = res.odds_history;
  if (!h || !Object.keys(h.series || {}).length) return "";
  const mv = h.move;
  const dl = (i) => mv ? `${mv.delta[i] > 0 ? "▲" : mv.delta[i] < 0 ? "▼" : "="} ${(mv.delta[i] * 100 >= 0 ? "+" : "") + (mv.delta[i] * 100).toFixed(1).replace(".", ",")} pts` : "";
  const note = mv ? `Depuis le ${dtF.format(new Date(mv.since))} (${mv.n_points} relevés) — probabilité implicite moyenne : 1 ${dl(0)} · N ${dl(1)} · 2 ${dl(2)}. Une probabilité qui monte = cote qui baisse (l'argent arrive sur cette issue).` : "";
  return ChartKit.card("d-odds", "Évolution des cotes", [["prob", "Probabilités"], ["odds", "Cotes"], ["books", "Par bookmaker"]], { tipKey: "oddsMove", note });
}
function mountOddsChart(res) {
  const h = res.odds_history, m = res.match;
  if (!h || !Object.keys(h.series || {}).length) return;
  ChartKit.mount("d-odds", (type, c) => {
    const books = Object.keys(h.series);
    const times = [...new Set(books.flatMap((b) => h.series[b].map((p) => p.ts)))].sort();
    if (times.length < 1) return null;
    const lab = times.map((t) => dtF.format(new Date(t)));
    // valeur de chaque bookmaker à chaque date (dernier relevé connu)
    const at = (b, k) => { let last = null, i = 0; const pts = h.series[b]; return times.map((t) => { while (i < pts.length && pts[i].ts <= t) last = pts[i++]; return last ? last[k] : null; }); };
    const implied = (b) => { const H = at(b, "h"), D = at(b, "d"), A = at(b, "a"); return H.map((_, j) => H[j] ? (() => { const s = 1 / H[j] + 1 / D[j] + 1 / A[j]; return [1 / H[j] / s, 1 / D[j] / s, 1 / A[j] / s]; })() : null); };
    const names = ["1 · " + m.home, "N · Nul", "2 · " + m.away], col = [c.home, c.draw, c.away];
    if (type === "books") {
      return { type: "line", data: { labels: lab, datasets: books.map((b, i) => ({ label: b.replace(" (direct)", ""), data: at(b, "h"), borderColor: c.series[i % 8], backgroundColor: c.series[i % 8], stepped: true, pointRadius: 2 })) },
        options: { plugins: { title: { display: true, text: `Cote « 1 » (${m.home}) chez chaque bookmaker`, color: c.muted } } } };
    }
    const imp = books.map(implied);
    const avg = (j) => times.map((_, t) => { const v = imp.map((x) => x[t]).filter(Boolean); return v.length ? v.reduce((s, x) => s + x[j], 0) / v.length : null; });
    if (type === "odds") return { type: "line", data: { labels: lab, datasets: [0, 1, 2].map((j) => ({ label: names[j], data: avg(j).map((p) => (p ? 1 / p : null)), borderColor: col[j], backgroundColor: col[j], stepped: true, pointRadius: 2 })) },
      options: { plugins: { title: { display: true, text: "Cote « juste » moyenne (marge retirée)", color: c.muted } } } };
    return { type: "line", data: { labels: lab, datasets: [0, 1, 2].map((j) => ({ label: names[j], data: avg(j).map((p) => (p ? p * 100 : null)), borderColor: col[j], backgroundColor: col[j], stepped: true, pointRadius: 2 })) },
      options: { scales: { y: { ticks: { callback: (v) => v + " %" } } } } };
  });
}

/* ================================================================== taux de réussite par confiance */
function tiersCard(tiers, id = "s-tiers") {
  if (!tiers || !tiers.length) return "";
  return `<div class="card pad"><h3 class="big">Réussite selon la confiance${tip("tiers")}</h3>
    <table class="tbl"><tr><th>Quand le favori est donné à…</th><th class="r">Matchs</th><th class="r">Part des matchs</th><th class="r">Favori gagnant</th></tr>
    ${tiers.map((t) => `<tr><td>${t.min ? "≥ " + Math.round(t.min * 100) + " %" : "tous les matchs"}</td><td class="num r">${t.n.toLocaleString("fr-FR")}</td><td class="num r">${pct(t.share)}</td><td class="num r" style="font-weight:700">${pct(t.accuracy, 1)}</td></tr>`).join("")}</table>
    <div class="note">Plus le modèle est confiant, plus il a raison : se limiter aux matchs où le favori dépasse 60 % fait passer la réussite d'environ 52 % à plus de 70 %, mais les cotes de ces favoris sont basses — la réussite ne garantit pas le gain.</div></div>`;
}

/* ================================================================== meilleures stratégies */
async function loadOptimizer() {
  const box = document.getElementById("opt-box");
  if (!box) return;
  box.innerHTML = `<p class="muted">Test de ~360 stratégies sur 8 saisons…</p>`;
  const o = await api("/api/bankroll/optimize");
  const y = (k) => (k.yield == null ? "–" : signed(k.yield, (x) => pct(x, 1)));
  box.innerHTML = `<p style="margin:0 0 12px;font-size:13.5px">${esc(o.verdict)}</p>
    <div class="scroll-x"><table class="tbl" style="min-width:980px"><tr><th>Stratégie</th>
      <th class="r">Paris (passé)</th><th class="r">Réussite</th><th class="r">Yield${tip("yield")}</th><th class="r">CLV${tip("clv")}</th><th class="r">Drawdown${tip("drawdown")}</th>
      <th class="r">Paris (vérif.)</th><th class="r">Yield (vérif.)</th><th></th></tr>
    ${o.strategies.map((s, i) => `<tr><td class="wrap" style="max-width:360px">${esc(s.label)}</td>
      <td class="num r">${s.train.n_settled}</td><td class="num r">${pct(s.train.hit_rate, 1)}</td><td class="num r" style="color:${s.train.yield > 0 ? "var(--ok)" : "var(--ko)"};font-weight:700">${y(s.train)}</td>
      <td class="num r" style="color:${s.train.clv > 0 ? "var(--ok)" : "var(--ko)"};font-weight:700">${s.train.clv == null ? "–" : signed(s.train.clv, (x) => pct(x, 2))}</td>
      <td class="num r">${pct(s.train.max_drawdown)}</td><td class="num r">${s.check.n_settled}</td>
      <td class="num r" style="color:${s.check.yield > 0 ? "var(--ok)" : s.check.yield < 0 ? "var(--ko)" : "inherit"}">${y(s.check)}</td>
      <td><button class="btn" data-apply="${i}" title="Utiliser cette stratégie pour le conseiller et la simulation">Appliquer</button></td></tr>`).join("")}</table></div>
    <div class="note">Passé = ${esc(o.train_period)} · vérification = ${esc(o.check_period)}. ${o.n_tested} stratégies testées et classées selon la CLV (capacité à obtenir une meilleure cote que la cote de clôture) : le rendement réel à attendre est proche de la CLV, pas du yield passé, qui contient une part de chance.${tip("optimizer")}</div>
    ${ChartKit.card("b-opt", "Courbes des meilleures stratégies (saison de référence)", [["line", "Courbes"]], { size: "short" })}`;
  box.querySelectorAll("[data-apply]").forEach((b) => b.addEventListener("click", async () => {
    const s = o.strategies[+b.dataset.apply];
    b.disabled = true;
    await api("/api/bankroll/apply", { method: "POST", body: JSON.stringify({ settings: s.settings, label: s.label }) });
    render();
  }));
  ChartKit.mount("b-opt", (type, c) => {
    const top = o.strategies.slice(0, 4);
    if (!top.length) return null;
    const n = Math.max(...top.map((s) => s.curve.length));
    return { type: "line", data: { labels: Array.from({ length: n }, (_, i) => i), datasets: top.map((s, i) => ({ label: s.label.slice(0, 48), data: s.curve.map((p) => p.bank), borderColor: c.series[i % 8], pointRadius: 0, tension: .1 })) },
      options: { scales: { x: { display: false } }, plugins: { legend: { position: "bottom" } } } };
  });
}

/* ================================================================== alertes */
let ALERTS = { alerts: [], unseen: 0 }, lastAlertId = null;
async function pollAlerts() {
  try { ALERTS = await api("/api/alerts"); } catch (e) { return; }
  const n = document.getElementById("bell-n");
  if (n) { n.textContent = ALERTS.unseen; n.parentElement.classList.toggle("primary", ALERTS.unseen > 0); }
  const top = ALERTS.alerts[0];
  if (top && lastAlertId !== null && top.id > lastAlertId && "Notification" in window && Notification.permission === "granted") {
    ALERTS.alerts.filter((a) => a.id > lastAlertId).slice(0, 3).forEach((a) => new Notification(a.title, { body: a.body }));
  }
  if (top) lastAlertId = top.id; else if (lastAlertId === null) lastAlertId = 0;
}
function renderBell() {
  const p = document.getElementById("bell-panel");
  const canNotify = "Notification" in window;
  p.innerHTML = `<div class="chart-head"><h3 style="margin:0">Alertes</h3>
      ${canNotify && Notification.permission !== "granted" ? `<button class="btn" id="notif-on">Activer les notifications</button>` : canNotify ? `<span class="lbl">notifications actives</span>` : ""}</div>
    ${ALERTS.alerts.length ? ALERTS.alerts.map((a) => `<div class="alert ${a.seen ? "" : "new"}" data-open="${a.match_id || ""}">
      <div class="lbl">${a.kind === "lineup" ? "Composition" : "Pari conseillé"} · ${dtF.format(new Date(a.created_at))}</div>
      <div style="font-weight:600">${esc(a.title)}</div><div class="muted" style="font-size:12.5px">${esc(a.body)}</div></div>`).join("")
      : `<p class="muted" style="font-size:13px">Aucune alerte pour l'instant. Vous serez prévenu quand une composition officielle tombe (environ 1 h avant le match) ou quand le conseiller recommande un pari.</p>`}
    <div class="note">${ALERTS.telegram ? "Envoi Telegram actif." : "Pour recevoir les alertes sur Telegram, voir le README (variables PROBAFOOT_TELEGRAM_TOKEN et PROBAFOOT_TELEGRAM_CHAT)."}</div>`;
  const b = document.getElementById("notif-on");
  if (b) b.addEventListener("click", async () => { await Notification.requestPermission(); renderBell(); });
  p.querySelectorAll("[data-open]").forEach((el) => el.addEventListener("click", () => { if (el.dataset.open) { S.sel = el.dataset.open; p.classList.add("hidden"); go("matches"); } }));
}
function startAlerts() {
  pollAlerts();
  setInterval(pollAlerts, 60000);
  document.getElementById("bell-btn").addEventListener("click", async () => {
    const p = document.getElementById("bell-panel");
    p.classList.toggle("hidden");
    if (!p.classList.contains("hidden")) {
      renderBell();
      if (ALERTS.unseen) { ALERTS = await api("/api/alerts/seen", { method: "POST" }); document.getElementById("bell-n").textContent = 0; document.getElementById("bell-btn").classList.remove("primary"); }
    }
  });
}

/* ================================================================== CONSEILLER */
async function viewAdvisor(v) {
  v.innerHTML = `<main class="page"><div class="head"><div class="kicker">Conseiller${tip("advisor")}</div>
    <h1 class="title">Que parier cette quinzaine ?</h1><div class="subtitle" id="adv-sub">Analyse des matchs à venir…</div></div>
    <div id="adv"><div class="card pad muted">Chargement…</div></div></main>`;
  const a = await api("/api/advisor");
  const tr = a.track, k = a.recommendations;
  $("#adv-sub").innerHTML = `Stratégie : <strong>${esc(a.strategy)}</strong> · <a href="#" id="adv-change">changer de stratégie</a>`;
  const yieldTxt = (x) => (x.yield == null ? "–" : signed(x.yield, (y) => pct(y, 1)));
  let h = `<div class="kpis">
    <div class="card pad kpi"><div class="lbl">Paris conseillés</div><div class="v">${k.length}</div><div class="sub">sur ${k.length + a.skips.length} matchs à venir</div></div>
    <div class="card pad kpi"><div class="lbl">Mise totale</div><div class="v">${eur(a.total_stake)}</div><div class="sub">${pct(a.bank ? a.total_stake / a.bank : 0, 1)} de la bankroll (${eur(a.bank)})</div></div>
    <div class="card pad kpi"><div class="lbl">Gain espéré${tip("edge")}</div><div class="v ${a.expected_profit > 0 ? "pos" : ""}">${signed(a.expected_profit, eur)}</div><div class="sub">moyenne si les probabilités sont justes</div></div>
    <div class="card pad kpi"><div class="lbl">Réussite des conseils${tip("advisorHit")}</div><div class="v">${pct(tr.backtest_prev.hit_rate, 1)}</div>
      <div class="sub">${tr.backtest_prev.n_settled} paris sur 7 saisons passées · yield ${yieldTxt(tr.backtest_prev)} · contre ${pct(tr.overall_accuracy, 0)} pour le pronostic sur tous les matchs</div></div>
    <div class="card pad kpi"><div class="lbl">Cote de clôture${tip("clv")}</div><div class="v ${tr.backtest_prev.clv > 0 ? "pos" : tr.backtest_prev.clv < 0 ? "neg" : ""}">${tr.backtest_prev.clv == null ? "–" : signed(tr.backtest_prev.clv, (x) => pct(x, 2))}</div>
      <div class="sub">CLV de cette stratégie sur le passé = rendement à attendre${tr.live.clv != null ? ` · en réel : ${signed(tr.live.clv, (x) => pct(x, 2))} (${tr.live.clv_n} paris)` : ""}</div></div>
    <div class="card pad kpi"><div class="lbl">Conseils réels${tip("autoBook")}</div><div class="v">${tr.live.n_settled ? pct(tr.live.hit_rate, 1) : "–"}</div>
      <div class="sub">${tr.live.n_settled ? `${tr.live.n_settled} paris réglés · yield ${yieldTxt(tr.live)}` : "aucun conseil réglé pour l'instant"}</div></div>
  </div>`;
  if (tr.backtest_prev.n_settled >= 30 && (tr.backtest_prev.yield < 0 || tr.backtest_prev.clv < 0)) {
    h += `<div class="warnbox">⚠ Sur 7 saisons, cette stratégie ${tr.backtest_prev.yield < 0 ? `perdait de l'argent (yield ${yieldTxt(tr.backtest_prev)})` : `a gagné (${yieldTxt(tr.backtest_prev)}) mais sans battre la cote de clôture (CLV ${signed(tr.backtest_prev.clv, (x) => pct(x, 2))}) : ses gains passés relèvent surtout de la chance`}.
      Allez dans <a href="#" data-go-opt>Bankroll → Meilleures stratégies</a> pour en appliquer une mieux classée, ou ne misez pas.</div>`;
  }
  if (tr.lineup_events) {
    h += `<div class="card pad" style="margin-bottom:var(--gap)"><h3 class="big">Test : parier juste après la composition officielle${tip("lineupBook")}</h3>
      <p style="margin:0;font-size:13.5px">${tr.lineup_events} composition(s) détectée(s) · ${tr.lineup.n_settled || 0} pari(s) de test réglé(s)${tr.lineup.clv != null ? ` · CLV moyenne <strong style="color:${tr.lineup.clv > 0 ? "var(--ok)" : "var(--ko)"}">${signed(tr.lineup.clv, (x) => pct(x, 2))}</strong> · yield ${yieldTxt(tr.lineup)}` : ""}.
      <span class="muted">Une CLV nettement positive sur 50 paris ou plus confirmerait que les bookmakers tardent à ajuster leurs cotes.</span></p></div>`;
  }
  if (k.length) {
    h += `<div class="recos">${k.map((r, i) => `<div class="card pad reco">
      <div class="lbl">${esc(r.match.league_name)} · ${cap(fullF.format(new Date(r.match.kickoff)))}${r.lineup_confirmed ? ` · <span class="t-home">compo officielle</span>` : ""}</div>
      <div style="font-weight:600;margin-top:4px">${teamLink(r.match.home_id, r.match.home)} – ${teamLink(r.match.away_id, r.match.away)}</div>
      <div class="sel">${esc(r.label)}</div>
      <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap"><span class="stake">${eur(r.stake)}</span>
        <span class="muted" style="font-size:13px">à la cote <strong class="num" style="color:var(--fg)">${num(r.odds)}</strong> chez ${esc(r.bookmaker.replace(" (direct)", ""))} · ${pct(r.stake_pct, 1)} de la bankroll</span></div>
      <div class="facts">
        <div>Proba modèle<strong>${pct(r.p, 1)}</strong></div><div>Proba cote<strong>${pct(1 / r.odds, 1)}</strong></div>
        <div>Avantage${tip("edge")}<strong style="color:var(--value)">${signed(r.edge, (x) => pct(x, 1))}</strong></div><div>Gain si gagné<strong>${signed(r.potential_win, eur)}</strong></div>
      </div>
      ${r.reasons.length ? `<ul>${r.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap"><button class="btn" data-bet="${i}" title="Ajouter ce pari à « Mes paris »">J'ai joué ce pari</button>
        <button class="btn soft" data-open="${r.match.id}">Voir le match</button></div>
    </div>`).join("")}</div>`;
  } else {
    h += `<div class="card nothing" style="margin-bottom:var(--gap)"><div class="big">Rien à parier pour l'instant</div>
      <p class="muted" style="margin:0">Aucun match ne présente un avantage suffisant selon la stratégie choisie. Ne rien faire est souvent la meilleure décision : les cotes seront revérifiées toutes les heures.</p></div>`;
  }
  h += `<div class="cols">
    <div class="card pad"><h3 class="big">Pronostics les plus sûrs${tip("tiers")}</h3>
      <p class="muted" style="margin:0 0 10px;font-size:12.5px">Issues les plus probables (pas forcément rentables à parier : les cotes des gros favoris sont basses).</p>
      <table class="tbl"><tr><th>Match</th><th>Pronostic</th><th class="r">Proba</th><th class="r">Réussite historique</th></tr>
      ${a.safest.map((s) => `<tr class="click" data-open="${s.match.id}"><td class="wrap"><span class="muted num" style="font-size:12px">${dtF.format(new Date(s.match.kickoff))}</span><br>${esc(s.match.home)} – ${esc(s.match.away)}</td>
        <td>${esc(s.label)}</td><td class="num r" style="font-weight:700">${pct(s.p)}</td><td class="num r">${s.tier_accuracy != null ? pct(s.tier_accuracy) + ` <span class="muted">(${s.tier_n})</span>` : "–"}</td></tr>`).join("")}</table></div>
    ${tiersCard(a.tiers, "a-tiers")}
  </div>
  <div class="card scroll-x"><div class="pad" style="padding:12px 14px 0"><h3 class="big" style="margin:0">À éviter (${a.skips.length})</h3></div>
    <table class="tbl" style="min-width:720px"><tr><th>Date</th><th>Match</th><th>Pourquoi ne pas parier</th></tr>
    ${a.skips.map((s) => `<tr class="click" data-open="${s.match.id}"><td class="num muted">${dtF.format(new Date(s.match.kickoff))}</td><td style="font-weight:600">${esc(s.match.home)} – ${esc(s.match.away)}</td><td class="wrap muted">${esc(s.reason)}</td></tr>`).join("")}</table></div>`;
  $("#adv").innerHTML = h;
  $("#adv-change").addEventListener("click", (e) => { e.preventDefault(); S.book = "auto"; go("bankroll"); });
  $$("#adv [data-go-opt]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); S.book = "auto"; go("bankroll"); setTimeout(loadOptimizer, 600); }));
  $$("#adv [data-open]").forEach((el) => el.addEventListener("click", (e) => { if (e.target.closest("a.teamlink")) return; S.sel = el.dataset.open; go("matches"); }));
  $$("#adv [data-bet]").forEach((b) => b.addEventListener("click", async () => {
    const r = k[+b.dataset.bet];
    const stake = prompt(`Mise réellement jouée sur « ${r.label} » (${r.match.home} – ${r.match.away}) ?`, r.stake);
    if (stake == null) return;
    const odds = prompt("Cote obtenue ?", r.odds);
    if (odds == null) return;
    await api("/api/bets", { method: "POST", body: JSON.stringify({ match_id: r.match.id, market: r.market, selection: r.selection, odds, stake, bookmaker: r.bookmaker.replace(" (direct)", "") }) });
    b.textContent = "✔ Enregistré dans « Mes paris »";
    b.disabled = true;
  }));
}
