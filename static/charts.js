"use strict";
/* Cartes graphiques avec choix du type de graphique (mémorisé par graphique). */
const ChartKit = (() => {
  const instances = {};
  const builders = {};
  let prefs = {};
  try { prefs = JSON.parse(localStorage.getItem("pf-chart-types") || "{}"); } catch (e) { prefs = {}; }
  const savePrefs = () => { try { localStorage.setItem("pf-chart-types", JSON.stringify(prefs)); } catch (e) { /* stockage indisponible */ } };

  function colors() {
    const cs = getComputedStyle(document.getElementById("app"));
    const v = (n) => cs.getPropertyValue(n).trim();
    return { home: v("--home"), draw: v("--draw"), away: v("--away"), ok: v("--ok"), ko: v("--ko"), warn: v("--warn"),
      value: v("--value"), fg: v("--fg"), muted: v("--muted"), line: v("--line"), line2: v("--line2"), card: v("--card"),
      series: [v("--home"), v("--away"), v("--value"), v("--ok"), v("--warn"), v("--draw"), "#06b6d4", "#ec4899"] };
  }

  function alpha(hex, a) {
    const h = hex.replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  /** HTML d'une carte graphique. types = [[clé, libellé], ...] */
  function card(id, title, types, { tipKey = "", size = "", note = "" } = {}) {
    const cur = prefs[id] && types.some(([k]) => k === prefs[id]) ? prefs[id] : types[0][0];
    return `<div class="card pad" data-chart="${id}">
      <div class="chart-head"><h3>${title}${tipKey ? tip(tipKey) : ""}</h3>
        ${types.length > 1 ? `<div class="seg small" role="group" aria-label="Type de graphique">${types.map(([k, l]) =>
          `<button data-ctype="${k}" class="${k === cur ? "on" : ""}" title="Afficher en ${l.toLowerCase()}">${l}</button>`).join("")}</div>` : ""}
      </div>
      <div class="chart-box ${size}"><canvas></canvas></div>
      ${note ? `<div class="note">${note}</div>` : ""}
    </div>`;
  }

  function render(id) {
    const el = document.querySelector(`[data-chart="${id}"]`);
    if (!el || !builders[id]) return;
    const btns = [...el.querySelectorAll("[data-ctype]")];
    const type = (btns.find((b) => b.classList.contains("on")) || {}).dataset?.ctype || prefs[id];
    if (instances[id]) { instances[id].destroy(); delete instances[id]; }
    const box = el.querySelector(".chart-box");
    const cfg = builders[id](type, colors());
    if (!cfg) { box.innerHTML = `<p class="muted">Pas assez de données pour ce graphique.</p>`; return; }
    if (cfg.html !== undefined) { box.style.height = "auto"; box.innerHTML = cfg.html; return; }
    box.style.height = "";
    if (!box.querySelector("canvas")) box.innerHTML = "<canvas></canvas>";
    if (typeof Chart === "undefined") { box.innerHTML = `<p class="muted">Bibliothèque de graphiques non chargée (connexion internet requise).</p>`; return; }
    const c = colors();
    Chart.defaults.font.family = "'IBM Plex Mono', ui-monospace, monospace";
    Chart.defaults.font.size = 11;
    Chart.defaults.color = c.muted;
    Chart.defaults.borderColor = c.line2;
    cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false, animation: { duration: 250 } }, cfg.options || {});
    cfg.options.plugins = Object.assign({ legend: { labels: { boxWidth: 10, boxHeight: 10 } },
      tooltip: { backgroundColor: c.fg, titleColor: c.card, bodyColor: c.card, padding: 8, cornerRadius: 3 } }, cfg.options.plugins || {});
    instances[id] = new Chart(box.querySelector("canvas"), cfg);
  }

  /** Enregistre le constructeur de config puis dessine. builder(type, colors) -> config Chart.js | {html} | null */
  function mount(id, builder) {
    builders[id] = builder;
    const el = document.querySelector(`[data-chart="${id}"]`);
    if (!el) return;
    el.querySelectorAll("[data-ctype]").forEach((b) => b.addEventListener("click", () => {
      el.querySelectorAll("[data-ctype]").forEach((x) => x.classList.toggle("on", x === b));
      prefs[id] = b.dataset.ctype;
      savePrefs();
      render(id);
    }));
    render(id);
  }

  function redrawAll() { Object.keys(builders).forEach((id) => { if (document.querySelector(`[data-chart="${id}"]`)) render(id); }); }

  return { card, mount, redrawAll, colors, alpha };
})();
