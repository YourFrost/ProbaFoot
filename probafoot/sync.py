"""Synchronisation des données et rafraîchissement des pronostics."""
import logging
import math
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import json

from . import absences, alerts, bankroll, context, models, odds_tracker
from .config import CACHE_TTL_CURRENT, HISTORY_SEASONS, LEAGUES, current_season
from .dataset import Dataset, parse_ts
from .db import get_meta, now_iso, set_meta
from .learning import current_model
from .names import similarity
from .predict import predict_match, save_prediction
from .sources import footballdata, understat

log = logging.getLogger(__name__)


def _f(v):
    return float(v) if v not in (None, "") else None


def ingest_league(conn, league: str, season: int, d: dict):
    ts = now_iso()
    rows = []
    for m in d["dates"]:
        res = bool(m["isResult"])
        rows.append((m["id"], league, season, m["datetime"].replace(" ", "T") + "Z",
                     m["h"]["id"], m["h"]["title"], m["a"]["id"], m["a"]["title"], int(res),
                     int(m["goals"]["h"]) if res else None, int(m["goals"]["a"]) if res else None,
                     _f(m["xG"]["h"]) if res else None, _f(m["xG"]["a"]) if res else None, ts))
    conn.executemany(
        """INSERT INTO matches(id, league, season, kickoff, home_id, home, away_id, away, is_result,
               hg, ag, hxg, axg, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET kickoff=excluded.kickoff, is_result=excluded.is_result,
               hg=excluded.hg, ag=excluded.ag, hxg=excluded.hxg, axg=excluded.axg,
               updated_at=excluded.updated_at""", rows)

    # xG sans penalty et points attendus depuis l'historique par équipe
    for team in d["teams"].values():
        for h in team["history"]:
            kickoff = h["date"].replace(" ", "T") + "Z"
            side = "h" if h["h_a"] == "h" else "a"
            col = "home_id" if side == "h" else "away_id"
            conn.execute(f"UPDATE matches SET {side}npxg=?, {side}xpts=? WHERE league=? AND kickoff=? AND {col}=?",
                         (_f(h.get("npxG")), _f(h.get("xpts")), league, kickoff, team["id"]))

    conn.execute("DELETE FROM players WHERE league=? AND season=?", (league, season))
    conn.executemany("INSERT OR REPLACE INTO players VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", [
        (league, season, p["id"], p["player_name"], p["team_title"], p["position"], int(p["games"]),
         int(p["time"]), int(p["goals"]), float(p["xG"]), int(p["assists"]), float(p["xA"]))
        for p in d["players"]])


def attach_odds(conn, league: str, rows: list[dict]) -> int:
    by_date = defaultdict(list)
    for r in conn.execute("SELECT id, kickoff, home, away FROM matches WHERE league=?", (league,)):
        by_date[r["kickoff"][:10]].append(r)
    n = 0
    for o in rows:
        if not (o["odds_h"] and o["odds_d"] and o["odds_a"]):
            continue
        cands = [c for k in (-1, 0, 1) for c in by_date[(o["date"] + timedelta(days=k)).isoformat()]]
        if not cands:
            continue
        best = max(cands, key=lambda c: similarity(o["home"], c["home"]) + similarity(o["away"], c["away"]))
        if similarity(o["home"], best["home"]) + similarity(o["away"], best["away"]) < 1.2:
            log.info("Cote non rapprochée : %s - %s (%s)", o["home"], o["away"], o["date"])
            continue
        ts = now_iso()
        conn.execute("INSERT OR REPLACE INTO odds VALUES(?,?,?,?,?,?,?)",
                     (best["id"], o["odds_h"], o["odds_d"], o["odds_a"], o["over25"], o["under25"], ts))
        cl = o.get("close") or {}
        if cl.get("h") and cl.get("d") and cl.get("a"):
            conn.execute("INSERT OR REPLACE INTO odds_closing VALUES(?,?,?,?,?,?)",
                         (best["id"], cl["h"], cl["d"], cl["a"], cl.get("over25"), cl.get("under25")))
        ah = o.get("ah") or {}
        if ah.get("line") is not None and ah.get("h") and ah.get("a"):
            conn.execute("INSERT OR REPLACE INTO odds_ah VALUES(?,?,?,?,?,?,?)",
                         (best["id"], ah["line"], ah["h"], ah["a"], ah.get("close_line"), ah.get("close_h"), ah.get("close_a")))
        for book, b in (o.get("books") or {}).items():
            conn.execute("INSERT OR REPLACE INTO odds_books VALUES(?,?,?,?,?,?,?,?)",
                         (best["id"], book, b.get("h"), b.get("d"), b.get("a"), b.get("over25"), b.get("under25"), ts))
        n += 1
    return n


