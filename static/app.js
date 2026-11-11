"use strict";

/* ================================================================== utilitaires */
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
};
const pct = (p, d = 0) => (p == null || isNaN(p) ? "–" : (p * 100).toFixed(d).replace(".", ",") + " %");
const num = (x, d = 2) => (x == null || isNaN(x) ? "–" : Number(x).toFixed(d).replace(".", ","));
const eur = (x) => (x == null ? "–" : Number(x).toLocaleString("fr-FR", { style: "currency", currency: "EUR" }));
const signed = (x, f) => (x == null ? "–" : (x > 0 ? "+" : "") + f(x));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const OUT = { H: "1", D: "N", A: "2", O: "+2.5", U: "−2.5" };
const LCODE = { EPL: "PL", La_liga: "LL", Bundesliga: "BL", Serie_A: "SA", Ligue_1: "L1" };
const dayF = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const timeF = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const dateF = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
const shortF = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });
const fullF = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
const dtF = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
const store = {
  get(k, d) { try { const v = localStorage.getItem("pf-" + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("pf-" + k, JSON.stringify(v)); } catch (e) { /* stockage indisponible */ } },
};

/* ================================================================== état */
const S = {
  tab: store.get("tab", "matches"), theme: store.get("theme", "dark"),
  league: "", week: "all", onlyValue: false, sel: null,
  sSource: "live", sLeague: "", hSource: "live", hLeague: "",
  calKind: "all", book: "auto", bdDim: "league", histPeriod: "all",
  squadSort: { key: "weight", dir: -1 }, betSort: { key: "kickoff", dir: -1 },
};
let META = null, MATCHES = { matches: [] }, DETAIL = null;
const TABS = [["matches", "Matchs"], ["advisor", "Conseiller"], ["calendar", "Calendrier"], ["bankroll", "Bankroll"], ["stats", "Performances"], ["history", "Historique"], ["glossary", "Lexique"]];

function setTheme(t) {
  S.theme = t; store.set("theme", t);
  $("#app").dataset.theme = t;
  $("#theme-btn").textContent = t === "dark" ? "◐ Clair" : "◐ Sombre";
  ChartKit.redrawAll();
}
$("#theme-btn").addEventListener("click", () => setTheme(S.theme === "dark" ? "light" : "dark"));

function renderTabs() {
  $("#tabs").innerHTML = TABS.map(([k, l]) => `<button class="tab ${S.tab === k ? "on" : ""}" data-tab="${k}">${l}</button>`).join("");
  $$("#tabs [data-tab]").forEach((b) => b.addEventListener("click", () => go(b.dataset.tab)));
}
function go(tab) { S.tab = tab; store.set("tab", tab); renderTabs(); render(); window.scrollTo(0, 0); }

const chips = (active, attr) => `<div class="chips">${[["", "Tous", "Tous les championnats"], ...Object.entries(META.leagues).map(([k, l]) => [k, l.name, `${l.name} (${l.country})`])]
  .map(([k, label, title]) => `<button class="chip ${active === k ? "on" : ""}" data-${attr}="${k}" title="${esc(title)}">${esc(label)}</button>`).join("")}</div>`;
const seg = (opts, active, attr, cls = "") => `<div class="seg ${cls}">${opts.map(([k, l]) => `<button class="${active === k ? "on" : ""}" data-${attr}="${k}">${l}</button>`).join("")}</div>`;
const bind = (attr, fn) => $$(`[data-${attr}]`).forEach((b) => b.addEventListener("click", () => fn(b.dataset[attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase())])));

/* ================================================================== tâches de fond */
const TASKNAME = { sync: "Synchronisation", backtest: "Backtest", learn: "Apprentissage" };
$$("[data-task]").forEach((b) => b.addEventListener("click", async () => {
  const r = await api(`/api/${b.dataset.task}`, { method: "POST" });
  if (!r.started) alert("Une tâche est déjà en cours.");
  pollStatus();
}));
let hideT = null, polling = false;
async function pollStatus() {
  polling = true;
  const s = await api("/api/status");
  const bar = $("#taskbar");
  $$("[data-task]").forEach((b) => (b.disabled = s.running));
  if (s.running) {
    clearTimeout(hideT);
    bar.className = "taskbar";
    bar.innerHTML = `<strong>${TASKNAME[s.name] || s.name}</strong><span class="txt">${esc(s.message)} (${Math.round(s.progress * 100)} %)</span>
      <span class="progress"><span style="width:${Math.round(s.progress * 100)}%"></span></span>`;
    $("#sync-dot").style.background = "var(--warn)";
    $("#sync-text").textContent = "Tâche en cours…";
    setTimeout(pollStatus, 1200);
    return;
  }
  polling = false;
  if (s.name) {
    bar.className = s.error ? "taskbar err" : "taskbar ok";
    bar.innerHTML = `<strong>${TASKNAME[s.name] || s.name}</strong><span class="txt">${s.error ? "Erreur : " + esc(s.error) : "Terminé : " + esc(summarize(s.result))}</span>`;
    hideT = setTimeout(() => bar.classList.add("hidden"), 10000);
    await loadMeta();
    await loadMatches();
    render();
  }
}
function summarize(r) {
  if (!r) return "";
  if (r.ok === false) return r.message;
  if (r.weights) return `log-loss ${num(r.logloss_before, 4)} → ${num(r.logloss_after, 4)} sur ${r.n} matchs, validation hors échantillon ${num(r.validation_before, 4)} → ${num(r.validation_after, 4)}`;
  if (r.predictions != null) return `${r.predictions} pronostics, ${r.odds} cotes, ${r.calendar} matchs de coupe/Europe, ${r.settled} paris réglés`;
  if (r.n != null) return `${r.n} matchs rejoués`;
  return JSON.stringify(r);
}

/* ================================================================== chargement */
async function loadMeta() {
  META = await api("/api/meta");
  $("#sync-dot").style.background = "var(--ok)";
  $("#sync-text").textContent = META.last_sync ? `Synchro ${dtF.format(new Date(META.last_sync))} · auto ${META.auto_sync_hours === 1 ? "toutes les heures" : `toutes les ${META.auto_sync_hours} h`}` : "Jamais synchronisé";
}
async function loadMatches() { MATCHES = await api("/api/matches"); }

function render() {
  const v = $("#view");
  ({ matches: viewMatches, advisor: viewAdvisor, calendar: viewCalendar, bankroll: viewBankroll, stats: viewStats, history: viewHistory, glossary: viewGlossary }[S.tab] || viewMatches)(v);
}

/* ================================================================== MATCHS */
function matchTags(m) {
  const p = m.prediction, t = [];
  if (m.result) {
    t.push(["t-fg", `${m.hg}-${m.ag}`]);
    if (p) t.push(p.correct ? ["t-ok", "✔ correct"] : ["t-ko", "✘ raté"]);
  }
  if (!p) return t;
  if (p.source === "backtest") t.push(["t-muted", "backtest"]);
  if (p.lineup_confirmed && !m.result) t.push(["t-home", "compo officielle"]);
  if (p.value.length) t.push(["t-value", "value " + p.value.map((v) => OUT[v.outcome]).join(",")]);
  const abs = (p.absents.home || 0) + (p.absents.away || 0);
  if (abs && !m.result) t.push(["t-warn", abs + (abs > 1 ? " absents" : " absent")]);
  if (p.derby) t.push(["t-fg", "derby"]);
  const mv = m.odds_move, pk = "HDA".indexOf(p.pick);
  if (mv && !m.result && Math.abs(mv[pk]) >= 0.02) t.push([mv[pk] > 0 ? "t-ok" : "t-ko", `cote ${OUT[p.pick]} ${mv[pk] > 0 ? "↘" : "↗"}`]);
  return t;
}

function viewMatches(v) {
  const mid = new Date(new Date(MATCHES.start).getTime() + 7 * 86400000);
  const all = MATCHES.matches;
  const list = all.filter((m) => {
    const d = new Date(m.kickoff);
    if (S.league && m.league !== S.league) return false;
    if (S.week === "0" && d >= mid) return false;
    if (S.week === "1" && d < mid) return false;
    if (S.onlyValue && !(m.prediction && m.prediction.value.length)) return false;
    return true;
  });
  const start = new Date(MATCHES.start), end = new Date(new Date(MATCHES.end).getTime() - 86400000);
  const nValue = all.filter((m) => m.prediction && m.prediction.value.length).length;
  const nPlayed = all.filter((m) => m.result).length;
  const nLineup = all.filter((m) => m.prediction && m.prediction.lineup_confirmed && !m.result).length;
  if (!S.sel || !all.some((m) => m.id === S.sel)) S.sel = (all.find((m) => !m.result) || all[0] || {}).id;

  const byDay = {};
  for (const m of list) (byDay[dayF.format(new Date(m.kickoff))] ||= []).push(m);
  v.innerHTML = `<main class="page">
    <div class="head">
      <div class="kicker">Semaine en cours + suivante · ${shortF.format(start)} – ${shortF.format(end)}</div>
      <h1 class="title">Les pronostics de la quinzaine</h1>
      <div class="subtitle">${all.length} matchs · 5 championnats · ${nValue} value bets${tip("value")} · ${nPlayed} ${nPlayed > 1 ? "matchs joués" : "match joué"}${nLineup ? ` · ${nLineup} compo(s) officielle(s)` : ""}</div>
    </div>
    <div class="filters">
      ${chips(S.league, "league")}
      ${seg([["all", "Semaine en cours + suivante"], ["0", "En cours"], ["1", "Suivante"]], S.week, "week")}
      <button class="valuebtn ${S.onlyValue ? "on" : ""}" id="value-toggle">Value bets uniquement</button>
    </div>
    <div class="split">
      <section class="list">
        ${!list.length ? `<div class="card pad muted">Aucun match pour cette sélection.${META.n_matches ? "" : " Lancez une synchronisation."}</div>` : ""}
        ${Object.entries(byDay).map(([day, ms]) => `<div class="card">
          <div class="day-head"><h2>${cap(day)}</h2><span class="lbl">${ms.length} ${ms.length > 1 ? "matchs" : "match"}</span></div>
          ${ms.map(matchRow).join("")}</div>`).join("")}
      </section>
      <aside class="card detail" id="detail"><div class="top muted">Sélectionnez un match.</div></aside>
    </div></main>`;
  bind("league", (k) => { S.league = k; render(); });
  bind("week", (k) => { S.week = k; render(); });
  $("#value-toggle").addEventListener("click", () => { S.onlyValue = !S.onlyValue; render(); });
  $$(".mrow").forEach((r) => r.addEventListener("click", () => {
    S.sel = r.dataset.id;
    $$(".mrow").forEach((x) => x.classList.toggle("sel", x === r));
    openMatch(S.sel);
    if (window.innerWidth < 1000) $("#detail").scrollIntoView({ behavior: "smooth" });
  }));
  if (S.sel) openMatch(S.sel);
  applyLive();
}

