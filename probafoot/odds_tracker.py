"""Suivi de l'évolution des cotes.

À chaque synchronisation (toutes les heures), les cotes 1N2 actuelles de 5 bookmakers sont
relevées via FotMob pour tous les matchs à venir de la fenêtre. Un point n'est enregistré que
si la cote a changé. Ces cotes « en direct » servent aussi :
- de marché pour les matchs lointains (football-data ne publie que la semaine en cours) ;
- de cotes les plus récentes (plus précises à l'approche du match) pour les value bets.
"""
import logging
import time
from collections import defaultdict

from .dataset import parse_ts
from .db import now_iso
from .sources import fotmob

log = logging.getLogger(__name__)
LIVE_SUFFIX = " (direct)"


def _record(conn, match_id: str, book: str, o: dict, ts: str) -> bool:
    last = conn.execute("SELECT h, d, a FROM odds_history WHERE match_id=? AND bookmaker=? ORDER BY ts DESC LIMIT 1",
                        (match_id, book)).fetchone()
    if last and all(abs((last[k] or 0) - o[k]) < 1e-6 for k in ("h", "d", "a")):
        return False
    conn.execute("INSERT OR REPLACE INTO odds_history VALUES(?,?,?,?,?,?)", (match_id, book, ts, o["h"], o["d"], o["a"]))
    return True


def snapshot(conn, match_ids: list[str] | None = None, force_ttl: float | None = None,
             progress=lambda msg, frac: None) -> dict:
    now = time.time()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, kickoff, home, away, fotmob_id FROM matches WHERE is_result=0 AND fotmob_id IS NOT NULL")]
    todo = [r for r in rows if 0 < parse_ts(r["kickoff"]) - now < 15 * 86400 and (match_ids is None or r["id"] in match_ids)]
    ts, n_changes = now_iso(), 0
    for i, m in enumerate(todo):
        if i % 5 == 0:
            progress(f"Cotes en direct {m['home']} - {m['away']}", i / max(len(todo), 1))
        hours = (parse_ts(m["kickoff"]) - now) / 3600
        ttl = force_ttl if force_ttl is not None else (2400 if hours < 72 else 6 * 3600)
        live = {}
        for cc, book in fotmob.ODDS_COUNTRIES.items():
            try:
                o = fotmob.match_odds(m["fotmob_id"], cc, ttl)
            except Exception as exc:
                log.debug("Cotes %s/%s indisponibles : %s", m["fotmob_id"], cc, exc)
                continue
            if o:
                live[book + LIVE_SUFFIX] = o
        for book, o in live.items():
            n_changes += _record(conn, m["id"], book, o, ts)
            conn.execute("INSERT OR REPLACE INTO odds_books(match_id, bookmaker, h, d, a, over25, under25, updated_at) "
                         "VALUES(?,?,?,?,?,NULL,NULL,?)", (m["id"], book, o["h"], o["d"], o["a"], ts))
        # football-data (si publié) : aussi historisé
        for r in conn.execute("SELECT * FROM odds_books WHERE match_id=? AND bookmaker NOT LIKE ? AND bookmaker NOT IN ('Avg','Max')",
                              (m["id"], "%" + LIVE_SUFFIX)):
            if r["h"] and r["d"] and r["a"]:
                n_changes += _record(conn, m["id"], r["bookmaker"], dict(r), r["updated_at"] or ts)
        # cotes « marché » du match : moyenne des bookmakers en direct (plus récentes)
        if len(live) >= 3:
            avg = {k: sum(o[k] for o in live.values()) / len(live) for k in ("h", "d", "a")}
            prev = conn.execute("SELECT over25, under25 FROM odds WHERE match_id=?", (m["id"],)).fetchone()
            conn.execute("INSERT OR REPLACE INTO odds VALUES(?,?,?,?,?,?,?)",
                         (m["id"], avg["h"], avg["d"], avg["a"], prev["over25"] if prev else None,
                          prev["under25"] if prev else None, ts))
        conn.commit()
    return {"matches": len(todo), "changes": n_changes}


def history(conn, match_id: str) -> dict:
    """Série par bookmaker + mouvement global (probabilités implicites moyennes, début -> maintenant)."""
    series = defaultdict(list)
    for r in conn.execute("SELECT * FROM odds_history WHERE match_id=? ORDER BY ts", (match_id,)):
        series[r["bookmaker"]].append({"ts": r["ts"], "h": r["h"], "d": r["d"], "a": r["a"]})

    def implied(p):
        inv = [1 / p["h"], 1 / p["d"], 1 / p["a"]]
        s = sum(inv)
        return [x / s for x in inv]

    first = [implied(pts[0]) for pts in series.values() if pts]
    last = [implied(pts[-1]) for pts in series.values() if pts]
    move = None
    if first:
        f = [sum(x[i] for x in first) / len(first) for i in range(3)]
        l = [sum(x[i] for x in last) / len(last) for i in range(3)]
        move = {"first": f, "last": l, "delta": [l[i] - f[i] for i in range(3)],
                "since": min(pts[0]["ts"] for pts in series.values() if pts), "n_points": sum(len(v) for v in series.values())}
    return {"series": series, "move": move}


def moves(conn, match_ids: list[str]) -> dict:
    """Mouvement résumé (variation de la probabilité implicite du favori) pour la liste des matchs."""
    out = {}
    for mid in match_ids:
        h = history(conn, mid)["move"]
        if h and h["n_points"] > len(h["first"]):
            out[mid] = h["delta"]
    return out
