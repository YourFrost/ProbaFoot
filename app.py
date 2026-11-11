"""ProbaFoot — serveur web (API JSON + interface statique).

Lancement :  python app.py   puis ouvrir http://127.0.0.1:5000
"""
import json
import logging
import math
import os
import threading
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from flask import Flask, jsonify, request, send_from_directory

from probafoot import absences, advisor, alerts, bankroll, context, factors, learning, models, odds_tracker, sync
from probafoot.sources import fotmob
from probafoot.config import (AUTO_SYNC_HOURS, BASE_DIR, COEF_LABELS, LEAGUES, MODEL_LABELS, current_season)
from probafoot.dataset import Dataset
from probafoot.db import connect, get_meta, init_db, write_lock

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = Flask(__name__, static_folder=str(BASE_DIR / "static"), static_url_path="/static")
app.json.sort_keys = False

TASK = {"running": False, "name": None, "message": "", "progress": 0.0, "result": None, "error": None}
_DS = {"ds": None, "at": 0.0}
LINEUP_WATCH_MINUTES = 2


def dataset(conn, max_age=300):
    """Dataset en mémoire, reconstruit au plus toutes les 5 min (ou après une tâche)."""
    if _DS["ds"] is None or time.time() - _DS["at"] > max_age:
        _DS["ds"], _DS["at"] = Dataset(conn), time.time()
    return _DS["ds"]