function matchRow(m) {
  const p = m.prediction;
  const tags = matchTags(m);
  const pick = p ? "HDA".indexOf(p.pick) : -1;
  return `<div class="mrow ${S.sel === m.id ? "sel" : ""} ${m.result ? "played" : ""}" data-id="${m.id}">
    <div style="display:flex;flex-direction:column;gap:2px"><span class="time">${timeF.format(new Date(m.kickoff))}</span><span class="code">${LCODE[m.league]}</span></div>
    <div style="min-width:0;display:flex;flex-direction:column;gap:1px">
      <span class="team ${pick === 0 ? "fav" : ""}">${esc(m.home)}</span>
      <span class="team ${pick === 2 ? "fav" : ""}">${esc(m.away)}</span>
      ${tags.length ? `<div class="tags">${tags.map(([c, t]) => `<span class="tag ${c}">${esc(t)}</span>`).join("")}</div>` : ""}
    </div>
    ${p ? `<div><div class="probs">${p.p.map((x, i) => `<span class="${i === pick ? "pick" : ""}">${pct(x)}</span>`).join("")}</div>
      <div class="minibar">${p.p.map((x) => `<span style="width:${x * 100}%"></span>`).join("")}</div></div>` : `<div class="muted" style="font-size:12px">Pas de pronostic</div>`}
  </div>`;
}

let openToken = 0;
async function openMatch(id) {
  const token = ++openToken;
  const el = $("#detail");
  if (!el) return;
  el.innerHTML = `<div class="top muted">Chargement…</div>`;
  const res = await api(`/api/match/${id}`);
  if (token !== openToken) return;
  DETAIL = res;
  renderDetail(res);
}

