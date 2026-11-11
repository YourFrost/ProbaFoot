"""Suivi de bankroll.

Deux carnets :
- 'manual' : les paris réellement joués, saisis par l'utilisateur ;
- 'auto'   : simulation — le programme « parie » automatiquement chaque value bet détecté
             (mise selon la stratégie choisie), mise figée au coup d'envoi.
Les paris sont réglés automatiquement quand le résultat arrive.
"""
import json
from collections import defaultdict

from .db import get_meta, now_iso, set_meta
from . import models
from .predict import best_odds

DEFAULT_SETTINGS = {
    "initial": 1000.0,        # bankroll de départ (€)
    "staking": "kelly",       # 'kelly' (fraction de Kelly) ou 'flat' (% fixe de la bankroll)
    "kelly_fraction": 0.25,   # quart de Kelly : réduit fortement la variance
    "flat_pct": 0.01,         # 1 % de la bankroll par pari en mise fixe
    "max_stake_pct": 0.05,    # plafond de mise par pari
    "min_edge": 0.06,         # avantage minimum pour parier
    "max_odds": 4.0,          # au-delà, les « avantages » sont presque toujours des erreurs du modèle
    "min_prob": 0.0,          # probabilité minimale du pari selon le modèle
    "markets": ["1X2"],       # le +/-2.5 perdait en backtest : désactivé par défaut
    "auto": True,
    "strategy_label": "1N2 · avantage ≥ 6 % · cote ≤ 4 · ¼ Kelly (meilleure stratégie sur 7 saisons)",
}


def selectable(market: str, p: float, odds: float, edge: float, s: dict) -> bool:
    """Le pari respecte-t-il la stratégie ?"""
    return (market in s["markets"] and edge >= s["min_edge"] and odds <= s["max_odds"]
            and p >= s.get("min_prob", 0.0) and edge > 0)


def settings(conn) -> dict:
    stored = get_meta(conn, "bankroll_settings", {}) or {}
    s = {**DEFAULT_SETTINGS, **stored}
    if stored and not stored.get("strategy_label"):   # réglages personnalisés : libellé décrivant ces réglages
        s["strategy_label"] = "Réglages personnalisés : " + strategy_label(s)
    return s


def save_settings(conn, new: dict) -> dict:
    s = {**settings(conn), **{k: v for k, v in new.items() if k in DEFAULT_SETTINGS}}
    set_meta(conn, "bankroll_settings", s)
    return s


def stake_for(p: float, odds: float, bank: float, s: dict) -> float:
    if s["staking"] == "flat":
        frac = s["flat_pct"]
    else:
        kelly = (p * odds - 1) / (odds - 1) if odds > 1 else 0
        frac = max(kelly, 0) * s["kelly_fraction"]
    return round(max(min(frac, s["max_stake_pct"]) * max(bank, 0), 0), 2)


def current_bank(conn, book: str) -> float:
    s = settings(conn)
    profit = conn.execute("SELECT COALESCE(SUM(profit), 0) FROM bets WHERE book=? AND status IN ('won','lost')",
                          (book,)).fetchone()[0]
    return s["initial"] + profit


def update_auto_bets(conn, match_id: str, pred: dict, book: str = "auto") -> dict | None:
    """Place le pari simulé du conseiller pour un match à venir. Comme un vrai parieur, le pari
    est pris une fois (au premier conseil) puis figé : sa cote pourra être comparée à la cote
    de clôture (CLV). book='lineup' = carnet de test des paris pris juste après la composition."""
    s = settings(conn)
    if not s["auto"]:
        return None
    if conn.execute("SELECT 1 FROM bets WHERE book=? AND match_id=?", (book, match_id)).fetchone():
        return None
    bank = current_bank(conn, book)
    cands = [(stake_for(v["p"], v["odds"], bank, s), v) for v in pred.get("value", [])
             if selectable(v["market"], v["p"], v["odds"], v["edge"], s)]
    cands = [(st, v) for st, v in cands if st > 0]
    if cands:  # un seul pari par match (meilleur gain espéré), comme le conseiller
        stake, v = max(cands, key=lambda c: c[0] * c[1]["edge"])
        conn.execute("""INSERT INTO bets(book, created_at, match_id, market, selection, odds, stake, bookmaker,
                        p_model, edge, status) VALUES(?,?,?,?,?,?,?,?,?,?,'pending')""",
                     (book, now_iso(), match_id, v["market"], v["outcome"], v["odds"], stake, v["bookmaker"], v["p"], v["edge"]))
        return {**v, "stake": stake}
    return None