def utc(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_task(name, fn):
    """Exécute une tâche longue en arrière-plan (une seule à la fois)."""
    if TASK["running"]:
        return False

    def progress(msg, frac):
        TASK.update(message=msg, progress=round(frac, 3))

    def worker():
        try:
            with write_lock, connect() as conn:
                TASK["result"] = fn(conn, progress)
        except Exception as exc:
            logging.exception("Tâche %s en échec", name)
            TASK["error"] = f"{exc.__class__.__name__}: {exc}"
            TASK["trace"] = traceback.format_exc()
        finally:
            _DS["ds"] = None
            TASK.update(running=False, progress=1.0)

    TASK.update(running=True, name=name, message="Démarrage…", progress=0.0, result=None, error=None)
    threading.Thread(target=worker, daemon=True).start()
    return True


def outcome(m):
    if not m["is_result"] or m["hg"] is None:
        return None
    return "H" if m["hg"] > m["ag"] else "D" if m["hg"] == m["ag"] else "A"


def match_summary(m, preds, odds, books_count):
    pred = preds.get((m["id"], "live")) or preds.get((m["id"], "backtest"))
    out = {k: m[k] for k in ("id", "league", "kickoff", "home", "away", "home_id", "away_id",
                             "is_result", "hg", "ag", "hxg", "axg")}
    out["league_name"] = LEAGUES[m["league"]]["name"]
    out["result"] = outcome(m)
    out["odds"] = odds.get(m["id"])
    out["n_books"] = books_count.get(m["id"], 0)
    if pred:
        d = json.loads(pred["data"])
        mk = (d.get("poisson") or {}).get("markets") or {}
        det = d.get("details") or {}
        out["prediction"] = {
            "source": pred["source"], "p": [pred["p_home"], pred["p_draw"], pred["p_away"]],
            "pick": pred["pick"], "xg": [pred["xg_home"], pred["xg_away"]],
            "over25": mk.get("over25"), "btts": mk.get("btts"),
            "top_score": (mk.get("top_scores") or [{}])[0].get("score"),
            "value": [v for v in d.get("value", []) if v["flag"]],
            "absents": {s: len(a.get("absent", [])) for s, a in d.get("absences", {}).items()},
            "lineup_confirmed": bool(det.get("lineup_confirmed")),
            "derby": bool((det.get("context") or {}).get("derby")),
            "updated_at": pred["updated_at"],
        }
        if out["result"]:
            out["prediction"]["correct"] = pred["pick"] == out["result"]
    return out


def team_series(ds, team_id, ts, n=10):
    """Derniers matchs d'une équipe (pour les graphiques de forme)."""
    out = []
    for g in ds.games_before(team_id, ts, n):
        home = g["home_id"] == team_id
        gf, ga = (g["hg"], g["ag"]) if home else (g["ag"], g["hg"])
        xf, xa = (g["hxg"], g["axg"]) if home else (g["axg"], g["hxg"])
        out.append({"date": g["kickoff"][:10], "opponent": g["away"] if home else g["home"], "home": home,
                    "gf": gf, "ga": ga, "xgf": xf, "xga": xa,
                    "result": "V" if gf > ga else "N" if gf == ga else "D"})
    return out


def next_league_game(ds, team_id, ts):
    best = None
    for games in ds.season_games.values():
        for g in games:
            if team_id in (g["home_id"], g["away_id"]) and g["ts"] > ts and (best is None or g["ts"] < best["ts"]):
                best = g
    return best


def team_calendar(ds, team_id, ts):
    """Match précédent et suivant toutes compétitions (championnat + coupes + Europe)."""
    prev_l = ds.last_game(team_id, ts)
    prev_c = ds.prev_cup(team_id, ts)
    nxt_c = ds.next_cup(team_id, ts)
    league_next = next_league_game(ds, team_id, ts + 3600)
    fmt_l = lambda g: {"comp": "Championnat", "kickoff": g["kickoff"],
                       "opponent": g["away"] if g["home_id"] == team_id else g["home"],
                       "home": g["home_id"] == team_id,
                       "score": f"{g['hg']}-{g['ag']}" if g.get("is_result") else None} if g else None
    fmt_c = lambda c: {"comp": c["comp"], "kind": c["kind"], "kickoff": c["kickoff"], "opponent": c["opponent"],
                       "score": f"{c['hs']}-{c['as_']}" if c.get("finished") else None} if c else None
    prev = max([x for x in (fmt_l(prev_l), fmt_c(prev_c)) if x], key=lambda x: x["kickoff"], default=None)
    nxt = min([x for x in (fmt_l(league_next), fmt_c(nxt_c)) if x], key=lambda x: x["kickoff"], default=None)
    return {"prev": prev, "next": nxt, "next_cup": fmt_c(nxt_c)}


@app.route("/")
def index():
    return send_from_directory(BASE_DIR / "static", "index.html")


@app.get("/api/meta")
def api_meta():
    with connect() as conn:
        weights, params = learning.current_model(conn)
        n = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        start, end = sync.window_bounds()
        return jsonify(leagues=LEAGUES, models=MODEL_LABELS, coefs=COEF_LABELS, weights=weights, params=params,
                       last_sync=get_meta(conn, "last_sync"), last_update=get_meta(conn, "last_update"),
                       season=current_season(), n_matches=n,
                       window={"start": start.isoformat(), "end": end.isoformat()},
                       auto_sync_hours=AUTO_SYNC_HOURS, lineup_watch_minutes=LINEUP_WATCH_MINUTES)


@app.get("/api/matches")
def api_matches():
    start, end = sync.window_bounds()
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM matches WHERE kickoff >= ? AND kickoff < ? ORDER BY kickoff", (utc(start), utc(end)))]
        ids = [r["id"] for r in rows]
        marks = ",".join("?" * len(ids)) or "''"
        preds = {(p["match_id"], p["source"]): dict(p) for p in conn.execute(
            f"SELECT * FROM predictions WHERE match_id IN ({marks})", ids)}
        odds = {o["match_id"]: dict(o) for o in conn.execute(f"SELECT * FROM odds WHERE match_id IN ({marks})", ids)}
        moves = odds_tracker.moves(conn, [r["id"] for r in rows if not r["is_result"]])
        books_count = {r[0]: r[1] for r in conn.execute(
            f"SELECT match_id, COUNT(*) FROM odds_books WHERE match_id IN ({marks}) AND bookmaker NOT IN ('Avg','Max') GROUP BY match_id", ids)}
    out = [match_summary(m, preds, odds, books_count) for m in rows]
    for m in out:
        m["odds_move"] = moves.get(m["id"])
    return jsonify(start=start.isoformat(), end=end.isoformat(), matches=out)


def match_payload(conn, match_id):
    m = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not m:
        return None
    m = dict(m)
    preds = {p["source"]: {**dict(p), "data": json.loads(p["data"])} for p in
             conn.execute("SELECT * FROM predictions WHERE match_id=?", (match_id,))}
    ds = dataset(conn)
    dm = ds.matches.get(match_id) or {**m, "ts": datetime.fromisoformat(m["kickoff"].replace("Z", "+00:00")).timestamp()}
    ctx = context.stored_context(conn, match_id)
    squads = {}
    if not m["is_result"]:
        overrides = absences.manual_overrides(conn, match_id)
        for side in ("home", "away"):
            squads[side] = absences.team_absences(conn, ds, dm, side, overrides, ctx)
    books = [dict(r) for r in conn.execute("SELECT * FROM odds_books WHERE match_id=? ORDER BY bookmaker", (match_id,))]
    bets = [dict(r) for r in conn.execute("SELECT * FROM bets WHERE match_id=? ORDER BY id DESC", (match_id,))]
    m["league_name"] = LEAGUES[m["league"]]["name"]
    m["result"] = outcome(m)
    return {
        "match": m, "predictions": preds, "squads": squads, "labels": MODEL_LABELS, "books": books, "bets": bets,
        "context": {k: ctx.get(k) for k in ("weather", "referee", "stadium", "lineup_confirmed", "lineup_type")} if ctx else None,
        "series": {s: team_series(ds, m[f"{s}_id"], dm["ts"]) for s in ("home", "away")},
        "odds_history": odds_tracker.history(conn, match_id),
        "calendar": {s: team_calendar(ds, m[f"{s}_id"], dm["ts"]) for s in ("home", "away")},
    }


@app.get("/api/match/<match_id>")
def api_match(match_id):
    with connect() as conn:
        res = match_payload(conn, match_id)
    return jsonify(res) if res else (jsonify(error="Match inconnu"), 404)


@app.post("/api/match/<match_id>/absence")
def api_absence(match_id):
    """Corrige l'état d'un joueur : status = 'absent' | 'present' | 'auto' (retire la correction)."""
    body = request.get_json(force=True)
    with write_lock, connect() as conn:
        if not conn.execute("SELECT 1 FROM matches WHERE id=?", (match_id,)).fetchone():
            return jsonify(error="Match inconnu"), 404
        if body["status"] == "auto":
            conn.execute("DELETE FROM manual_absences WHERE match_id=? AND player_id=?", (match_id, body["player_id"]))
        else:
            conn.execute("INSERT OR REPLACE INTO manual_absences VALUES(?,?,?,?,?)",
                         (match_id, body.get("team_id"), body["player_id"], body.get("player"), body["status"]))
        conn.commit()
        sync.refresh_predictions(conn, match_ids=[match_id])
        conn.commit()
        return jsonify(match_payload(conn, match_id))


@app.get("/api/calendar")
def api_calendar():
    """Coupes d'Europe et coupes nationales impliquant les équipes des 5 championnats."""
    days_back, days_fwd = int(request.args.get("back", 7)), int(request.args.get("fwd", 21))
    now = datetime.now(timezone.utc)
    with connect() as conn:
        mapped = {r["fotmob_id"]: r["understat_id"] for r in conn.execute("SELECT * FROM team_map")}
        league_of = {}
        for r in conn.execute("SELECT home_id, league FROM matches WHERE season=?", (current_season(),)):
            league_of[r["home_id"]] = r["league"]
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM calendar WHERE kickoff >= ? AND kickoff < ? ORDER BY kickoff",
            (utc(now - timedelta(days=days_back)), utc(now + timedelta(days=days_fwd))))]
        ds = dataset(conn)
    out = []
    for c in rows:
        teams = []
        for side in ("home", "away"):
            uid = mapped.get(c[f"{side}_fid"])
            info = None
            if uid:
                ts = datetime.fromisoformat(c["kickoff"].replace("Z", "+00:00")).timestamp()
                lg_next = next_league_game(ds, uid, ts)
                last_ts, _ = ds.last_any(uid, ts)
                info = {"league": league_of.get(uid), "rest_before": round((ts - last_ts) / 86400, 1) if last_ts else None,
                        "next_league": {"kickoff": lg_next["kickoff"], "opponent": lg_next["away"] if lg_next["home_id"] == uid else lg_next["home"],
                                        "days": round((lg_next["ts"] - ts) / 86400, 1)} if lg_next else None}
            teams.append(info)
        if teams[0] or teams[1]:
            out.append({**c, "home_info": teams[0], "away_info": teams[1]})
    return jsonify(out)