function renderDetail(res) {
  const el = $("#detail");
  if (!el) return;
  const { match: m, predictions } = res;
  const pred = predictions.live || predictions.backtest;
  const labels = res.labels;
  let h = `<div class="top">
    <div class="lbl">${esc(m.league_name)} · ${cap(fullF.format(new Date(m.kickoff)))}</div>
    <h2 class="match">${teamLink(m.home_id, m.home)} – ${teamLink(m.away_id, m.away)}</h2>
    <div id="detail-live" data-id="${m.id}"></div>`;
  if (!pred) { el.innerHTML = h + `<p class="muted">Aucun pronostic disponible pour ce match.</p></div>`; return; }
  const d = pred.data, det = d.details || {}, adj = d.adj || {};
  const mk = d.poisson ? d.poisson.markets : null;
  const res1 = m.result ? "HDA".indexOf(m.result) : null;
  if (m.result) {
    const ok = pred.pick === m.result;
    h += `<div style="display:flex;align-items:baseline;gap:10px;margin-top:6px;flex-wrap:wrap">
      <span class="score-big">${m.hg}-${m.ag}</span><span class="muted" style="font-size:13px">Score final · xG ${num(m.hxg)} - ${num(m.axg)}</span>
      <span class="tag ${ok ? "t-ok" : "t-ko"}">${ok ? "✔ prono correct" : "✘ prono raté"}</span></div>`;
  }
  const src = pred.source === "live"
    ? (m.result ? "Pronostic réel figé au coup d'envoi" : `Pronostic réel · mis à jour le ${dtF.format(new Date(pred.updated_at))}`)
    : "Pronostic de backtest (rejoué a posteriori)";
  h += `<div class="muted" style="font-size:12.5px;margin-top:8px">${src}${det.lineup_confirmed && !m.result ? ` · <span class="t-home" style="font-weight:600">composition officielle prise en compte</span>${tip("lineup")}` : ""}</div>
    <div class="bigbar" style="height:12px;margin-bottom:0">${d.final.map((x) => `<span style="width:${x * 100}%"></span>`).join("")}</div>
    <div class="outcomes">${d.final.map((x, i) => `<div class="outcome o${i} ${pred.pick === "HDA"[i] ? "pick" : ""}">
      <div class="who">${i === 0 ? "Victoire " + esc(m.home) : i === 1 ? "Match nul" : "Victoire " + esc(m.away)}</div>
      <div class="pv">${pct(x)}</div><div class="fair">cote juste ${num(1 / x)}${pred.pick === "HDA"[i] ? " · pronostic" : ""}</div></div>`).join("")}</div>
    <div class="note" style="margin-top:6px">Probabilités de chaque issue${tip("proba1n2")} · la « cote juste » est la cote à partir de laquelle un pari devient rentable${tip("odds")}</div>
  </div>`;

  // --- cellules : modèles, buts, facteurs, confrontations
  const modelTips = { poisson: "poisson", mratings: "mratings", market: "market" };
  h += `<div class="cells">
    <div class="cell"><h3>Modèles${tip("ensemble")}</h3>
      <div class="grid" style="grid-template-columns:minmax(0,1fr) 44px 42px 42px 42px">
        <span class="lbl">Modèle</span><span class="lbl r">Poids${tip("weight")}</span><span class="lbl r t-home">1</span><span class="lbl r">N</span><span class="lbl r t-ko">2</span>
        ${Object.keys(labels).map((k) => { const p = d.models[k]; return p
          ? `<span>${esc(labels[k])}${tip(modelTips[k])}</span><span class="num r muted">${d.profile === "meta" ? (k === "market" ? "base" : "corr.") : pct(d.weights[k])}</span>${p.map((x) => `<span class="num r">${pct(x)}</span>`).join("")}`
          : `<span class="muted">${esc(labels[k])}${tip(modelTips[k])}</span><span class="num r muted">–</span><span class="muted r" style="grid-column:span 3">indisponible</span>`; }).join("")}
        <span style="font-weight:700;border-top:1px solid var(--line);padding-top:6px">Ensemble</span><span style="border-top:1px solid var(--line)"></span>
        ${d.final.map((x) => `<span class="num r" style="font-weight:700;border-top:1px solid var(--line);padding-top:6px">${pct(x)}</span>`).join("")}
      </div>
      <div class="note">${d.profile === "meta" ? `Pronostic final = cotes du match (marge retirée) corrigées par nos deux modèles et par les absences${tip("meta")}`
        : `Profil ${d.profile === "with_market" ? "avec cotes" : "sans cotes"}${tip("profile")} · netteté ${num(d.weights.sharpness)}${tip("sharpness")}`}</div>
    </div>`;
  if (mk) {
    h += `<div class="cell"><h3>Buts${tip("xgExpected")}</h3>
      <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap"><span class="xg-big">${num(d.poisson.lh)} - ${num(d.poisson.la)}</span>
        <span class="muted" style="font-size:12px">avant ajustements ${num(d.poisson.lh0)} - ${num(d.poisson.la0)}</span></div>
      <div class="grid" style="grid-template-columns:minmax(0,1fr) auto;margin-top:12px">
        <span>+1.5 buts</span><span class="num r">${pct(mk.over15)}</span>
        <span>+2.5 buts${tip("over25")}</span><span class="num r">${pct(mk.over25)}</span>
        <span>+3.5 buts</span><span class="num r">${pct(mk.over35)}</span>
        <span>Les deux marquent${tip("btts")}</span><span class="num r">${pct(mk.btts)}</span>
      </div>
      <div class="lbl" style="margin:14px 0 8px">Scores les plus probables${tip("topScores")}</div>
      <div style="display:flex;flex-direction:column;gap:5px">${mk.top_scores.slice(0, 5).map((s) => `
        <div style="display:grid;grid-template-columns:38px minmax(0,1fr) 58px;gap:10px;align-items:center;font-size:13px">
          <span class="num" style="font-weight:600">${s.score}</span><span class="hbar"><span style="width:${s.p / mk.top_scores[0].p * 100}%"></span></span>
          <span class="num r muted">${pct(s.p, 1)}</span></div>`).join("")}</div>
    </div>`;
  }
  const f = det.form || {};
  const dots = (fm) => fm ? `<span class="formdots">${fm.seq.split("").map((l) => `<span class="f${l}">${l}</span>`).join("")}</span>` : "–";
  const r = det.ratings, mr = det.mratings, cx = det.context || {};
  const abs = d.absences || {};
  // pair(valeur dom, valeur ext, sens) : met en gras la meilleure des deux valeurs
  const pair = (vh, va, better, fmt = (x) => num(x)) => {
    const ok = vh != null && va != null && vh !== va;
    const hb = ok && (better === "high" ? vh > va : vh < va), ab = ok && !hb;
    return `<span class="num ${hb ? "better" : ""}">${vh == null ? "–" : fmt(vh)}</span><span class="num ${ab ? "better" : ""}">${va == null ? "–" : fmt(va)}</span>`;
  };
  const vsExp = (x) => (x > 0 ? "+" : "") + num(x) + " pt";
  const nextCup = (x) => x ? `${esc(x.comp)} dans ${num(x.days, 1)} j` : "–";
  h += `<div class="cell"><h3>Facteurs<span class="muted" style="font-family:var(--body);font-size:12px;font-weight:400">· en gras : le meilleur des deux</span></h3>
    <div class="grid" style="grid-template-columns:minmax(0,1.35fr) minmax(0,1fr) minmax(0,1fr);align-items:center">
      <span></span><span style="font-weight:600;font-size:12.5px" class="team">${teamLink(m.home_id, m.home)}</span><span style="font-weight:600;font-size:12.5px" class="team">${teamLink(m.away_id, m.away)}</span>
      <span class="muted">Derniers matchs${tip("formSeq")}</span><span>${dots(f.home)}</span><span>${dots(f.away)}</span>
      <span class="muted">Points vs attendu${tip("formVsExp")}</span>${pair(f.home?.vs_expected, f.away?.vs_expected, "high", vsExp)}
      ${mr ? `<span class="muted">Attaque · cotes${tip("mrAttack")}</span>${pair(mr.home.att, mr.away.att, "high")}
        <span class="muted">Défense · cotes${tip("mrDefense")}</span>${pair(mr.home.def, mr.away.def, "low")}` : ""}
      ${r ? `<span class="muted">Attaque · xG${tip("attack")}</span>${pair(r.home.att, r.away.att, "high")}
        <span class="muted">Défense · xG${tip("defense")}</span>${pair(r.home.def, r.away.def, "low")}` : ""}
      <span class="muted">Force à domicile${tip("homeadv")}</span><span class="num">${num(adj.home_att)} / ${num(adj.home_def)}</span><span class="muted">–</span>
      <span class="muted">Absences · attaque${tip("absAtt")}</span>${pair(adj.abs_att_h, adj.abs_att_a, "low", (x) => pct(x))}
      <span class="muted">Absences · défense${tip("absDef")}</span>${pair(adj.abs_def_h, adj.abs_def_a, "low", (x) => pct(x))}
      <span class="muted">Absences · notes${tip("absRating")}</span>${pair(adj.abs_rating_h, adj.abs_rating_a, "low", (x) => pct(x))}
      ${abs.home && (abs.home.xi_rating || abs.away?.xi_rating) ? `<span class="muted">Note du onze${tip("xiRating")}</span>${pair(abs.home.xi_rating, abs.away?.xi_rating, "high")}` : ""}
      <span class="lbl" style="grid-column:1/-1;margin-top:8px">Pour information (sans effet sur le calcul)${tip("infoOnly")}</span>
      <span class="muted">Classement</span>${pair(cx.pos_h, cx.pos_a, "low", ordinal)}
      <span class="muted">Jours de repos${tip("rest")}</span>${pair(cx.rest_h, cx.rest_a, "high", (x) => num(x, 1))}
      <span class="muted">Coupe / Europe à venir${tip("rotation")}</span><span class="num">${nextCup(cx.next_cup_h)}</span><span class="num">${nextCup(cx.next_cup_a)}</span>
    </div></div>
    <div class="cell"><h3>Confrontations directes${tip("h2h")}</h3>
      ${det.h2h && det.h2h.length ? `<div style="display:flex;flex-direction:column;gap:6px;font-size:13px">${det.h2h.map((g) => `
        <div style="display:grid;grid-template-columns:78px minmax(0,1fr) 36px minmax(0,1fr);gap:8px;align-items:baseline">
          <span class="num muted" style="font-size:12px">${dateF.format(new Date(g.date))}</span><span class="r team">${esc(g.home)}</span>
          <span class="num c" style="font-weight:600">${g.score}</span><span class="team">${esc(g.away)}</span></div>`).join("")}</div>`
        : `<p class="muted" style="margin:0;font-size:13px">Aucune confrontation récente dans l'historique chargé.</p>`}
    </div>
  </div>`;

  h += contextSection(res, d);
  h += oddsSection(res, d);
  h += `<div class="section" style="display:grid;gap:var(--gap)">
    ${ChartKit.card("d-models", "Probabilités par modèle", [["bar", "Barres"], ["stacked", "Empilé"], ["radar", "Radar"], ["line", "Lignes"]], { tipKey: "ensemble" })}
    ${mk ? ChartKit.card("d-scores", "Matrice des scores", [["heat", "Carte"], ["bar", "Barres"], ["doughnut", "Anneau"]], { tipKey: "heatmap" }) : ""}
    ${oddsHistoryCard(res)}
    ${ChartKit.card("d-form", "Forme : xG des 10 derniers matchs", [["line", "Lignes"], ["bar", "Barres"], ["diff", "Écart xG"]], { tipKey: "xg" })}
  </div>`;
  h += squadSection(res);
  h += betSection(res, d);
  el.innerHTML = h;
  mountDetailCharts(res, d);
  mountOddsChart(res);
  bindDetail(res, d);
  applyLive();
}

function contextSection(res, d) {
  const c = res.context || {}, cal = res.calendar || {}, det = d.details || {}, m = res.match;
  const w = c.weather, ref = c.referee, sta = c.stadium;
  const calRow = (side) => { const x = cal[side] || {};
    const f = (g, lbl) => g ? `<div><span class="lbl">${lbl}</span>${esc(g.comp)} · ${g.home === false ? "à" : g.home ? "vs" : "vs"} ${esc(g.opponent)} · <span class="num">${shortF.format(new Date(g.kickoff))}</span>${g.score ? ` · <span class="num">${g.score}</span>` : ""}</div>` : "";
    return `<div><strong>${esc(m[side])}</strong>${f(x.prev, "Match précédent")}${f(x.next, "Match suivant")}</div>`; };
  return `<div class="section"><h3>Contexte du match</h3>
    <div class="ctxgrid">
      ${sta ? `<div><span class="lbl">Stade</span>${esc(sta.name || "–")}${sta.city ? " · " + esc(sta.city) : ""}${sta.capacity ? ` <span class="muted num">(${Number(sta.capacity).toLocaleString("fr-FR")} places)</span>` : ""}</div>` : ""}
      <div><span class="lbl">Météo${tip("weather")}</span>${w ? `${esc(weatherFr(w.description))} · <span class="num">${w.temperature ?? "–"} °C</span> · vent <span class="num">${Math.round((w.windSpeed ?? 0) * 3.6)} km/h</span> · pluie <span class="num">${num(w.precipitation ?? 0, 1)} mm</span>${w.precipChance != null ? ` <span class="muted">(risque ${w.precipChance} %)</span>` : ""}` : `<span class="muted">non disponible</span>`}</div>
      <div><span class="lbl">Arbitre${tip("referee")}</span>${ref ? `${esc(ref.name)}${ref.yellow_per_match != null ? ` · <span class="num">${num(ref.yellow_per_match, 1)}</span> jaunes/match` : ""}${ref.penalties_total != null && ref.matches ? ` · <span class="num">${num(ref.penalties_total / ref.matches, 2)}</span> pen./match` : ""}` : `<span class="muted">pas encore désigné</span>`}</div>
      <div><span class="lbl">Derby${tip("derby")}</span>${(det.context || {}).derby ? `<span class="tag t-fg">oui</span>` : "non"}</div>
    </div>
    <h4 class="lbl" style="margin-top:14px">Calendrier toutes compétitions${tip("calendar")}</h4>
    <div class="ctxgrid" style="font-size:12.5px">${calRow("home")}${calRow("away")}</div>
  </div>`;
}

function oddsSection(res, d) {
  const m = res.match, books = res.books || [];
  if (!d.value.length && !books.length) {
    return `<div class="section muted" style="font-size:13px">Cotes pas encore publiées pour ce match (disponibles seulement pour la semaine en cours) — profil de poids « sans cotes »${tip("profile")}.</div>`;
  }
  const lab = (v) => v.market === "1X2" ? `${OUT[v.outcome]} · ${v.outcome === "H" ? esc(m.home) : v.outcome === "A" ? esc(m.away) : "Nul"}` : `${OUT[v.outcome]} buts`;
  let h = `<div class="section"><h3>Cotes &amp; value${tip("value")}</h3>
    <div class="scroll-x"><table class="tbl"><tr><th>Issue</th><th class="r">Meilleure cote${tip("bestOdds")}</th><th>Bookmaker</th><th class="r">Proba modèle</th><th class="r">Proba cote${tip("impliedProb")}</th><th class="r">Avantage${tip("edge")}</th></tr>
    ${d.value.map((v) => `<tr style="${v.flag ? "color:var(--value);font-weight:700" : ""}"><td>${lab(v)}</td><td class="num r">${num(v.odds)}</td><td>${esc(v.bookmaker)}</td>
      <td class="num r">${pct(v.p, 1)}</td><td class="num r">${pct(1 / v.odds, 1)}</td><td class="num r">${signed(v.edge, (x) => pct(x, 1))}</td></tr>`).join("")}
    </table></div><div class="note">Avantage = proba × cote − 1, calculé avec la meilleure cote disponible. Signalé en violet à partir de +5 %.</div>`;
  const singles = books.filter((b) => b.bookmaker !== "Avg" && b.bookmaker !== "Max");
  if (singles.length) {
    const best = {};
    for (const k of ["h", "d", "a", "over25", "under25"]) best[k] = Math.max(...singles.map((b) => b[k] || 0));
    const margin = (b) => b.h && b.d && b.a ? 1 / b.h + 1 / b.d + 1 / b.a - 1 : null;
    const avg = books.find((b) => b.bookmaker === "Avg");
    h += `<h4 class="lbl" style="margin-top:16px">Comparaison des bookmakers (${singles.length})</h4>
      <div class="scroll-x"><table class="tbl"><tr><th>Bookmaker</th><th class="r">1</th><th class="r">N</th><th class="r">2</th><th class="r">+2.5</th><th class="r">−2.5</th><th class="r">Marge${tip("margin")}</th></tr>
      ${singles.sort((a, b) => (margin(a) ?? 9) - (margin(b) ?? 9)).map((b) => `<tr><td>${esc(b.bookmaker)}</td>
        ${["h", "d", "a", "over25", "under25"].map((k) => `<td class="num r ${b[k] && b[k] === best[k] ? "best" : ""}">${b[k] ? num(b[k]) : "–"}</td>`).join("")}
        <td class="num r muted">${pct(margin(b), 1)}</td></tr>`).join("")}
      ${avg ? `<tr><td class="muted">Moyenne du marché</td>${["h", "d", "a", "over25", "under25"].map((k) => `<td class="num r muted">${avg[k] ? num(avg[k]) : "–"}</td>`).join("")}<td class="num r muted">${pct(margin(avg), 1)}</td></tr>` : ""}
      </table></div>`;
  }
  return h + `</div>`;
}

/* Tri des tableaux : état {key, dir}, clés = {clé: fonction de valeur} */
const POS_ORDER = { GB: 0, DEF: 1, MIL: 2, ATT: 3 };
const SQUAD_KEYS = {
  name: (p) => p.name.toLowerCase(), position: (p) => POS_ORDER[p.position] ?? 9, share_min: (p) => p.share_min,
  share_att: (p) => p.share_att, rating: (p) => p.rating ?? -1, weight: (p) => p.weight * 10 + p.share_min,
};
function sortRows(rows, st, keys) {
  const f = keys[st.key] || (() => 0);
  return [...rows].sort((a, b) => { const x = f(a), y = f(b); return (x < y ? -1 : x > y ? 1 : 0) * st.dir; });
}
function sortHead(key, label, cls, table, tipKey = "") {
  const st = table === "squad" ? S.squadSort : S.betSort;
  const on = st.key === key;
  const tag = table === "squad" ? "span" : "th";
  return `<${tag} class="${table === "squad" ? "h lbl" : ""} ${cls} sortable" data-sort-${table}="${key}" title="Trier par ${label.toLowerCase()}">${label}${on ? `<span class="sort-ind">${st.dir > 0 ? "▲" : "▼"}</span>` : ""}${tipKey ? tip(tipKey) : ""}</${tag}>`;
}
function toggleSort(st, key, defaultDir = -1) {
  if (st.key === key) st.dir = -st.dir; else { st.key = key; st.dir = key === "name" || key === "position" || key === "match" || key === "bookmaker" ? 1 : defaultDir; }
}

function squadSection(res) {
  const m = res.match, sq = res.squads || {};
  if (m.result) return `<div class="section muted" style="font-size:13px">Match terminé : les compositions ne sont plus modifiables.</div>`;
  if (!sq.home) return `<div class="section muted" style="font-size:13px">Effectifs non encore chargés pour ce match — lancez une synchronisation.</div>`;
  const cls = (p) => p.weight >= 1 ? "abs" : p.weight > 0 ? "half" : "";
  const team = (side) => { const t = sq[side];
    const rows = sortRows(t.squad.filter((p) => p.share_min >= 0.08 || p.override || p.weight > 0), S.squadSort, SQUAD_KEYS).slice(0, 30);
    const nAbs = t.absent.length;
    return `<div>
      <div class="squad-head"><span style="font-weight:700">${esc(m[side])}${t.formation ? ` <span class="muted num" style="font-weight:400">${esc(t.formation)}</span>` : ""}</span>
        <span class="lbl" style="color:${nAbs ? "var(--warn)" : "var(--muted)"}">${nAbs} ${nAbs > 1 ? "absents" : "absent"} · ${esc(t.source)}</span></div>
      <div class="squad">
        ${sortHead("name", "Joueur", "", "squad")}${sortHead("position", "Poste", "", "squad")}${sortHead("share_min", "Min.", "r", "squad", "minutesShare")}${sortHead("share_att", "xG+xA", "r", "squad", "attShare")}${sortHead("rating", "Note", "r", "squad", "rating")}${sortHead("weight", "État", "", "squad")}
        ${rows.map((p) => `<span class="${cls(p)}" title="${esc(p.name)}">${esc(p.name)}<span class="status">${esc(p.override ? (p.override === "absent" ? "absent (manuel)" : "présent (manuel)") : p.auto_label)}${p.expected_return ? " · retour : " + esc(p.expected_return) : ""}</span></span>
          <span class="lbl" style="font-size:11px">${esc(p.position)}</span><span class="num r">${pct(p.share_min)}</span><span class="num r">${pct(p.share_att)}</span>
          <span class="num r">${p.rating ? num(p.rating, 1) : "–"}</span>
          <span>${seg([["auto", "Auto"], ["absent", "Absent"], ["present", "Présent"]], p.override || "auto", "ov", "small").replace(/data-ov="(\w+)"/g,
            `data-ov="$1" data-player="${esc(p.player_id)}" data-name="${esc(p.name)}" data-team="${esc(t.team_id)}"`)}</span>`).join("")}
      </div></div>`; };
  return `<div class="section"><h3>Effectifs &amp; absences${tip("unavailable")}</h3>
    <p class="muted" style="font-size:12.5px;margin:0 0 14px;text-wrap:pretty">Sources par priorité : vos corrections, puis la composition officielle (vérifiée toutes les ${META.lineup_watch_minutes} min dans l'heure qui précède le match)${tip("lineup")}, puis la liste des blessés/suspendus FotMob. « Incertain » et « remplaçant » comptent pour moitié. Le pronostic est recalculé dès que vous corrigez.</p>
    <div style="display:flex;flex-direction:column;gap:18px">${team("home")}${team("away")}</div></div>`;
}

function betSection(res, d) {
  const m = res.match;
  const opts = [["1X2", "H", `1 · ${m.home}`], ["1X2", "D", "N · Nul"], ["1X2", "A", `2 · ${m.away}`], ["OU25", "O", "+2.5 buts"], ["OU25", "U", "−2.5 buts"]];
  const bestFor = (mkt, sel) => d.value.find((v) => v.market === mkt && v.outcome === sel);
  const bets = res.bets || [];
  return `<div class="section"><h3>Parier sur ce match${tip("bankroll")}</h3>
    ${bets.length ? `<div class="scroll-x" style="margin-bottom:12px"><table class="tbl"><tr><th>Carnet</th><th>Pari</th><th class="r">Cote</th><th class="r">Mise</th><th class="r">Avantage</th><th>Statut</th><th class="r">Gain</th></tr>
      ${bets.map((b) => `<tr><td>${b.book === "auto" ? "Simulation" : "Mes paris"}</td><td>${OUT[b.selection]} ${b.bookmaker ? `<span class="muted">· ${esc(b.bookmaker)}</span>` : ""}</td>
        <td class="num r">${num(b.odds)}</td><td class="num r">${eur(b.stake)}</td><td class="num r">${signed(b.edge, (x) => pct(x, 1))}</td>
        <td>${statusTag(b.status)}</td><td class="num r">${b.profit != null ? eur(b.profit) : "–"}</td></tr>`).join("")}</table></div>` : ""}
    ${m.result ? "" : `<form class="form" id="bet-form">
      <label><span>Pari</span><select name="sel">${opts.map(([mk, s, l]) => `<option value="${mk}|${s}">${esc(l)}</option>`).join("")}</select></label>
      <label><span>Cote${tip("odds")}</span><input name="odds" type="number" step="0.01" min="1.01" required></label>
      <label><span>Mise (€)</span><input name="stake" type="number" step="0.5" min="0.5" required></label>
      <label><span>Bookmaker</span><input name="bookmaker" type="text" placeholder="ex. Bet365"></label>
      <button class="btn primary" type="submit">Enregistrer le pari</button>
    </form><div class="note" id="bet-hint"></div>`}
  </div>`;
}

const WEATHER_FR = {
  "sunny": "Ensoleillé", "clear": "Dégagé", "mostly sunny": "Plutôt ensoleillé", "mostly clear": "Plutôt dégagé",
  "partly cloudy": "Partiellement nuageux", "partly sunny": "Éclaircies", "mostly cloudy": "Plutôt nuageux", "cloudy": "Nuageux",
  "overcast": "Couvert", "fog": "Brouillard", "foggy": "Brouillard", "mist": "Brume", "haze": "Brume sèche", "hazy": "Brume sèche",
  "drizzle": "Bruine", "light drizzle": "Bruine légère", "light rain": "Pluie faible", "rain": "Pluie", "moderate rain": "Pluie modérée",
  "heavy rain": "Forte pluie", "showers": "Averses", "light showers": "Averses légères", "rain showers": "Averses",
  "scattered showers": "Averses éparses", "isolated showers": "Averses isolées", "thunderstorm": "Orage", "thunderstorms": "Orages",
  "scattered thunderstorms": "Orages épars", "isolated thunderstorms": "Orages isolés", "snow": "Neige", "light snow": "Neige faible",
  "heavy snow": "Forte neige", "snow showers": "Averses de neige", "sleet": "Neige fondue", "freezing rain": "Pluie verglaçante",
  "wind": "Venteux", "windy": "Venteux", "breezy": "Brise", "hot": "Très chaud", "cold": "Froid",
};
function weatherFr(desc) {
  if (!desc) return "";
  const k = String(desc).toLowerCase().trim();
  if (WEATHER_FR[k]) return WEATHER_FR[k];
  // traduction mot à mot pour les combinaisons (« Mostly Cloudy / Wind »…)
  return k.split(/\s*[\/,&]\s*|\s+and\s+/).map((part) => WEATHER_FR[part] || part).join(", ").replace(/^./, (c) => c.toUpperCase());
}

function statusTag(s) {
  return { won: `<span class="tag t-ok">gagné</span>`, lost: `<span class="tag t-ko">perdu</span>`, pending: `<span class="tag t-muted">en cours</span>`, void: `<span class="tag t-muted">annulé</span>` }[s] || s;
}

function bindDetail(res, d) {
  const m = res.match;
  $$("#detail [data-sort-squad]").forEach((h) => h.addEventListener("click", () => {
    toggleSort(S.squadSort, h.dataset.sortSquad);
    const el = $("#detail"), top = el.scrollTop;
    renderDetail(DETAIL);
    $("#detail").scrollTop = top;
  }));
  $$("#detail [data-ov]").forEach((b) => b.addEventListener("click", async () => {
    $$("#detail [data-ov]").forEach((x) => (x.disabled = true));
    const r = await api(`/api/match/${m.id}/absence`, { method: "POST", body: JSON.stringify({
      player_id: b.dataset.player, player: b.dataset.name, team_id: b.dataset.team, status: b.dataset.ov }) });
    DETAIL = r;
    renderDetail(r);
    loadMatches().then(() => { const row = $(`.mrow[data-id="${m.id}"]`); if (row) row.outerHTML = matchRow(MATCHES.matches.find((x) => x.id === m.id)); rebindRows(); });
  }));
  const form = $("#bet-form");
  if (form) {
    const fill = async () => {
      const [mk, sel] = form.sel.value.split("|");
      const v = d.value.find((x) => x.market === mk && x.outcome === sel);
      form.odds.value = v ? v.odds : "";
      form.bookmaker.value = v ? v.bookmaker : "";
      const ou = d.over25 ?? (d.poisson ? d.poisson.markets.over25 : null);
      const p = mk === "1X2" ? d.final["HDA".indexOf(sel)] : ou != null ? (sel === "O" ? ou : 1 - ou) : null;
      const bk = await api("/api/bankroll?book=manual");
      const s = bk.settings, odds = Number(form.odds.value);
      let stake = null;
      if (p && odds > 1) {
        const kelly = Math.max((p * odds - 1) / (odds - 1), 0) * s.kelly_fraction;
        stake = Math.round(Math.min(s.staking === "flat" ? s.flat_pct : kelly, s.max_stake_pct) * bk.kpis.bank * 2) / 2;
      }
      form.stake.value = stake || "";
      $("#bet-hint").innerHTML = p ? `Proba du modèle : <strong>${pct(p, 1)}</strong> · juste cote ${num(1 / p)}${odds > 1 ? ` · avantage ${signed(p * odds - 1, (x) => pct(x, 1))}` : ""} · mise suggérée selon votre stratégie (${s.staking === "flat" ? "mise fixe" : "¼ Kelly"})${tip("kelly")}` : "";
    };
    form.sel.addEventListener("change", fill);
    fill();
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const [market, selection] = form.sel.value.split("|");
      await api("/api/bets", { method: "POST", body: JSON.stringify({ match_id: m.id, market, selection, odds: form.odds.value, stake: form.stake.value, bookmaker: form.bookmaker.value }) });
      openMatch(m.id);
    });
  }
}
function rebindRows() {
  $$(".mrow").forEach((r) => { r.onclick = () => { S.sel = r.dataset.id; $$(".mrow").forEach((x) => x.classList.toggle("sel", x === r)); openMatch(S.sel); }; });
}

function mountDetailCharts(res, d) {
  const m = res.match, labels = res.labels;
  ChartKit.mount("d-models", (type, c) => {
    const keys = Object.keys(labels).filter((k) => d.models[k]);
    const names = [...keys.map((k) => labels[k].split(" (")[0]), "Ensemble"];
    const rows = [...keys.map((k) => d.models[k]), d.final];
    const outc = ["1 · " + m.home, "N · Nul", "2 · " + m.away], col = [c.home, c.draw, c.away];
    if (type === "radar") return { type: "radar", data: { labels: outc, datasets: rows.map((p, i) => ({ label: names[i], data: p.map((x) => x * 100),
      borderColor: c.series[i % 8], backgroundColor: ChartKit.alpha(c.series[i % 8], .08), borderWidth: i === rows.length - 1 ? 3 : 1.5, pointRadius: 2 })) },
      options: { scales: { r: { ticks: { callback: (v) => v + " %", backdropColor: "transparent" }, grid: { color: c.line2 }, angleLines: { color: c.line2 } } } } };
    if (type === "line") return { type: "line", data: { labels: names, datasets: outc.map((o, j) => ({ label: o, data: rows.map((p) => p[j] * 100), borderColor: col[j], backgroundColor: col[j], tension: .25 })) },
      options: { scales: { y: { ticks: { callback: (v) => v + " %" } } } } };
    return { type: "bar", data: { labels: names, datasets: outc.map((o, j) => ({ label: o, data: rows.map((p) => p[j] * 100), backgroundColor: col[j] })) },
      options: { indexAxis: type === "stacked" ? "y" : "x", scales: { x: { stacked: type === "stacked", max: type === "stacked" ? 100 : undefined }, y: { stacked: type === "stacked", ticks: { callback: type === "stacked" ? undefined : (v) => v + " %" } } },
        plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label} : ${num(ctx.raw, 1)} %` } } } } };
  });
  if (d.poisson) ChartKit.mount("d-scores", (type, c) => {
    const M = d.poisson.matrix, n = M.length;
    if (type === "heat") {
      const max = Math.max(...M.flat());
      return { html: `<div class="heat" style="grid-template-columns:34px repeat(${n},1fr)">
        <div class="hd" title="Buts ${esc(m.home)} (lignes) / ${esc(m.away)} (colonnes)">D\E</div>${M[0].map((_, j) => `<div class="hd">${j}</div>`).join("")}
        ${M.map((row, i) => `<div class="hd">${i}</div>${row.map((p, j) => `<div title="${i}-${j} : ${pct(p, 1)}" style="background:${ChartKit.alpha(i > j ? c.home : i === j ? c.draw : c.away, Math.max(p / max, .04))};color:${p / max > .55 ? "#fff" : "var(--fg)"}">${(p * 100).toFixed(1)}</div>`).join("")}`).join("")}
        </div><div class="note">Lignes : buts de ${esc(m.home)} · colonnes : buts de ${esc(m.away)} · valeurs en %. Bleu = victoire domicile, gris = nul, rouge = victoire extérieure.</div>` };
    }
    const top = d.poisson.markets.top_scores.slice(0, 8);
    const colorOf = (s) => { const [a, b] = s.split("-").map(Number); return a > b ? c.home : a === b ? c.draw : c.away; };
    if (type === "doughnut") return { type: "doughnut", data: { labels: top.map((s) => s.score), datasets: [{ data: top.map((s) => s.p * 100), backgroundColor: top.map((s) => colorOf(s.score)), borderColor: c.card }] },
      options: { plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: (ctx) => `${ctx.label} : ${num(ctx.raw, 1)} %` } } } } };
    return { type: "bar", data: { labels: top.map((s) => s.score), datasets: [{ label: "Probabilité", data: top.map((s) => s.p * 100), backgroundColor: top.map((s) => colorOf(s.score)) }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { ticks: { callback: (v) => v + " %" } } } } };
  });
  ChartKit.mount("d-form", (type, c) => {
    const H = res.series.home, A = res.series.away;
    if (!H.length && !A.length) return null;
    const n = Math.max(H.length, A.length);
    const lab = Array.from({ length: n }, (_, i) => `J-${n - i}`);
    const pad = (arr, f) => [...Array(n - arr.length).fill(null), ...arr.map(f)];
    if (type === "diff") return { type: "bar", data: { labels: lab, datasets: [
      { label: m.home + " (xG pour − contre)", data: pad(H, (g) => g.xgf - g.xga), backgroundColor: c.home },
      { label: m.away + " (xG pour − contre)", data: pad(A, (g) => g.xgf - g.xga), backgroundColor: c.away }] } };
    const kind = type === "bar" ? "bar" : "line";
    return { type: kind, data: { labels: lab, datasets: [
      { label: m.home + " · xG pour", data: pad(H, (g) => g.xgf), borderColor: c.home, backgroundColor: c.home, tension: .3 },
      { label: m.home + " · xG contre", data: pad(H, (g) => g.xga), borderColor: ChartKit.alpha(c.home, .45), backgroundColor: ChartKit.alpha(c.home, .45), borderDash: [4, 3], tension: .3 },
      { label: m.away + " · xG pour", data: pad(A, (g) => g.xgf), borderColor: c.away, backgroundColor: c.away, tension: .3 },
      { label: m.away + " · xG contre", data: pad(A, (g) => g.xga), borderColor: ChartKit.alpha(c.away, .45), backgroundColor: ChartKit.alpha(c.away, .45), borderDash: [4, 3], tension: .3 }] },
      options: { plugins: { tooltip: { callbacks: { title: (items) => { const i = items[0].dataIndex; const g = items[0].datasetIndex < 2 ? H[i - (n - H.length)] : A[i - (n - A.length)]; return g ? `${g.date} · vs ${g.opponent} (${g.gf}-${g.ga})` : ""; } } } } } };
  });
}