def reset_pending_auto(conn):
    """Après un changement de stratégie : les paris simulés pas encore joués sont recalculés."""
    conn.execute("DELETE FROM bets WHERE book='auto' AND status='pending' AND match_id IN "
                 "(SELECT id FROM matches WHERE is_result=0 AND kickoff > strftime('%Y-%m-%dT%H:%M:%SZ','now'))")


def _won(market: str, sel: str, hg: int, ag: int) -> bool:
    if market == "1X2":
        return sel == ("H" if hg > ag else "D" if hg == ag else "A")
    total = hg + ag
    return total > 2.5 if sel == "O" else total < 2.5


def closing_prob(conn, match_id: str, kickoff: str, market: str, selection: str) -> float | None:
    """Probabilité « juste » de clôture : dernières cotes relevées avant le coup d'envoi
    (moyenne des bookmakers suivis, marge retirée), sinon cotes de clôture football-data."""
    if market == "1X2":
        last = {}
        for r in conn.execute("SELECT bookmaker, h, d, a FROM odds_history WHERE match_id=? AND ts<=? ORDER BY ts", (match_id, kickoff)):
            last[r["bookmaker"]] = (r["h"], r["d"], r["a"])
        if last:
            ps = [models.devig(list(o)) for o in last.values() if all(o)]
            if ps:
                return float(sum(p["HDA".index(selection)] for p in ps) / len(ps))
    r = conn.execute("SELECT * FROM odds_closing WHERE match_id=?", (match_id,)).fetchone()
    if not r:
        return None
    if market == "1X2":
        return float(models.devig([r["h"], r["d"], r["a"]])["HDA".index(selection)])
    if r["over25"] and r["under25"]:
        po = (1 / r["over25"]) / (1 / r["over25"] + 1 / r["under25"])
        return po if selection == "O" else 1 - po
    return None


def settle(conn) -> int:
    rows = conn.execute("""SELECT b.id, b.match_id, b.market, b.selection, b.odds, b.stake, m.hg, m.ag, m.kickoff FROM bets b
                           JOIN matches m ON m.id = b.match_id
                           WHERE b.status='pending' AND m.is_result=1 AND m.hg IS NOT NULL""").fetchall()
    for r in rows:
        won = _won(r["market"], r["selection"], r["hg"], r["ag"])
        profit = round(r["stake"] * (r["odds"] - 1), 2) if won else -r["stake"]
        pc = closing_prob(conn, r["match_id"], r["kickoff"], r["market"], r["selection"])
        conn.execute("UPDATE bets SET status=?, profit=?, settled_at=?, closing_odds=?, clv=? WHERE id=?",
                     ("won" if won else "lost", profit, now_iso(), None if not pc else 1 / pc,
                      None if not pc else r["odds"] * pc - 1, r["id"]))
    return len(rows)


def _kpis(bets: list[dict], initial: float) -> dict:
    settled = [b for b in bets if b["status"] in ("won", "lost")]
    staked = sum(b["stake"] for b in settled)
    profit = sum(b["profit"] for b in settled)
    equity, peak, dd = initial, initial, 0.0
    curve = [{"date": None, "bank": initial}]
    for b in sorted(settled, key=lambda b: b["kickoff"]):
        equity += b["profit"]
        peak = max(peak, equity)
        dd = max(dd, (peak - equity) / peak if peak > 0 else 0)
        curve.append({"date": b["kickoff"], "bank": round(equity, 2)})
    return {
        "n_bets": len(bets), "n_settled": len(settled), "n_pending": len(bets) - len(settled),
        "won": sum(1 for b in settled if b["status"] == "won"),
        "hit_rate": (sum(1 for b in settled if b["status"] == "won") / len(settled)) if settled else None,
        "staked": round(staked, 2), "profit": round(profit, 2),
        "roi": profit / initial if initial else None,          # rendement sur la bankroll de départ
        "yield": profit / staked if staked else None,           # rendement par euro misé
        "bank": round(initial + profit, 2), "max_drawdown": dd,
        "avg_odds": (sum(b["odds"] for b in settled) / len(settled)) if settled else None,
        # CLV : cote prise comparée à la cote « juste » de clôture (>0 = on a battu le marché)
        "clv": (lambda v: sum(v) / len(v) if v else None)([b["clv"] for b in bets if b.get("clv") is not None]),
        "clv_n": sum(1 for b in bets if b.get("clv") is not None),
        "curve": curve,
    }