# ------------------------------------------------------------------ bankroll
@app.get("/api/bankroll")
def api_bankroll():
    book = request.args.get("book", "auto")
    with connect() as conn:
        return jsonify(bankroll.summary(conn, book))


@app.post("/api/bankroll/settings")
def api_bankroll_settings():
    with write_lock, connect() as conn:
        s = bankroll.save_settings(conn, {**request.get_json(force=True), "strategy_label": ""})
        bankroll.reset_pending_auto(conn)
        conn.commit()
        sync.refresh_predictions(conn)  # recalcule les paris simulés à venir
        return jsonify(s)


@app.get("/api/bankroll/simulate")
def api_bankroll_simulate():
    with connect() as conn:
        s = bankroll.settings(conn)
        for k in ("min_edge", "kelly_fraction", "flat_pct", "max_stake_pct", "max_odds", "initial"):
            if k in request.args:
                s[k] = float(request.args[k])
        if "staking" in request.args:
            s["staking"] = request.args["staking"]
        if "markets" in request.args:
            s["markets"] = request.args["markets"].split(",")
        sources = ("backtest", "live") if request.args.get("source", "all") == "all" else (request.args["source"],)
        return jsonify(bankroll.simulate(conn, s, sources, request.args.get("from") or None, request.args.get("to") or None))


