"""Conseiller : quoi parier (ou ne rien faire) sur les matchs à venir.

- Applique la stratégie active (réglages de la bankroll, idéalement choisie par l'optimiseur)
  aux pronostics des matchs à venir, avec la meilleure cote disponible.
- Donne la mise conseillée (bankroll de la simulation), les raisons, et explique pourquoi
  les autres matchs sont à éviter.
- Suit ses propres résultats : les paris du conseiller sont ceux du carnet « auto ».
"""
import json
import time

import numpy as np

from . import bankroll, learning, odds_tracker
from .config import LEAGUES, MODEL_LABELS, current_season
from .dataset import parse_ts

SEL_LABEL = {"H": "Victoire {home}", "D": "Match nul", "A": "Victoire {away}", "O": "Plus de 2,5 buts", "U": "Moins de 2,5 buts"}
TIERS = (0.0, 0.5, 0.6, 0.7)


def confidence_tiers(samples: list[dict]) -> list[dict]:
    """Taux de réussite du pronostic selon la probabilité du favori."""
    out = []
    for lo in TIERS:
        sel = [s for s in samples if max(s["p_home"], s["p_draw"], s["p_away"]) >= lo]
        if sel:
            acc = float(np.mean([int(np.argmax([s["p_home"], s["p_draw"], s["p_away"]]) == s["y"]) for s in sel]))
            out.append({"min": lo, "n": len(sel), "accuracy": acc, "share": len(sel) / len(samples)})
    return out


def tier_of(p: float, tiers: list[dict]) -> dict | None:
    best = None
    for t in tiers:
        if p >= t["min"]:
            best = t
    return best


def _reasons(d: dict, v: dict, move: dict | None) -> list[str]:
    out = []
    models = d.get("models") or {}
    if v["market"] == "1X2":
        i = "HDA".index(v["outcome"])
        mk = models.get("market")
        own = [(k, p[i]) for k, p in models.items() if p and k != "market"]
        if mk and own:
            avg = sum(p for _, p in own) / len(own)
            if avg > mk[i] + 0.02:
                out.append(f"Nos modèles ({', '.join(MODEL_LABELS[k].split(' (')[0] for k, _ in own)}) donnent {avg * 100:.0f} % contre {mk[i] * 100:.0f} % pour le marché.")
        if move:
            dlt = move["delta"][i]
            if abs(dlt) >= 0.01:
                out.append(f"Cotes {'en baisse' if dlt > 0 else 'en hausse'} depuis le premier relevé "
                           f"({'+' if dlt > 0 else ''}{dlt * 100:.1f} pts de probabilité) : "
                           + ("le marché va dans notre sens." if dlt > 0 else "le marché s'éloigne, prudence."))
    else:
        out.append(f"Buts attendus {d['poisson']['lh']:.2f} - {d['poisson']['la']:.2f} (modèle Poisson), "
                   f"proba {'+' if v['outcome'] == 'O' else '−'}2,5 = {v['p'] * 100:.0f} %.")
    adj = d.get("adj") or {}
    for s, lbl in (("h", "domicile"), ("a", "extérieur")):
        if (adj.get(f"abs_rating_{s}") or 0) >= 0.1:
            out.append(f"Absences importantes côté {lbl} ({adj[f'abs_rating_{s}'] * 100:.0f} % de la qualité de l'effectif).")
    if (d.get("details") or {}).get("lineup_confirmed"):
        out.append("Composition officielle prise en compte.")
    return out