/* ================================================================== CALENDRIER */
async function viewCalendar(v) {
  v.innerHTML = `<main class="page"><div class="head"><div class="kicker">Calendrier européen &amp; coupes</div>
    <h1 class="title">Les autres compétitions</h1>
    <div class="subtitle">Ligue des champions, Ligue Europa, Ligue Conférence et coupes nationales des équipes suivies : 7 derniers jours et 3 prochaines semaines.${tip("calendar")}</div></div>
    <div class="filters">${seg([["all", "Tout"], ["europe", "Coupes d'Europe"], ["cup", "Coupes nationales"]], S.calKind, "calkind")}</div>
    <div id="cal-list" class="list"><div class="card pad muted">Chargement…</div></div></main>`;
  bind("calkind", (k) => { S.calKind = k; render(); });
  const rows = (await api("/api/calendar")).filter((c) => S.calKind === "all" || c.kind === S.calKind);
  const byDay = {};
  for (const c of rows) (byDay[dayF.format(new Date(c.kickoff))] ||= []).push(c);
  const info = (x) => { if (!x) return "";
    const warnRest = x.rest_before != null && x.rest_before < 4, nl = x.next_league, warnNext = nl && nl.days <= 3.5;
    return `<span class="status" style="text-transform:none">${LCODE[x.league] || ""} · repos avant : <span style="color:${warnRest ? "var(--warn)" : "inherit"}">${num(x.rest_before, 1)} j</span>${nl ? ` · championnat ensuite : <span style="color:${warnNext ? "var(--warn)" : "inherit"}">J+${num(nl.days, 1)}</span> vs ${esc(nl.opponent)}` : ""}</span>`; };
  $("#cal-list").innerHTML = rows.length ? Object.entries(byDay).map(([day, cs]) => `<div class="card">
    <div class="day-head"><h2>${cap(day)}</h2><span class="lbl">${cs.length} ${cs.length > 1 ? "matchs" : "match"}</span></div>
    ${cs.map((c) => `<div class="mrow" style="grid-template-columns:50px minmax(0,1fr) auto;cursor:default">
      <div style="display:flex;flex-direction:column;gap:2px"><span class="time">${timeF.format(new Date(c.kickoff))}</span></div>
      <div style="min-width:0;display:grid;gap:4px">
        <div><span class="${c.home_info ? "" : "muted"}" style="font-weight:${c.home_info ? 700 : 400}">${esc(c.home)}</span>${info(c.home_info)}</div>
        <div><span class="${c.away_info ? "" : "muted"}" style="font-weight:${c.away_info ? 700 : 400}">${esc(c.away)}</span>${info(c.away_info)}</div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px"><span class="tag ${c.kind === "europe" ? "t-home" : "t-muted"}">${esc(c.comp)}</span>
        ${c.finished ? `<span class="num" style="font-weight:600">${c.hs}-${c.as_}</span>` : ""}</div>
    </div>`).join("")}</div>`).join("") : `<div class="card pad muted">Aucun match de coupe ou européen dans la période (lancez une synchronisation si le calendrier est vide).</div>`;
}