@app.post("/api/bets")
def api_add_bet():
    b = request.get_json(force=True)
    with write_lock, connect() as conn:
        if not conn.execute("SELECT 1 FROM matches WHERE id=?", (b["match_id"],)).fetchone():
            return jsonify(error="Match inconnu"), 404
        pred = conn.execute("SELECT data FROM predictions WHERE match_id=? ORDER BY source DESC", (b["match_id"],)).fetchone()
        p = None
        if pred:
            d = json.loads(pred["data"])
            if b["market"] == "1X2":
                p = d["final"]["HDA".index(b["selection"])]
            elif d.get("over25") is not None or d.get("poisson"):
                o = d.get("over25") if d.get("over25") is not None else d["poisson"]["markets"]["over25"]
                p = o if b["selection"] == "O" else 1 - o
        odds = float(b["odds"])
        conn.execute("""INSERT INTO bets(book, created_at, match_id, market, selection, odds, stake, bookmaker,
                        p_model, edge, status, note) VALUES('manual', datetime('now'), ?,?,?,?,?,?,?,?,'pending',?)""",
                     (b["match_id"], b["market"], b["selection"], odds, float(b["stake"]), b.get("bookmaker"),
                      p, (p * odds - 1) if p else None, b.get("note")))
        bankroll.settle(conn)
        conn.commit()
        return jsonify(bankroll.summary(conn, "manual"))


@app.delete("/api/bets/<int:bet_id>")
def api_delete_bet(bet_id):
    with write_lock, connect() as conn:
        conn.execute("DELETE FROM bets WHERE id=? AND book='manual'", (bet_id,))
        conn.commit()
        return jsonify(bankroll.summary(conn, "manual"))


# ------------------------------------------------------------------ tâches
@app.post("/api/sync")
def api_sync():
    return jsonify(started=run_task("sync", sync.sync_all), task=TASK)


@app.post("/api/backtest")
def api_backtest():
    return jsonify(started=run_task("backtest", learning.run_backtest), task=TASK)


@app.post("/api/learn")
def api_learn():
    def job(conn, progress):
        progress("Optimisation des poids et des coefficients…", 0.1)
        res = learning.learn(conn)
        if res.get("ok"):
            conn.commit()
            progress("Mise à jour des pronostics…", 0.7)
            sync.refresh_predictions(conn)
        return res
    return jsonify(started=run_task("learn", job), task=TASK)