def advise(conn) -> dict:
    s = bankroll.settings(conn)
    bank = bankroll.current_bank(conn, "auto")
    now = time.time()
    rows = conn.execute("""SELECT p.data, p.updated_at, m.* FROM predictions p JOIN matches m ON m.id = p.match_id
                           WHERE p.source='live' AND m.is_result=0 ORDER BY m.kickoff""").fetchall()
    samples = learning.collect(conn, ("backtest", "live"))
    tiers = confidence_tiers(samples)
    recs, skips, safest = [], [], []
    for r in rows:
        ts = parse_ts(r["kickoff"])
        if ts <= now:
            continue
        d = json.loads(r["data"])
        m = {k: r[k] for k in ("id", "league", "kickoff", "home", "away", "home_id", "away_id")}
        m["league_name"] = LEAGUES[r["league"]]["name"]
        pmax = max(d["final"])
        pick = "HDA"[d["final"].index(pmax)]
        t = tier_of(pmax, tiers)
        safest.append({"match": m, "pick": pick, "label": SEL_LABEL[pick].format(**m), "p": pmax,
                       "tier_accuracy": t["accuracy"] if t else None, "tier_n": t["n"] if t else None})
        move = odds_tracker.history(conn, r["id"])["move"]
        chosen, best_other = [], None
        for v in d.get("value", []):
            if bankroll.selectable(v["market"], v["p"], v["odds"], v["edge"], s):
                stake = bankroll.stake_for(v["p"], v["odds"], bank, s)
                if stake > 0:
                    chosen.append({"match": m, "market": v["market"], "selection": v["outcome"],
                                   "label": SEL_LABEL[v["outcome"]].format(**m), "odds": v["odds"], "bookmaker": v["bookmaker"],
                                   "p": v["p"], "edge": v["edge"], "stake": stake, "stake_pct": stake / bank if bank else 0,
                                   "expected_profit": stake * v["edge"], "potential_win": stake * (v["odds"] - 1),
                                   "reasons": _reasons(d, v, move), "lineup_confirmed": bool(d["details"].get("lineup_confirmed"))})
            elif best_other is None or v["edge"] > best_other["edge"]:
                best_other = v
        if chosen:
            # un seul pari par match : celui au meilleur gain espéré
            recs.append(max(chosen, key=lambda c: c["expected_profit"]))
        else:
            if not d.get("value"):
                why = "Pas encore de cotes pour ce match."
            elif best_other is None:
                why = "Aucun pari disponible."
            elif best_other["edge"] <= 0:
                why = f"Aucune cote au-dessus de la « juste » cote (meilleur avantage {best_other['edge'] * 100:+.1f} %)."
            elif best_other["market"] not in s["markets"]:
                why = f"Seul avantage sur un marché non retenu par la stratégie ({'±2,5 buts' if best_other['market'] == 'OU25' else '1N2'}, {best_other['edge'] * 100:+.1f} %)."
            elif best_other["edge"] < s["min_edge"]:
                why = f"Avantage trop faible ({best_other['edge'] * 100:+.1f} % < {s['min_edge'] * 100:.0f} % requis)."
            elif best_other["odds"] > s["max_odds"]:
                why = f"Cote trop élevée ({best_other['odds']:.2f} > {s['max_odds']:g}) : trop risqué."
            else:
                why = f"Probabilité trop faible ({best_other['p'] * 100:.0f} % < {s['min_prob'] * 100:.0f} % requis)."
            skips.append({"match": m, "reason": why, "p": d["final"], "pick": pick})
    safest.sort(key=lambda x: -x["p"])

    auto = bankroll.summary(conn, "auto")
    hist = bankroll.load_history(conn)
    season = current_season()
    sim_prev = bankroll.simulate_rows(hist, s, date_to=f"{season}-07-01")["kpis"]
    sim_cur = bankroll.simulate_rows(hist, s, date_from=f"{season}-07-01")["kpis"]
    slim = lambda k: {x: k.get(x) for x in ("n_settled", "won", "hit_rate", "yield", "roi", "max_drawdown", "profit", "staked", "clv", "clv_n")}
    lineup = bankroll.summary(conn, "lineup")["kpis"]
    n_events = conn.execute("SELECT COUNT(*) FROM lineup_events").fetchone()[0]
    overall_acc = next((t["accuracy"] for t in tiers if t["min"] == 0.0), None)
    return {
        "settings": s, "strategy": s.get("strategy_label") or bankroll.strategy_label(s), "bank": bank,
        "recommendations": recs, "skips": skips, "safest": safest[:10], "tiers": tiers,
        "total_stake": sum(r["stake"] for r in recs), "expected_profit": sum(r["expected_profit"] for r in recs),
        "track": {"live": slim(auto["kpis"]), "backtest_prev": slim(sim_prev), "backtest_cur": slim(sim_cur),
                  "lineup": slim(lineup), "lineup_events": n_events,
                  "overall_accuracy": overall_acc, "season": season},
    }