def _breakdown(bets: list[dict]) -> dict:
    out = {}
    for key, fn in (("league", lambda b: b["league"]), ("market", lambda b: b["market"]),
                    ("edge", lambda b: "5–10 %" if b["edge"] < 0.10 else "10–20 %" if b["edge"] < 0.20 else "≥ 20 %"),
                    ("bookmaker", lambda b: b["bookmaker"] or "–")):
        agg = defaultdict(lambda: {"n": 0, "staked": 0.0, "profit": 0.0})
        for b in bets:
            if b["status"] in ("won", "lost") and (key != "edge" or b["edge"] is not None):
                a = agg[fn(b)]
                a["n"] += 1
                a["staked"] += b["stake"]
                a["profit"] += b["profit"]
        out[key] = {k: {**v, "yield": v["profit"] / v["staked"] if v["staked"] else None} for k, v in agg.items()}
    return out


def summary(conn, book: str) -> dict:
    s = settings(conn)
    bets = [dict(r) for r in conn.execute(
        """SELECT b.*, m.home, m.away, m.league, m.kickoff, m.hg, m.ag FROM bets b
           JOIN matches m ON m.id = b.match_id WHERE b.book=? ORDER BY m.kickoff DESC""", (book,))]
    return {"settings": s, "bets": bets, "kpis": _kpis(bets, s["initial"]), "breakdown": _breakdown(bets)}


def load_history(conn, sources=("backtest", "live")) -> list[dict]:
    """Pronostics passés + meilleures cotes historiques, prêts à rejouer (chargés une seule fois)."""
    books = defaultdict(dict)
    for r in conn.execute("SELECT * FROM odds_books"):
        books[r["match_id"]][r["bookmaker"]] = dict(r)
    closing = {}
    for r in conn.execute("SELECT * FROM odds_closing"):
        pc = models.devig([r["h"], r["d"], r["a"]])
        po = (1 / r["over25"]) / (1 / r["over25"] + 1 / r["under25"]) if r["over25"] and r["under25"] else None
        closing[r["match_id"]] = {"H": pc[0], "D": pc[1], "A": pc[2], "O": po, "U": None if po is None else 1 - po}
    rows = conn.execute(
        f"""SELECT p.match_id, p.source, p.p_home, p.p_draw, p.p_away, p.data, m.kickoff, m.league,
                   m.home, m.away, m.hg, m.ag FROM predictions p JOIN matches m ON m.id = p.match_id
            WHERE m.is_result=1 AND m.hg IS NOT NULL AND p.source IN ({','.join('?' * len(sources))})
            ORDER BY m.kickoff, p.source DESC""", sources).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["match_id"] in seen:   # un seul pronostic par match ('live' trié avant 'backtest')
            continue
        seen.add(r["match_id"])
        best = best_odds(books.get(r["match_id"]))
        if not best:
            continue
        data = json.loads(r["data"])
        # backtest : pronostic sans la composition officielle (inconnue quand les cotes sont relevées)
        sim = data.get("sim") if r["source"] == "backtest" else None
        final = sim["final"] if sim else [r["p_home"], r["p_draw"], r["p_away"]]
        ou = sim["over25"] if sim else data.get("over25")
        if ou is None:
            ou = ((data.get("poisson") or {}).get("markets") or {}).get("over25")
        cands = [("1X2", sel, final[i], k) for i, (k, sel) in enumerate((("h", "H"), ("d", "D"), ("a", "A")))]
        if ou is not None:
            cands += [("OU25", "O", ou, "over25"), ("OU25", "U", 1 - ou, "under25")]
        cl = closing.get(r["match_id"], {})
        opts = [(mk, sel, p, *best[k], cl.get(sel)) for mk, sel, p, k in cands if k in best]
        out.append({k: r[k] for k in ("match_id", "kickoff", "league", "home", "away", "hg", "ag")} | {"opts": opts})
    return out


def simulate_rows(hist: list[dict], s: dict, date_from: str | None = None, date_to: str | None = None) -> dict:
    bank, bets = s["initial"], []
    for r in hist:
        if (date_from and r["kickoff"] < date_from) or (date_to and r["kickoff"] >= date_to):
            continue
        cands = []
        for market, sel, p, o, book, pclose in r["opts"]:
            edge = p * o - 1
            if selectable(market, p, o, edge, s):
                stake = stake_for(p, o, bank, s)
                if stake > 0:
                    cands.append((stake * edge, market, sel, p, o, book, edge, stake, pclose))
        if cands:  # un seul pari par match : le meilleur gain espéré
            _, market, sel, p, o, book, edge, stake, pclose = max(cands, key=lambda c: c[0])
            won = _won(market, sel, r["hg"], r["ag"])
            profit = round(stake * (o - 1), 2) if won else -stake
            bank += profit
            bets.append({"match_id": r["match_id"], "kickoff": r["kickoff"], "league": r["league"],
                         "home": r["home"], "away": r["away"], "hg": r["hg"], "ag": r["ag"], "market": market,
                         "selection": sel, "odds": o, "bookmaker": book, "stake": stake, "p_model": p,
                         "edge": edge, "status": "won" if won else "lost", "profit": profit,
                         "clv": None if pclose is None else o * pclose - 1})
    return {"settings": s, "kpis": _kpis(bets, s["initial"]), "breakdown": _breakdown(bets), "bets": bets[::-1]}