@app.get("/api/status")
def api_status():
    return jsonify({k: v for k, v in TASK.items() if k != "trace"})


# ------------------------------------------------------------------ performances
@app.get("/api/stats")
def api_stats():
    source = request.args.get("source", "live")
    league = request.args.get("league") or None
    sources = ("live", "backtest") if source == "all" else (source,)
    with connect() as conn:
        samples = learning.collect(conn, sources, league)
        history = [dict(r) for r in conn.execute("SELECT * FROM weights_history ORDER BY id DESC LIMIT 30")]
        weights, params = learning.current_model(conn)
    res = learning.metrics(samples)
    for h in history:
        h["weights"], h["params"] = json.loads(h["weights"]), json.loads(h["params"])
    # évolution : réussite et log-loss par mois
    by_month = defaultdict(list)
    for s in samples:
        p = [s["p_home"], s["p_draw"], s["p_away"]]
        by_month[s["kickoff"][:7]].append((int(max(range(3), key=lambda i: p[i]) == s["y"]), -math.log(max(p[s["y"]], 1e-9))))
    timeline = [{"month": k, "n": len(v), "accuracy": sum(a for a, _ in v) / len(v), "logloss": sum(b for _, b in v) / len(v)}
                for k, v in sorted(by_month.items())]
    res.update(weights=weights, params=params, history=history, labels=MODEL_LABELS, coef_labels=COEF_LABELS,
               timeline=timeline, tiers=advisor.confidence_tiers(samples) if samples else [])
    return jsonify(res)


@app.get("/api/history")
def api_history():
    source = request.args.get("source", "live")
    league = request.args.get("league") or None
    limit = int(request.args.get("limit", 200))
    sources = ("live", "backtest") if source == "all" else (source,)
    with connect() as conn:
        samples = learning.collect(conn, sources, league)[-limit:]
    out = [{"match_id": s["match_id"], "source": s["source"], "kickoff": s["kickoff"], "league": s["league"],
            "home": s["home"], "away": s["away"], "score": f"{s['hg']}-{s['ag']}",
            "p": [s["p_home"], s["p_draw"], s["p_away"]], "pick": s["pick"],
            "result": "HDA"[s["y"]], "correct": s["pick"] == "HDA"[s["y"]]} for s in reversed(samples)]
    return jsonify(out)


# ------------------------------------------------------------------ conseiller & stratégies
@app.get("/api/advisor")
def api_advisor():
    with connect() as conn:
        return jsonify(advisor.advise(conn))


@app.get("/api/bankroll/optimize")
def api_optimize():
    with connect() as conn:
        return jsonify(bankroll.optimize(conn, current_season()))


@app.post("/api/bankroll/apply")
def api_apply_strategy():
    """Applique une stratégie proposée par l'optimiseur (elle devient celle du conseiller)."""
    body = request.get_json(force=True)
    with write_lock, connect() as conn:
        s = {**body["settings"], "strategy_label": body.get("label") or bankroll.strategy_label({**bankroll.settings(conn), **body["settings"]}), "auto": True}
        s = bankroll.save_settings(conn, s)
        bankroll.reset_pending_auto(conn)
        conn.commit()
        sync.refresh_predictions(conn)
        conn.commit()
        return jsonify(s)


# ------------------------------------------------------------------ alertes
@app.get("/api/alerts")
def api_alerts():
    with connect() as conn:
        return jsonify(alerts.recent(conn))


@app.post("/api/alerts/seen")
def api_alerts_seen():
    with write_lock, connect() as conn:
        alerts.mark_seen(conn)
        conn.commit()
        return jsonify(alerts.recent(conn))


# ------------------------------------------------------------------ scores en direct
_LIVE = {"at": 0.0, "data": {}}