/* ================================================================== BANKROLL */
async function viewBankroll(v) {
  v.innerHTML = `<main class="page"><div class="head"><div class="kicker">Suivi de bankroll${tip("bankroll")}</div>
    <h1 class="title">Gestion des mises</h1>
    <div class="subtitle">Simulation automatique des value bets, vos paris réels, et test de la stratégie sur l'historique.</div></div>
    <div class="filters">${seg([["auto", "Conseiller (simulation)"], ["manual", "Mes paris"], ["lineup", "Après compo (test)"], ["hist", "Simulation historique"]], S.book, "book")}
      ${tip({ auto: "autoBook", manual: "bankroll", lineup: "lineupBook", hist: "histSim" }[S.book])}</div>
    <div id="bk"><div class="card pad muted">Chargement…</div></div></main>`;
  bind("book", (k) => { S.book = k; render(); });
  const season = META.season;
  const period = { all: ["", ""], prev: ["", `${season}-07-01`], cur: [`${season}-07-01`, ""] }[S.histPeriod];
  const data = S.book === "hist" ? await api(`/api/bankroll/simulate?from=${period[0]}&to=${period[1]}`) : await api(`/api/bankroll?book=${S.book}`);
  const k = data.kpis, s = data.settings;
  const cls = (x) => (x > 0 ? "pos" : x < 0 ? "neg" : "");
  let h = "";
  h += tutorial();
  if (S.book === "hist") h += `<div class="filters" style="margin-bottom:12px"><span class="lbl">Période</span>${seg([["all", "Tout"], ["prev", `Saison ${season - 1}/${String(season).slice(2)}`], ["cur", `Saison ${season}/${String(season + 1).slice(2)}`]], S.histPeriod, "hperiod")}</div>`;
  if (S.book === "hist") h += `<div class="warnbox">Stratégie rejouée sur 8 saisons avec les cotes réelles de l'époque. Chaque saison est pronostiquée par un modèle qui n'a appris que sur les saisons précédentes, sans les compositions officielles. Le hasard reste important sur quelques centaines de paris : fiez-vous d'abord à la « cote de clôture » (CLV), qui annonce le rendement à long terme.</div>`;
  h += `<div class="kpis">
    <div class="card pad kpi"><div class="lbl">Bankroll${tip("bankroll")}</div><div class="v">${eur(k.bank)}</div><div class="sub">départ ${eur(s.initial)}</div></div>
    <div class="card pad kpi"><div class="lbl">Bénéfice</div><div class="v ${cls(k.profit)}">${signed(k.profit, eur)}</div><div class="sub">ROI ${signed(k.roi, (x) => pct(x, 1))}${tip("roi")}</div></div>
    <div class="card pad kpi"><div class="lbl">Yield${tip("yield")}</div><div class="v ${cls(k.yield)}">${signed(k.yield, (x) => pct(x, 1))}</div><div class="sub">${eur(k.staked)} misés</div></div>
    <div class="card pad kpi"><div class="lbl">Paris${tip("hitRate")}</div><div class="v">${k.n_settled}</div><div class="sub">${pct(k.hit_rate, 0)} gagnés · ${k.n_pending} en cours · cote moy. ${num(k.avg_odds)}</div></div>
    <div class="card pad kpi"><div class="lbl">Drawdown max${tip("drawdown")}</div><div class="v">${pct(k.max_drawdown, 1)}</div><div class="sub">plus forte baisse depuis un sommet</div></div>
    <div class="card pad kpi"><div class="lbl">Cote de clôture${tip("clv")}</div><div class="v ${cls(k.clv)}">${k.clv == null ? "–" : signed(k.clv, (x) => pct(x, 2))}</div><div class="sub">${k.clv == null ? "pas encore de pari réglé" : `CLV moyenne sur ${k.clv_n} paris · rendement attendu à long terme`}</div></div>
  </div>
  <div class="cols">
    ${ChartKit.card("b-equity", "Évolution de la bankroll", [["line", "Courbe"], ["area", "Aire"], ["bar", "Gains par pari"]], { tipKey: "bankroll" })}
    ${ChartKit.card("b-break", "Rentabilité par " + { league: "championnat", market: "marché", edge: "avantage", bookmaker: "bookmaker" }[S.bdDim],
      [["bar", "Barres"], ["doughnut", "Anneau"], ["polar", "Polaire"]], { tipKey: "yield", note: `Afficher par : ${seg([["league", "Championnat"], ["market", "Marché"], ["edge", "Avantage"], ["bookmaker", "Bookmaker"]], S.bdDim, "bddim", "small")}` })}
  </div>`;
  h += `<div class="card pad" style="margin-bottom:var(--gap)"><div class="chart-head"><h3 class="big" style="margin:0">Meilleures stratégies${tip("optimizer")}</h3>
    <button class="btn primary" id="opt-run">Chercher les meilleures stratégies</button></div>
    <p class="muted" style="margin:0;font-size:12.5px">Stratégie active : <strong style="color:var(--fg)">${esc(s.strategy_label || "")}</strong>. Le programme teste des centaines de combinaisons (marchés, avantage minimum, cote max, probabilité minimale, méthode de mise) et propose les plus rentables.</p>
    <div id="opt-box" style="margin-top:12px"></div></div>`;
  h += settingsCard(s);
  if (S.book === "manual") h += manualForm();
  h += betsTable(data.bets || [], S.book);
  $("#bk").innerHTML = h;
  bind("bddim", (d) => { S.bdDim = d; render(); });
  bind("hperiod", (k) => { S.histPeriod = k; render(); });
  $("#opt-run").addEventListener("click", loadOptimizer);
  $$("[data-sort-bets]").forEach((h) => h.addEventListener("click", () => { toggleSort(S.betSort, h.dataset.sortBets); render(); }));
  $("#tuto").addEventListener("toggle", (e) => { try { localStorage.setItem("pf-tuto-bankroll", e.target.open ? "open" : "closed"); } catch (err) { /* ignore */ } });
  ChartKit.mount("b-equity", (type, c) => {
    const curve = k.curve;
    if (curve.length < 2) return null;
    if (type === "bar") {
      const settled = (data.bets || []).filter((b) => b.status === "won" || b.status === "lost").sort((a, b) => a.kickoff.localeCompare(b.kickoff));
      return { type: "bar", data: { labels: settled.map((b) => shortF.format(new Date(b.kickoff))), datasets: [{ label: "Gain (€)", data: settled.map((b) => b.profit), backgroundColor: settled.map((b) => (b.profit >= 0 ? c.ok : c.ko)) }] },
        options: { plugins: { legend: { display: false } } } };
    }
    return { type: "line", data: { labels: curve.map((p, i) => (p.date ? shortF.format(new Date(p.date)) : "départ")), datasets: [
      { label: "Bankroll (€)", data: curve.map((p) => p.bank), borderColor: c.home, backgroundColor: ChartKit.alpha(c.home, .15), fill: type === "area", pointRadius: curve.length > 60 ? 0 : 2, tension: .15 },
      { label: "Départ", data: curve.map(() => s.initial), borderColor: c.muted, borderDash: [4, 4], pointRadius: 0 }] } };
  });
  ChartKit.mount("b-break", (type, c) => {
    const bd = data.breakdown[S.bdDim] || {};
    const keys = Object.keys(bd);
    if (!keys.length) return null;
    const lab = keys.map((x) => (META.leagues[x] ? META.leagues[x].name : x === "1X2" ? "1N2" : x === "OU25" ? "+/− 2.5 buts" : x));
    if (type === "bar") return { type: "bar", data: { labels: lab, datasets: [{ label: "Bénéfice (€)", data: keys.map((x) => bd[x].profit), backgroundColor: keys.map((x) => (bd[x].profit >= 0 ? c.ok : c.ko)) }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: (ctx) => `${bd[keys[ctx.dataIndex]].n} paris · yield ${pct(bd[keys[ctx.dataIndex]].yield, 1)}` } } } } };
    return { type: type === "polar" ? "polarArea" : "doughnut", data: { labels: lab, datasets: [{ label: "Misé (€)", data: keys.map((x) => bd[x].staked), backgroundColor: keys.map((_, i) => ChartKit.alpha(c.series[i % 8], .8)), borderColor: c.card }] },
      options: { plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: (ctx) => `${ctx.label} : ${eur(ctx.raw)} misés, ${eur(bd[keys[ctx.dataIndex]].profit)} de bénéfice` } } },
        scales: type === "polar" ? { r: { ticks: { backdropColor: "transparent" }, grid: { color: c.line2 } } } : undefined } };
  });
  bindBankroll();
}