def load_books(conn, match_ids=None) -> dict:
    books = defaultdict(dict)
    for r in conn.execute("SELECT * FROM odds_books"):
        if match_ids is None or r["match_id"] in match_ids:
            books[r["match_id"]][r["bookmaker"]] = dict(r)
    return books


def window_bounds(today: date | None = None) -> tuple[datetime, datetime]:
    """Du lundi de la semaine en cours (heure locale) au dimanche de la semaine suivante."""
    today = today or date.today()
    start = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time()).astimezone()
    return start, start + timedelta(days=14)


def refresh_predictions(conn, progress=lambda msg, frac: None, match_ids: list[str] | None = None,
                        force_ttl: float | None = None) -> int:
    """(Re)calcule les pronostics live des matchs à venir de la fenêtre. Figés au coup d'envoi."""
    weights, params = current_model(conn)
    ds = Dataset(conn, params)
    start, end = window_bounds()
    now = time.time()
    todo = [m for m in ds.matches.values()
            if start.timestamp() <= m["ts"] < end.timestamp() and m["ts"] > now
            and (match_ids is None or m["id"] in match_ids)]
    odds = {r["match_id"]: dict(r) for r in conn.execute("SELECT * FROM odds")}
    books = load_books(conn)
    for i, m in enumerate(todo):
        progress(f"Pronostic {m['home']} - {m['away']}", i / max(len(todo), 1))
        ctx = context.upcoming_context(conn, m, force_ttl)
        overrides = absences.manual_overrides(conn, m["id"])
        abs_ = {s: absences.team_absences(conn, ds, m, s, overrides, ctx) for s in ("home", "away")}
        pred = predict_match(ds, m, params, weights, odds=odds.get(m["id"]), absences=abs_,
                             ctx=ctx, books=books.get(m["id"]))
        if pred:
            save_prediction(conn, m["id"], "live", pred)
            bet = bankroll.update_auto_bets(conn, m["id"], pred)
            if bet:
                sel = {"H": f"victoire {m['home']}", "D": "match nul", "A": f"victoire {m['away']}", "O": "plus de 2,5 buts", "U": "moins de 2,5 buts"}[bet["outcome"]]
                alerts.create(conn, "bet", m["id"], f"Pari conseillé : {m['home']} – {m['away']}",
                              f"{sel.capitalize()} à {bet['odds']:.2f} chez {bet['bookmaker'].replace(' (direct)', '')} · mise {bet['stake']:.2f} € · avantage {bet['edge'] * 100:+.1f} %")
        conn.commit()
    if todo:
        set_meta(conn, "last_update", now_iso())  # l'interface recharge dès que cette date change
    return len(todo)


LINEUP_WINDOW_MIN = 80       # on surveille les matchs qui commencent dans moins de 80 min
LINEUP_REFRESH_AFTER = 600   # une fois la compo connue : cotes et pronostic toutes les 10 min