@app.get("/api/live")
def api_live():
    """Scores en direct (FotMob) des matchs en cours ou tout juste terminés, rafraîchis toutes les 45 s."""
    now = time.time()
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, kickoff, fotmob_id FROM matches WHERE fotmob_id IS NOT NULL AND kickoff >= ? AND kickoff <= ?",
            (utc(datetime.now(timezone.utc) - timedelta(hours=3)), utc(datetime.now(timezone.utc) + timedelta(minutes=10))))]
    if not rows:
        return jsonify({})
    if now - _LIVE["at"] > 45:
        by_fid = {}
        days = {datetime.fromisoformat(r["kickoff"].replace("Z", "+00:00")).date() for r in rows}
        for day in days:
            try:
                for lg in fotmob.matches_on(day, ttl=30):
                    for fm in lg.get("matches", []):
                        by_fid[str(fm["id"])] = fotmob.live_status(fm)
            except Exception as exc:
                logging.warning("Scores en direct indisponibles : %s", exc)
        _LIVE.update(at=now, data=by_fid)
    return jsonify({r["id"]: _LIVE["data"][r["fotmob_id"]] for r in rows if r["fotmob_id"] in _LIVE["data"]})


# ------------------------------------------------------------------ fiche équipe
@app.get("/api/team/<team_id>")
def api_team(team_id):
    with connect() as conn:
        ds = dataset(conn)
        season = current_season()
        league = next((lg for (lg, se), ts in ds.season_teams.items() if se == season and team_id in ts), None)
        if not league:
            return jsonify(error="Équipe inconnue"), 404
        now = time.time()
        name = next(g["home"] if g["home_id"] == team_id else g["away"] for g in ds.season_games[(league, season)]
                    if team_id in (g["home_id"], g["away_id"]))
        table, by_id = factors.standings(ds, league, season, now)
        row = by_id.get(team_id, {})
        played = [g for g in ds.season_games[(league, season)] if team_id in (g["home_id"], g["away_id"]) and g["is_result"] and g["hg"] is not None]
        upcoming = sorted([g for g in ds.season_games[(league, season)] if team_id in (g["home_id"], g["away_id"]) and not g["is_result"]],
                          key=lambda g: g["ts"])[:6]

        def split(home):
            gs = [g for g in played if (g["home_id"] == team_id) == home]
            if not gs:
                return None
            gf = [g["hg"] if home else g["ag"] for g in gs]
            ga = [g["ag"] if home else g["hg"] for g in gs]
            xf = [(g["hxg"] if home else g["axg"]) or 0 for g in gs]
            xa = [(g["axg"] if home else g["hxg"]) or 0 for g in gs]
            pts = sum(3 if a > b else 1 if a == b else 0 for a, b in zip(gf, ga))
            return {"n": len(gs), "w": sum(a > b for a, b in zip(gf, ga)), "d": sum(a == b for a, b in zip(gf, ga)),
                    "l": sum(a < b for a, b in zip(gf, ga)), "gf": sum(gf), "ga": sum(ga), "ppg": pts / len(gs),
                    "xgf": sum(xf) / len(gs), "xga": sum(xa) / len(gs)}

        la = ds.leagues[league]
        weights, params = learning.current_model(conn)
        r = models.team_ratings(la, now, params, ds.priors(league, season, params))
        mr = models.market_team_ratings(ds.implied[league], now, params, ds.priors(league, season, params))
        i = la.idx[team_id]
        ratings = {
            "xg": {"att": float(r["att"][i]), "def": float(r["de"][i]), "home_att": float(r["home_att"][i]), "home_def": float(r["home_def"][i])} if r else None,
            "odds": {"att": float(np.exp(mr["att"][i])), "def": float(np.exp(-mr["def"][i]))} if mr else None,
        }
        # rang des ratings dans la ligue
        if mr:
            strength = {t: mr["att"][j] + mr["def"][j] for t, j in la.idx.items() if t in ds.season_teams[(league, season)]}
            ratings["odds_rank"] = sorted(strength, key=lambda t: -strength[t]).index(team_id) + 1
        # joueurs : stats Understat + notes FotMob
        fid = context.fotmob_team_id(conn, team_id)
        rated = context.team_ratings(conn, fid, utc(datetime.now(timezone.utc)), f"{season}-07-01T00:00:00Z")
        players = []
        for p in conn.execute("SELECT * FROM players WHERE league=? AND season=?", (league, season)):
            if name not in [t.strip() for t in (p["team"] or "").split(",")]:
                continue
            pr = rated.get(absences._find(p["name"], rated) or "")
            players.append({"name": p["name"], "position": absences._pos_label(p["position"]), "games": p["games"],
                            "minutes": p["minutes"], "goals": p["goals"], "assists": p["assists"], "xg": p["xg"], "xa": p["xa"],
                            "rating": round(pr["avg"], 2) if pr else None})
        players.sort(key=lambda x: -(x["minutes"] or 0))
        # blessés / suspendus : contexte FotMob du prochain match
        injuries = []
        if upcoming:
            ctx = context.stored_context(conn, upcoming[0]["id"])
            side = "home" if upcoming[0]["home_id"] == team_id else "away"
            injuries = ((ctx or {}).get("teams", {}).get(side) or {}).get("unavailable", [])
        form = models.team_form(ds, team_id, now, {**params, "form_n": 10}, ds.implied_probs)
        cal = team_calendar(ds, team_id, now)
        cups = [{"comp": c["comp"], "kickoff": c["kickoff"], "opponent": c["opponent"],
                 "score": f"{c['hs']}-{c['as_']}" if c["finished"] else None} for c in ds.cup_games.get(team_id, [])
                if c["kickoff"] >= f"{season}-07-01"]
        results = [{"id": g["id"], "kickoff": g["kickoff"], "home": g["home_id"] == team_id,
                    "opponent": g["away"] if g["home_id"] == team_id else g["home"],
                    "opponent_id": g["away_id"] if g["home_id"] == team_id else g["home_id"],
                    "gf": g["hg"] if g["home_id"] == team_id else g["ag"], "ga": g["ag"] if g["home_id"] == team_id else g["hg"],
                    "xgf": g["hxg"] if g["home_id"] == team_id else g["axg"], "xga": g["axg"] if g["home_id"] == team_id else g["hxg"]}
                   for g in sorted(played, key=lambda g: g["ts"])]
    return jsonify({
        "id": team_id, "name": name, "league": league, "league_name": LEAGUES[league]["name"],
        "standing": {k: row.get(k) for k in ("pos", "pts", "played", "gd", "gf")} | {"n_teams": len(table)},
        "table": [{"team_id": t["team_id"], "team": t["team"], "pos": t["pos"], "pts": t["pts"], "played": t["played"], "gd": t["gd"]} for t in table],
        "home": split(True), "away": split(False), "ratings": ratings, "form": form, "results": results,
        "upcoming": [{"id": g["id"], "kickoff": g["kickoff"], "home": g["home_id"] == team_id,
                      "opponent": g["away"] if g["home_id"] == team_id else g["home"]} for g in upcoming],
        "cups": cups, "players": players, "injuries": injuries, "calendar": cal,
    })


# ------------------------------------------------------------------ boucles de fond
def auto_sync_loop():
    while AUTO_SYNC_HOURS:
        time.sleep(AUTO_SYNC_HOURS * 3600)
        run_task("sync", sync.sync_all)


def lineup_watch_loop():
    """Compositions officielles : guettées toutes les 2 min pour les matchs imminents."""
    while True:
        time.sleep(LINEUP_WATCH_MINUTES * 60)
        if TASK["running"]:
            continue
        try:
            with write_lock, connect() as conn:
                n = sync.lineup_watch(conn)
                conn.commit()
            if n:
                logging.info("Compositions vérifiées pour %d match(s) imminent(s)", n)
                _DS["ds"] = None
        except Exception:
            logging.exception("Veille des compositions en échec")


if __name__ == "__main__":
    init_db()
    with connect() as c:
        if c.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0:
            logging.info("Base vide : première synchronisation lancée en arrière-plan")
            run_task("sync", sync.sync_all)
    threading.Thread(target=auto_sync_loop, daemon=True).start()
    threading.Thread(target=lineup_watch_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