function settingsCard(s) {
  return `<div class="card pad" style="margin-bottom:var(--gap)"><h3 class="big">Stratégie de mise</h3>
    <form class="form" id="bk-settings">
      <label><span>Bankroll de départ (€)</span><input name="initial" type="number" step="10" min="10" value="${s.initial}"></label>
      <label><span>Méthode${tip("kelly")}</span><select name="staking"><option value="kelly" ${s.staking === "kelly" ? "selected" : ""}>Fraction de Kelly</option><option value="flat" ${s.staking === "flat" ? "selected" : ""}>Mise fixe (% bankroll)</option></select></label>
      <label><span>Fraction de Kelly</span><input name="kelly_fraction" type="number" step="0.05" min="0.05" max="1" value="${s.kelly_fraction}"></label>
      <label><span>Mise fixe (% bankroll)${tip("flat")}</span><input name="flat_pct" type="number" step="0.5" min="0.1" max="10" value="${s.flat_pct * 100}"></label>
      <label><span>Mise max (% bankroll)</span><input name="max_stake_pct" type="number" step="0.5" min="0.5" max="25" value="${s.max_stake_pct * 100}"></label>
      <label><span>Avantage minimum${tip("edge")}</span><input name="min_edge" type="number" step="1" min="0" max="50" value="${s.min_edge * 100}"></label>
      <label><span>Cote max</span><input name="max_odds" type="number" step="0.5" min="1.5" max="50" value="${s.max_odds}"></label>
      <label><span>Marchés</span><span style="display:flex;gap:10px;text-transform:none;letter-spacing:0;font-family:var(--body);font-size:13px;color:var(--fg)">
        <label class="inline"><input type="checkbox" name="m1x2" ${s.markets.includes("1X2") ? "checked" : ""}> 1N2</label>
        <label class="inline"><input type="checkbox" name="mou" ${s.markets.includes("OU25") ? "checked" : ""}> ±2.5</label></span></label>
      <label class="inline"><input type="checkbox" name="auto" ${s.auto ? "checked" : ""}> Simulation automatique active</label>
      <button class="btn primary" type="submit">${S.book === "hist" ? "Relancer la simulation" : "Enregistrer"}</button>
    </form>
    <div class="note">Les pourcentages sont en % (ex. 5 = 5 %). La simulation automatique place un pari virtuel sur chaque value bet des matchs à venir ; la mise est figée au coup d'envoi puis réglée au résultat.</div></div>`;
}

function manualForm() {
  const upcoming = MATCHES.matches.filter((m) => !m.result && new Date(m.kickoff) > new Date());
  return `<div class="card pad" style="margin-bottom:var(--gap)"><h3 class="big">Ajouter un pari</h3>
    ${upcoming.length ? `<form class="form" id="bk-add">
      <label style="grid-column:span 2"><span>Match</span><select name="match">${upcoming.map((m) => `<option value="${m.id}">${dtF.format(new Date(m.kickoff))} · ${esc(m.home)} – ${esc(m.away)}</option>`).join("")}</select></label>
      <label><span>Pari</span><select name="sel"><option value="1X2|H">1 (domicile)</option><option value="1X2|D">N (nul)</option><option value="1X2|A">2 (extérieur)</option><option value="OU25|O">+2.5 buts</option><option value="OU25|U">−2.5 buts</option></select></label>
      <label><span>Cote</span><input name="odds" type="number" step="0.01" min="1.01" required></label>
      <label><span>Mise (€)</span><input name="stake" type="number" step="0.5" min="0.5" required></label>
      <label><span>Bookmaker</span><input name="bookmaker" type="text"></label>
      <button class="btn primary" type="submit">Enregistrer</button></form>
      <div class="note">Astuce : depuis la fiche d'un match, la meilleure cote et la mise conseillée sont pré-remplies.</div>` : `<p class="muted">Aucun match à venir dans la fenêtre.</p>`}</div>`;
}

const BET_KEYS = {
  kickoff: (b) => b.kickoff, match: (b) => (b.home + b.away).toLowerCase(), selection: (b) => b.market + b.selection,
  odds: (b) => b.odds, bookmaker: (b) => (b.bookmaker || "").toLowerCase(), stake: (b) => b.stake, p_model: (b) => b.p_model ?? -1,
  edge: (b) => b.edge ?? -9, clv: (b) => b.clv ?? -9, status: (b) => ({ pending: 0, won: 1, lost: 2, void: 3 }[b.status] ?? 9), profit: (b) => b.profit ?? -1e9,
};
function betsTable(bets, book) {
  if (!bets.length) return `<div class="card pad muted">${book === "manual" ? "Aucun pari enregistré." : "Aucun pari pour l'instant : la simulation parie dès qu'un value bet apparaît."}</div>`;
  const rows = sortRows(bets, S.betSort, BET_KEYS).slice(0, 400);
  const H = (k, l, cls = "", t = "") => sortHead(k, l, cls, "bets", t);
  return `<div class="card scroll-x"><div class="pad" style="padding:12px 14px 0"><h3 class="big" style="margin:0">Historique des paris <span class="muted" style="font-family:var(--body);font-size:12.5px;font-weight:400">· cliquez sur un en-tête pour trier</span></h3></div>
    <table class="tbl" style="min-width:900px"><tr>${H("kickoff", "Date")}${H("match", "Match")}${H("selection", "Pari")}${H("odds", "Cote", "r", "odds")}${H("bookmaker", "Bookmaker")}
      ${H("stake", "Mise", "r")}${H("p_model", "Proba", "r")}${H("edge", "Avantage", "r", "edge")}${H("clv", "CLV", "r", "clv")}${H("status", "Statut")}${H("profit", "Gain", "r")}${book === "manual" ? "<th></th>" : ""}</tr>
    ${rows.map((b) => `<tr><td class="num muted">${dateF.format(new Date(b.kickoff))}</td><td class="wrap" style="font-weight:600">${esc(b.home)} – ${esc(b.away)}${b.hg != null ? ` <span class="num muted">${b.hg}-${b.ag}</span>` : ""}</td>
      <td class="num">${OUT[b.selection]}</td><td class="num r">${num(b.odds)}</td><td>${esc(b.bookmaker || "–")}</td><td class="num r">${eur(b.stake)}</td>
      <td class="num r">${pct(b.p_model, 1)}</td><td class="num r">${signed(b.edge, (x) => pct(x, 1))}</td>
      <td class="num r" style="color:${b.clv > 0 ? "var(--ok)" : b.clv < 0 ? "var(--ko)" : "inherit"}">${b.clv == null ? "–" : signed(b.clv, (x) => pct(x, 1))}</td><td>${statusTag(b.status)}</td>
      <td class="num r" style="color:${b.profit > 0 ? "var(--ok)" : b.profit < 0 ? "var(--ko)" : "inherit"}">${b.profit != null ? signed(b.profit, eur) : "–"}</td>
      ${book === "manual" ? `<td><button class="btn" data-del="${b.id}" title="Supprimer ce pari">✕</button></td>` : ""}</tr>`).join("")}</table>
    ${bets.length > 400 ? `<div class="note" style="padding:0 14px 12px">400 premiers paris affichés sur ${bets.length}.</div>` : ""}</div>`;
}