def lineup_watch(conn) -> int:
    """Appelée toutes les 2 min. Pour chaque match imminent, guette la composition officielle
    (publiée ~1 h avant). Dès qu'elle tombe : relevé immédiat des cotes, recalcul du pronostic,
    alerte, et pari de test dans le carnet « lineup » pour mesurer si parier à cet instant bat
    la cote de clôture (seule fenêtre où un avantage est plausible)."""
    now = time.time()
    if bankroll.settle(conn):
        conn.commit()
    rows = [dict(r) for r in conn.execute("SELECT * FROM matches WHERE is_result=0 AND fotmob_id IS NOT NULL")]
    soon = [r for r in rows if 0 < parse_ts(r["kickoff"]) - now < LINEUP_WINDOW_MIN * 60]
    n = 0
    for m in soon:
        m["ts"] = parse_ts(m["kickoff"])
        event = conn.execute("SELECT lineup_at FROM lineup_events WHERE match_id=?", (m["id"],)).fetchone()
        if event:   # compo déjà traitée : simple rafraîchissement périodique
            last = get_meta(conn, f"lw:{m['id']}", 0)
            if now - last >= LINEUP_REFRESH_AFTER:
                odds_tracker.snapshot(conn, match_ids=[m["id"]], force_ttl=300)
                refresh_predictions(conn, match_ids=[m["id"]], force_ttl=600)
                set_meta(conn, f"lw:{m['id']}", now)
                n += 1
            continue
        ctx = context.upcoming_context(conn, m, force_ttl=100)
        if not ctx or not ctx.get("lineup_confirmed"):
            continue
        before = conn.execute("SELECT p_home, p_draw, p_away FROM predictions WHERE match_id=? AND source='live'", (m["id"],)).fetchone()
        odds_tracker.snapshot(conn, match_ids=[m["id"]], force_ttl=0)
        refresh_predictions(conn, match_ids=[m["id"]], force_ttl=600)
        row = conn.execute("SELECT p_home, p_draw, p_away, data FROM predictions WHERE match_id=? AND source='live'", (m["id"],)).fetchone()
        if not row:
            continue
        pred = json.loads(row["data"])
        after = [row["p_home"], row["p_draw"], row["p_away"]]
        mins = (m["ts"] - now) / 60
        conn.execute("INSERT OR REPLACE INTO lineup_events VALUES(?,?,?,?,?,?)",
                     (m["id"], now_iso(), round(mins, 1), json.dumps(list(before)) if before else None,
                      json.dumps(after), json.dumps(pred["models"].get("market"))))
        set_meta(conn, f"lw:{m['id']}", now)
        bet = bankroll.update_auto_bets(conn, m["id"], pred, book="lineup")
        delta = max(abs(a - b) for a, b in zip(after, before)) * 100 if before else 0
        body = (f"Coup d'envoi dans {mins:.0f} min. Pronostic : 1 {after[0] * 100:.0f} % · N {after[1] * 100:.0f} % · 2 {after[2] * 100:.0f} %"
                + (f" (variation max {delta:.1f} pts)." if before else "."))
        if bet:
            sel = {"H": f"victoire {m['home']}", "D": "match nul", "A": f"victoire {m['away']}"}.get(bet["outcome"], bet["outcome"])
            body += f" Pari possible : {sel} à {bet['odds']:.2f} chez {bet['bookmaker'].replace(' (direct)', '')} (avantage {bet['edge'] * 100:+.1f} %)."
        alerts.create(conn, "lineup", m["id"], f"Composition officielle : {m['home']} – {m['away']}", body)
        conn.commit()
        n += 1
    return n


def sync_all(conn, progress=lambda msg, frac: None) -> dict:
    season = current_season()
    seasons = list(range(season - HISTORY_SEASONS, season + 1))
    steps = len(LEAGUES) * len(seasons)
    i = 0
    for league in LEAGUES:
        for s in seasons:
            progress(f"Understat {LEAGUES[league]['name']} {s}/{s + 1}", 0.35 * i / steps)
            i += 1
            flag = f"ingested:{league}:{s}"
            if s != season and get_meta(conn, flag):   # saison passée déjà en base
                continue
            ttl = CACHE_TTL_CURRENT if s == season else math.inf
            ingest_league(conn, league, s, understat.league_data(league, s, ttl))
            if s != season:
                set_meta(conn, flag, True)
            conn.commit()

    n_odds = 0
    for league, info in LEAGUES.items():
        progress(f"Cotes {info['name']}", 0.35 + 0.1 * list(LEAGUES).index(league) / len(LEAGUES))
        for s in seasons:
            flag = f"odds:{league}:{s}"
            if s != season and get_meta(conn, flag):
                continue
            try:
                n_odds += attach_odds(conn, league, footballdata.season_odds(
                    info["fd"], s, ttl=3000 if s == season else math.inf))
                if s != season:
                    set_meta(conn, flag, True)
            except Exception as exc:
                log.warning("Cotes %s %s indisponibles : %s", league, s, exc)
    try:
        upcoming = footballdata.upcoming_odds()
        for league, info in LEAGUES.items():
            n_odds += attach_odds(conn, league, [o for o in upcoming if o["div"] == info["fd"]])
    except Exception as exc:
        log.warning("Cotes à venir indisponibles : %s", exc)
    conn.commit()

    # FotMob : calendrier toutes compétitions (début de saison -> J+21) et détails des matchs joués
    cal = context.sync_calendar(conn, date(season, 7, 1), date.today() + timedelta(days=21),
                                lambda msg, f: progress(msg, 0.45 + 0.15 * f))
    n_det = context.sync_finished(conn, season, lambda msg, f: progress(msg, 0.6 + 0.1 * f))

    odds_live = odds_tracker.snapshot(conn, progress=lambda msg, f: progress(msg, 0.7 + 0.15 * f))
    n_pred = refresh_predictions(conn, lambda msg, f: progress(msg, 0.85 + 0.15 * f))
    n_settled = bankroll.settle(conn)
    set_meta(conn, "last_sync", now_iso())
    return {"ok": True, "odds": n_odds, "predictions": n_pred, "linked": cal["linked"],
            "calendar": cal["calendar"], "details": n_det, "settled": n_settled, "odds_changes": odds_live["changes"]}