def simulate(conn, s: dict, sources=("backtest", "live"), date_from: str | None = None, date_to: str | None = None) -> dict:
    """Rejoue la stratégie sur les pronostics passés avec les cotes historiques des bookmakers."""
    return simulate_rows(load_history(conn, sources), s, date_from, date_to)


def strategy_label(s: dict) -> str:
    mk = " + ".join({"1X2": "1N2", "OU25": "±2,5 buts"}[m] for m in s["markets"])
    if s["staking"] == "kelly":
        stake = "¼ Kelly" if s["kelly_fraction"] == 0.25 else f"Kelly × {s['kelly_fraction']}"
    else:
        stake = f"mise fixe {s['flat_pct'] * 100:.0f} %"
    parts = [mk, f"avantage ≥ {s['min_edge'] * 100:.0f} %", f"cote ≤ {s['max_odds']:g}"]
    if s.get("min_prob"):
        parts.append(f"proba ≥ {s['min_prob'] * 100:.0f} %")
    return " · ".join(parts + [stake])


def optimize(conn, season: int) -> dict:
    """Cherche les meilleures stratégies sur la saison précédente (sans biais de composition),
    puis les vérifie sur la saison en cours. Score = yield, pénalisé quand il y a peu de paris."""
    base = settings(conn)
    hist = load_history(conn)
    cut = f"{season}-07-01"
    grid = []
    for markets in (["1X2"], ["OU25"], ["1X2", "OU25"]):
        for min_edge in (0.0, 0.01, 0.02, 0.04, 0.06):
            for max_odds in (1.8, 2.5, 4.0, 8.0):
                for min_prob in (0.0, 0.35, 0.5):
                    for staking in ("kelly", "flat"):
                        grid.append({**base, "markets": markets, "min_edge": min_edge, "max_odds": max_odds,
                                     "min_prob": min_prob, "staking": staking, "kelly_fraction": 0.25, "flat_pct": 0.01})
    results = []
    for g in grid:
        k = simulate_rows(hist, g, date_to=cut)["kpis"]
        if k["n_settled"] < 150 or k["yield"] is None:
            continue
        # Classement : la CLV (écart à la cote de clôture) prédit le rendement réel avec beaucoup
        # moins de hasard que les gains observés ; on exige en plus un rendement passé positif.
        if k.get("clv") is None or k["clv_n"] < 100:
            continue
        results.append((k["clv"] + 0.25 * k["yield"] * k["n_settled"] / (k["n_settled"] + 400), g, k))
    results.sort(key=lambda x: -x[0])

    def slim(x):
        return {kk: x[kk] for kk in ("n_settled", "won", "hit_rate", "staked", "profit", "roi", "yield", "max_drawdown", "avg_odds", "clv")}

    top, seen = [], set()
    for score, g, k in results:
        key = (k["n_settled"], round(k["profit"], 2), g["staking"])  # stratégies équivalentes = mêmes paris
        if key in seen:
            continue
        seen.add(key)
        check = simulate_rows(hist, g, date_from=cut)["kpis"]
        top.append({"settings": {kk: g[kk] for kk in ("markets", "min_edge", "max_odds", "min_prob", "staking", "kelly_fraction", "flat_pct")},
                    "label": strategy_label(g), "score": score, "train": slim(k), "check": slim(check),
                    "curve": k["curve"][:: max(1, len(k["curve"]) // 150)]})
        if len(top) >= 8:
            break
    profitable = [t for t in top if t["train"]["yield"] > 0 and (t["train"]["clv"] or 0) > 0]
    return {"strategies": top, "n_tested": len(grid),
            "train_period": "toutes les saisons passées (pronostics appris sans connaître la suite)",
            "check_period": f"saison {season}/{(season + 1) % 100:02d}",
            "verdict": ("Aucune stratégie ne bat à la fois la cote de clôture et le hasard sur l'historique : le plus sage "
                        "est de ne pas parier (ou de très petites mises pour tester)." if not profitable else
                        "Stratégies classées selon leur capacité à battre la cote de clôture (CLV), l'indicateur le plus "
                        "fiable du rendement réel. Attendez-vous à un rendement proche de la CLV, pas du rendement passé.")}