function tutorial() {
  let open = true;
  try { open = localStorage.getItem("pf-tuto-bankroll") !== "closed"; } catch (e) { /* stockage indisponible */ }
  return `<details class="card pad tuto" id="tuto" style="margin-bottom:var(--gap)" ${open ? "open" : ""}>
    <summary>Tutoriel : comment utiliser la bankroll</summary>
    <ol>
      <li><strong>Fixez votre bankroll</strong> : la somme totale que vous acceptez de consacrer aux paris (et de perdre). Réglez-la dans « Stratégie de mise » ci-dessous.${tip("bankroll")}</li>
      <li><strong>Choisissez une méthode de mise</strong> : ¼ de Kelly (recommandé) mise davantage quand l'avantage est grand, la mise fixe joue toujours le même pourcentage. Ne dépassez jamais 2 à 5 % par pari.${tip("kelly")}</li>
      <li><strong>Laissez tourner la « Simulation automatique »</strong> quelques semaines : elle parie virtuellement chaque value bet détecté, avec la meilleure cote disponible, et règle les paris au résultat. C'est gratuit et sans risque.${tip("autoBook")}</li>
      <li><strong>Vérifiez la « Simulation historique »</strong> : même stratégie rejouée sur les saisons passées. Comparez « saison précédente » et « saison en cours » : si les résultats divergent beaucoup, méfiance.${tip("histSim")}</li>
      <li><strong>Pour parier pour de vrai</strong> : ouvrez la fiche d'un match (onglet Matchs) → section « Parier sur ce match ». La meilleure cote et la mise conseillée sont pré-remplies ; notez la cote réellement obtenue puis « Enregistrer ». Le résultat est réglé automatiquement.</li>
      <li><strong>Suivez les bons indicateurs</strong> : le yield (gain par euro misé) et le drawdown (plus forte baisse) comptent plus que le taux de réussite. Il faut plusieurs centaines de paris pour juger une stratégie.${tip("yield")}${tip("drawdown")}</li>
    </ol>
    <div class="note">Rappel : les bookmakers intègrent la plupart des informations publiques. Même un bon modèle ne garantit aucun gain — ne misez que ce que vous pouvez vous permettre de perdre.</div>
  </details>`;
}

function bindBankroll() {
  const f = $("#bk-settings");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const markets = [f.m1x2.checked && "1X2", f.mou.checked && "OU25"].filter(Boolean);
    const body = { initial: +f.initial.value, staking: f.staking.value, kelly_fraction: +f.kelly_fraction.value, flat_pct: f.flat_pct.value / 100,
      max_stake_pct: f.max_stake_pct.value / 100, min_edge: f.min_edge.value / 100, max_odds: +f.max_odds.value, markets, auto: f.auto.checked };
    f.querySelector("button").disabled = true;
    await api("/api/bankroll/settings", { method: "POST", body: JSON.stringify(body) });
    render();
  });
  const add = $("#bk-add");
  if (add) add.addEventListener("submit", async (e) => {
    e.preventDefault();
    const [market, selection] = add.sel.value.split("|");
    await api("/api/bets", { method: "POST", body: JSON.stringify({ match_id: add.match.value, market, selection, odds: add.odds.value, stake: add.stake.value, bookmaker: add.bookmaker.value }) });
    render();
  });
  $$("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Supprimer ce pari ?")) return;
    await api(`/api/bets/${b.dataset.del}`, { method: "DELETE" });
    render();
  }));
}

/* ================================================================== PERFORMANCES */
async function viewStats(v) {
  v.innerHTML = `<main class="page"><div class="kicker">Performances</div><h1 class="title" style="margin-bottom:18px">Fiabilité des modèles</h1>
    <div class="filters">${seg([["live", "Pronostics réels (avant match)"], ["backtest", "Backtest"], ["all", "Tout"]], S.sSource, "ssource")}
      ${tip(S.sSource === "backtest" ? "backtest" : "live")}${chips(S.sLeague, "sleague")}</div><div id="st"><div class="card pad muted">Chargement…</div></div></main>`;
  bind("ssource", (k) => { S.sSource = k; render(); });
  bind("sleague", (k) => { S.sLeague = k; render(); });
  const s = await api(`/api/stats?source=${S.sSource}&league=${S.sLeague}`);
  const o = s.overall, b = s.baseline;
  const row = (label, x, cls = "") => x && x.n ? `<tr class="${cls}"><td style="${cls === "hl" ? "font-weight:700" : ""}">${label}</td><td class="num r muted">${x.n.toLocaleString("fr-FR")}</td>
    <td class="num r">${pct(x.accuracy, 1)}</td><td class="num r">${num(x.brier, 4)}</td><td class="num r">${num(x.logloss, 4)}</td></tr>` : "";
  const head = (first) => `<tr><th>${first}</th><th class="r">n</th><th class="r">Réussite${tip("accuracy")}</th><th class="r">Brier${tip("brier")}</th><th class="r">Log-loss${tip("logloss")}</th></tr>`;
  const tipsModel = { poisson: "poisson", mratings: "mratings", market: "market" };
  let h = S.sSource !== "live" ? `<div class="warnbox">Backtest sur 8 saisons : chaque saison est pronostiquée par un modèle qui n'a appris que sur les saisons précédentes et sans les compositions officielles. Ces chiffres sont donc une mesure honnête de ce qu'on peut attendre en réel.</div>` : "";
  h += `<div class="kpis">
    <div class="card pad kpi"><div class="lbl">Matchs évalués</div><div class="v">${(o.n || 0).toLocaleString("fr-FR")}</div><div class="sub">${S.sLeague ? META.leagues[S.sLeague].name : "Tous championnats"}</div></div>
    <div class="card pad kpi"><div class="lbl">Réussite (favori)${tip("accuracy")}</div><div class="v">${pct(o.accuracy, 1)}</div><div class="sub">Référence naïve ${pct(b.accuracy, 1)}${tip("baseline")}</div></div>
    <div class="card pad kpi"><div class="lbl">Brier (↓ mieux)${tip("brier")}</div><div class="v">${num(o.brier, 4)}</div><div class="sub">Référence ${num(b.brier, 4)}</div></div>
    <div class="card pad kpi"><div class="lbl">Log-loss (↓ mieux)${tip("logloss")}</div><div class="v">${num(o.logloss, 4)}</div><div class="sub">Référence ${num(b.logloss, 4)}</div></div>
  </div>`;
  if (!o.n) h += `<div class="card pad muted" style="margin-bottom:var(--gap)">Pas encore de match terminé avec pronostic pour cette sélection. Lancez un backtest pour obtenir une première mesure.</div>`;
  h += `<div class="cols">
    <div class="card pad"><h3 class="big">Par modèle</h3><div class="scroll-x"><table class="tbl">${head("Modèle")}
      ${row("Ensemble (final)", o, "hl")}${Object.entries(s.per_model).map(([k, x]) => row(esc(s.labels[k] || k) + tip(tipsModel[k]), x)).join("")}
      ${row(`<span class="muted">Référence naïve</span>${tip("baseline")}`, b)}</table></div></div>
    <div class="card pad"><h3 class="big">Par championnat</h3><div class="scroll-x"><table class="tbl">${head("Championnat")}
      ${Object.entries(s.per_league).map(([k, x]) => row(esc(META.leagues[k]?.name || k), x, S.sLeague === k ? "hl" : "")).join("")}</table></div></div>
    ${tiersCard(s.tiers)}
    ${ChartKit.card("s-calib", "Calibration", [["line", "Courbe"], ["bar", "Barres"]], { tipKey: "calibration", note: "Quand le modèle annonce X %, l'issue se produit-elle X % du temps ? Idéal : sur la diagonale." })}
    ${ChartKit.card("s-models", "Comparaison des modèles", [["bar", "Barres"], ["radar", "Radar"], ["polar", "Polaire"]], { tipKey: "logloss", note: "Réussite du favori par modèle (plus haut = mieux)." })}
    ${ChartKit.card("s-time", "Évolution mois par mois", [["line", "Lignes"], ["bar", "Barres"]], { tipKey: "accuracy" })}
    ${s.weights.meta ? `<div class="card pad"><h3 class="big">Modèle final appris${tip("meta")}</h3>
      <p class="muted" style="margin:0 0 10px;font-size:12.5px">Quand les cotes existent, le pronostic part des cotes (marge retirée) et applique ces corrections, apprises sur ${s.weights.meta.n.toLocaleString("fr-FR")} matchs.</p>
      <div class="grid" style="grid-template-columns:minmax(0,1fr) 70px">${s.weights.meta.features.map((f, i) => `<span>${esc(cap(f))}</span><span class="num r">${signed(s.weights.meta.beta[i], (x) => num(x, 3))}</span>`).join("")}
        <span>Poids des absences${tip("absRating")}</span><span class="num r">${num(s.weights.meta.gamma)}</span></div>
      <div class="note">Contrôle sur les 20 % de matchs les plus récents (jamais vus) : log-loss ${num(s.weights.meta.val_meta, 4)} contre ${num(s.weights.meta.val_market, 4)} pour les cotes seules. Un coefficient positif pousse la probabilité vers le haut ; « écart » = différence entre notre modèle et les cotes.</div></div>` : ""}
    <div class="card pad"><h3 class="big">Poids sans cotes${tip("weight")}</h3>
      ${[["with_market", "Avec cotes disponibles"], ["no_market", "Sans cotes (matchs lointains)"]].map(([p, title]) => `<div class="lbl" style="margin:4px 0 8px">${title}</div>
        <div class="grid" style="grid-template-columns:minmax(0,190px) minmax(0,1fr) 52px;align-items:center;margin-bottom:14px">
        ${Object.keys(s.labels).filter((k) => p === "with_market" || k !== "market").map((k) => `<span>${esc(s.labels[k])}</span>
          <span class="hbar blue" style="height:8px"><span style="width:${Math.min((s.weights[p][k] || 0) / .6 * 100, 100)}%"></span></span><span class="num r">${pct(s.weights[p][k], 1)}</span>`).join("")}
        <span class="muted">Netteté${tip("sharpness")}</span><span></span><span class="num r">${num(s.weights[p].sharpness)}</span></div>`).join("")}
      <div class="lbl" style="margin-bottom:8px">Coefficients d'ajustement${tip("coefs")}</div>
      <div class="grid" style="grid-template-columns:minmax(0,1fr) 52px">${Object.entries(s.coef_labels).map(([k, l]) => `<span>${esc(l)}</span><span class="num r">${num(s.params[k])}</span>`).join("")}</div>
    </div>
    ${ChartKit.card("s-weights", "Répartition des poids", [["doughnut", "Anneau"], ["pie", "Camembert"], ["bar", "Barres"]], { tipKey: "weight" })}
    ${ChartKit.card("s-whist", "Évolution des poids", [["line", "Lignes"], ["bar", "Empilé"]], { tipKey: "weight" })}
  </div>
  <div class="card pad scroll-x"><h3 class="big">Historique d'apprentissage${tip("validation")}</h3>
    ${s.history.length ? `<table class="tbl" style="min-width:1100px"><tr><th>Date</th><th>Échantillon</th><th>Log-loss avant → après</th>${Object.keys(s.labels).map((k) => `<th class="r">${k}</th>`).join("")}
      ${Object.keys(s.coef_labels).map((k) => `<th class="r" title="${esc(s.coef_labels[k])}">${k.replace(/_(beta|penalty)$/, "")}</th>`).join("")}</tr>
      ${s.history.map((x) => `<tr><td class="num">${dtF.format(new Date(x.created_at))}</td><td>${x.n_samples.toLocaleString("fr-FR")} <span class="muted">(${esc(x.note)})</span></td>
        <td class="num">${num(x.logloss_before, 4)} → ${num(x.logloss_after, 4)}</td>${Object.keys(s.labels).map((k) => `<td class="num r">${pct((x.weights.with_market || x.weights)[k])}</td>`).join("")}
        ${Object.keys(s.coef_labels).map((k) => `<td class="num r">${num(x.params[k])}</td>`).join("")}</tr>`).join("")}</table>`
      : `<p class="muted">Aucun apprentissage effectué (poids par défaut).</p>`}</div>`;
  $("#st").innerHTML = h;

  ChartKit.mount("s-calib", (type, c) => {
    if (!s.calibration.length) return null;
    const lab = s.calibration.map((x) => x.bin);
    if (type === "bar") return { type: "bar", data: { labels: lab, datasets: [
      { label: "Annoncé", data: s.calibration.map((x) => x.predicted * 100), backgroundColor: c.draw },
      { label: "Observé", data: s.calibration.map((x) => x.observed * 100), backgroundColor: c.home }] }, options: { scales: { y: { ticks: { callback: (v) => v + " %" } } } } };
    return { type: "scatter", data: { datasets: [
      { label: "Observé", data: s.calibration.map((x) => ({ x: x.predicted * 100, y: x.observed * 100, n: x.n })), borderColor: c.home, backgroundColor: c.home, showLine: true, pointRadius: 4 },
      { label: "Calibration parfaite", data: [{ x: 0, y: 0 }, { x: 100, y: 100 }], borderColor: c.muted, borderDash: [4, 4], showLine: true, pointRadius: 0 }] },
      options: { scales: { x: { min: 0, max: 100, title: { display: true, text: "Probabilité annoncée (%)" } }, y: { min: 0, max: 100, title: { display: true, text: "Fréquence observée (%)" } } },
        plugins: { tooltip: { callbacks: { label: (ctx) => ctx.raw.n ? `annoncé ${num(ctx.raw.x, 1)} % → observé ${num(ctx.raw.y, 1)} % (${ctx.raw.n} cas)` : "" } } } } };
  });
  ChartKit.mount("s-models", (type, c) => {
    const keys = Object.keys(s.per_model).filter((k) => s.per_model[k].n);
    if (!keys.length) return null;
    const lab = [...keys.map((k) => (s.labels[k] || k).split(" (")[0]), "Ensemble", "Référence"];
    const acc = [...keys.map((k) => s.per_model[k].accuracy), o.accuracy, b.accuracy].map((x) => x * 100);
    const cols = lab.map((_, i) => (i === lab.length - 2 ? c.fg : i === lab.length - 1 ? c.draw : c.series[i % 8]));
    if (type === "radar") return { type: "radar", data: { labels: lab, datasets: [{ label: "Réussite (%)", data: acc, borderColor: c.home, backgroundColor: ChartKit.alpha(c.home, .15) }] },
      options: { scales: { r: { suggestedMin: 35, ticks: { backdropColor: "transparent" }, grid: { color: c.line2 }, angleLines: { color: c.line2 } } } } };
    if (type === "polar") return { type: "polarArea", data: { labels: lab, datasets: [{ data: acc.map((x) => x - 30), backgroundColor: cols.map((x) => ChartKit.alpha(x, .7)) }] },
      options: { plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: (ctx) => `${ctx.label} : ${num(ctx.raw + 30, 1)} %` } } }, scales: { r: { ticks: { display: false }, grid: { color: c.line2 } } } } };
    return { type: "bar", data: { labels: lab, datasets: [{ label: "Réussite (%)", data: acc, backgroundColor: cols }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { suggestedMin: 35, ticks: { callback: (v) => v + " %" } } } } };
  });
  ChartKit.mount("s-time", (type, c) => {
    if (!s.timeline.length) return null;
    const lab = s.timeline.map((t) => t.month);
    return { type: type === "bar" ? "bar" : "line", data: { labels: lab, datasets: [
      { label: "Réussite (%)", data: s.timeline.map((t) => t.accuracy * 100), borderColor: c.home, backgroundColor: c.home, yAxisID: "y", tension: .25 },
      { label: "Log-loss", data: s.timeline.map((t) => t.logloss), borderColor: c.warn, backgroundColor: c.warn, yAxisID: "y1", tension: .25 }] },
      options: { scales: { y: { position: "left", ticks: { callback: (v) => v + " %" } }, y1: { position: "right", grid: { drawOnChartArea: false } } },
        plugins: { tooltip: { callbacks: { afterBody: (items) => `${s.timeline[items[0].dataIndex].n} matchs` } } } } };
  });
  ChartKit.mount("s-weights", (type, c) => {
    const p = s.weights.with_market;
    const keys = Object.keys(s.labels);
    const lab = keys.map((k) => s.labels[k].split(" (")[0]);
    if (type === "bar") return { type: "bar", data: { labels: lab, datasets: [
      { label: "Avec cotes", data: keys.map((k) => (s.weights.with_market[k] || 0) * 100), backgroundColor: c.home },
      { label: "Sans cotes", data: keys.map((k) => (s.weights.no_market[k] || 0) * 100), backgroundColor: c.draw }] }, options: { scales: { y: { ticks: { callback: (v) => v + " %" } } } } };
    return { type, data: { labels: lab, datasets: [{ label: "Avec cotes", data: keys.map((k) => (p[k] || 0) * 100), backgroundColor: keys.map((_, i) => c.series[i % 8]), borderColor: c.card }] },
      options: { plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: (ctx) => `${ctx.label} : ${num(ctx.raw, 1)} %` } } } } };
  });
  ChartKit.mount("s-whist", (type, c) => {
    const hist = [...s.history].reverse();
    if (hist.length < 2) return null;
    const keys = Object.keys(s.labels);
    return { type: type === "bar" ? "bar" : "line", data: { labels: hist.map((x) => dateF.format(new Date(x.created_at))), datasets: keys.map((k, i) => ({
      label: s.labels[k].split(" (")[0], data: hist.map((x) => ((x.weights.with_market || x.weights)[k] || 0) * 100), borderColor: c.series[i % 8], backgroundColor: c.series[i % 8], tension: .2 })) },
      options: { scales: { x: { stacked: type === "bar" }, y: { stacked: type === "bar", ticks: { callback: (v) => v + " %" } } } } };
  });
}

/* ================================================================== HISTORIQUE */
async function viewHistory(v) {
  v.innerHTML = `<main class="page"><div class="kicker">Historique</div><h1 class="title">Pronostics évalués</h1>
    <div class="subtitle" id="hi-sum" style="margin-bottom:18px"></div>
    <div class="filters">${seg([["live", "Pronostics réels"], ["backtest", "Backtest"]], S.hSource, "hsource")}${chips(S.hLeague, "hleague")}</div>
    <div class="card scroll-x" id="hi"><div class="pad muted" style="padding:14px">Chargement…</div></div></main>`;
  bind("hsource", (k) => { S.hSource = k; render(); });
  bind("hleague", (k) => { S.hLeague = k; render(); });
  const rows = await api(`/api/history?source=${S.hSource}&league=${S.hLeague}&limit=300`);
  const ok = rows.filter((r) => r.correct).length;
  $("#hi-sum").textContent = rows.length ? `${rows.length} matchs · ${ok} favoris trouvés (${pct(ok / rows.length)})` : "Aucun pronostic évalué pour cette sélection.";
  $("#hi").innerHTML = rows.length ? `<table class="tbl" style="min-width:880px"><tr><th>Date</th><th>Championnat</th><th>Match</th><th class="r t-home">1</th><th class="r">N</th><th class="r t-ko">2</th><th class="c">Prono</th><th class="c">Score</th><th></th></tr>
    ${rows.map((r) => { const pk = "HDA".indexOf(r.pick); return `<tr><td class="num muted">${dateF.format(new Date(r.kickoff))}</td><td class="muted">${esc(META.leagues[r.league]?.name)}</td>
      <td style="font-weight:600">${esc(r.home)} – ${esc(r.away)}</td>${r.p.map((x, i) => `<td class="num r" style="font-weight:${i === pk ? 700 : 400}">${pct(x)}</td>`).join("")}
      <td class="num c" style="font-weight:700">${OUT[r.pick]}</td><td class="num c">${r.score}</td><td style="font-weight:700;color:${r.correct ? "var(--ok)" : "var(--ko)"}">${r.correct ? "✔" : "✘"}</td></tr>`; }).join("")}</table>` : "";
}

/* ================================================================== LEXIQUE */
function viewGlossary(v) {
  v.innerHTML = `<main class="page"><div class="head"><div class="kicker">Lexique</div><h1 class="title">Comprendre les chiffres</h1>
    <div class="subtitle">Toutes les notes explicatives de l'application. Elles apparaissent aussi au survol des petits « ? ».</div></div>
    <div class="glossary">${Object.values(GLOSSARY).map(([t, d]) => `<div class="card pad"><h3>${esc(t)}</h3><p>${esc(d)}</p></div>`).join("")}</div></main>`;
}

/* ================================================================== démarrage */
(async () => {
  setTheme(S.theme);
  renderTabs();
  await loadMeta();
  await loadMatches();
  render();
  pollStatus();
  startLive();
  startAlerts();
  // Synchro horaire côté serveur : on suit les tâches lancées automatiquement et on recharge
  // les données dès qu'une nouvelle synchro (ou une composition officielle) est disponible.
  let lastSeen = META.last_update;
  setInterval(async () => {
    try {
      const st = await api("/api/status");
      if (st.running && !polling) return pollStatus();
      const meta = await api("/api/meta");
      if (meta.last_update !== lastSeen) {
        lastSeen = meta.last_update;
        await loadMeta();
        await loadMatches();
        if (S.tab === "matches") render();
      }
    } catch (e) { /* serveur indisponible : on réessaie au prochain tour */ }
  }, 120000);
})();
