"""Contexte des matchs depuis FotMob : calendrier toutes compétitions, compositions,
indisponibles, notes des joueurs, météo, arbitre."""
import json
import logging
import math
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .db import now_iso
from .names import similarity
from .sources import fotmob

log = logging.getLogger(__name__)


def _iso(utc: str) -> str:
    return utc[:19].replace(" ", "T") + "Z"


def _day_ttl(day: date) -> float:
    today = date.today()
    if day < today - timedelta(days=2):
        return math.inf          # journée passée : figée
    if day <= today + timedelta(days=3):
        return 1800
    return 6 * 3600


def sync_calendar(conn, start: date, end: date, progress=lambda msg, frac: None) -> dict:
    """Parcourt les journées [start, end] : relie les matchs de championnat FotMob aux matchs
    Understat (et apprend la correspondance des équipes), stocke coupes et matchs européens."""
    team_map = {r["fotmob_id"]: r["understat_id"] for r in conn.execute("SELECT * FROM team_map")}
    by_league_day = defaultdict(list)
    for r in conn.execute("SELECT id, league, kickoff, home_id, home, away_id, away FROM matches"):
        by_league_day[(r["league"], r["kickoff"][:10])].append(dict(r))
    league_of = {v: k for k, v in fotmob.LEAGUE_IDS.items()}
    n_days, n_linked, n_cal = (end - start).days + 1, 0, 0
    for i in range(n_days):
        day = start + timedelta(days=i)
        if i % 5 == 0:
            progress(f"Calendrier FotMob {day:%d/%m/%Y}", i / n_days)
        try:
            leagues = fotmob.matches_on(day, _day_ttl(day))
        except Exception as exc:
            log.warning("FotMob %s indisponible : %s", day, exc)
            continue
        for lg in leagues:
            pid = lg.get("primaryId")
            if pid in league_of:
                n_linked += _link_league(conn, league_of[pid], lg["matches"], by_league_day, team_map)
                continue
            kind, comp = fotmob.competition_kind(lg)
            if not kind:
                continue
            for m in lg["matches"]:
                st = m.get("status") or {}
                if st.get("cancelled") or not st.get("utcTime"):
                    continue
                conn.execute("INSERT OR REPLACE INTO calendar VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                    str(m["id"]), pid, comp, kind, _iso(st["utcTime"]),
                    str(m["home"]["id"]), m["home"]["name"], str(m["away"]["id"]), m["away"]["name"],
                    m["home"].get("score") if st.get("finished") else None,
                    m["away"].get("score") if st.get("finished") else None, int(bool(st.get("finished")))))
                n_cal += 1
        conn.commit()
    return {"linked": n_linked, "calendar": n_cal}


def _link_league(conn, league, fm_matches, by_league_day, team_map) -> int:
    n = 0
    for fm in fm_matches:
        st = fm.get("status") or {}
        if not st.get("utcTime"):
            continue
        d = datetime.fromisoformat(_iso(st["utcTime"]).replace("Z", "+00:00")).date()
        cands = [c for k in (-1, 0, 1) for c in by_league_day[(league, (d + timedelta(days=k)).isoformat())]]
        if not cands:
            continue
        fh, fa = str(fm["home"]["id"]), str(fm["away"]["id"])

        def score(c):
            s = 0.0
            for fid, fname, uid, uname in ((fh, fm["home"]["name"], c["home_id"], c["home"]),
                                           (fa, fm["away"]["name"], c["away_id"], c["away"])):
                s += 2.0 if team_map.get(fid) == uid else similarity(fname, uname)
            return s
        best = max(cands, key=score)
        if score(best) < 1.3:
            continue
        conn.execute("UPDATE matches SET fotmob_id=? WHERE id=?", (str(fm["id"]), best["id"]))
        for fid, fname, uid in ((fh, fm["home"]["name"], best["home_id"]), (fa, fm["away"]["name"], best["away_id"])):
            if team_map.get(fid) != uid:
                team_map[fid] = uid
                conn.execute("INSERT OR REPLACE INTO team_map VALUES(?,?,?)", (fid, uid, fname))
        n += 1
    return n


def _store_details(conn, match_id: str, fotmob_id: str, parsed: dict, finished: bool):
    conn.execute("INSERT OR REPLACE INTO match_context VALUES(?,?,?,?)",
                 (match_id, fotmob_id, now_iso(), json.dumps({**parsed, "finished": finished})))
    if finished:
        for side in ("home", "away"):
            t = parsed["teams"].get(side) or {}
            for p in t.get("players", []):
                if p["minutes"] > 0:
                    conn.execute("INSERT OR REPLACE INTO player_ratings VALUES(?,?,?,?,?,?,?,?)",
                                 (fotmob_id, match_id, t.get("team_id"), p["id"], p["name"],
                                  p["rating"], p["minutes"], int(p["started"])))


def sync_finished(conn, season: int, progress=lambda msg, frac: None) -> int:
    """Détails des matchs terminés de la saison (notes des joueurs, météo, arbitre, compos)."""
    done = {r["match_id"] for r in conn.execute(
        "SELECT match_id FROM match_context WHERE json_extract(data, '$.finished') = 1")}
    todo = [dict(r) for r in conn.execute(
        "SELECT id, fotmob_id FROM matches WHERE season=? AND is_result=1 AND fotmob_id IS NOT NULL", (season,))
        if r["id"] not in done]
    for i, m in enumerate(todo):
        if i % 10 == 0:
            progress(f"Notes des joueurs {i}/{len(todo)}", i / max(len(todo), 1))
            conn.commit()
        try:
            _store_details(conn, m["id"], m["fotmob_id"], fotmob.parse_details(fotmob.match_details(m["fotmob_id"])), True)
        except Exception as exc:
            log.warning("Détails FotMob %s indisponibles : %s", m["fotmob_id"], exc)
    conn.commit()
    return len(todo)


def upcoming_context(conn, m: dict, force_ttl: float | None = None) -> dict | None:
    """Contexte d'un match à venir (indisponibles, compo officielle, météo, arbitre).
    Rafraîchi d'autant plus souvent que le coup d'envoi approche."""
    if not m.get("fotmob_id"):
        return None
    hours = (m["ts"] - time.time()) / 3600
    ttl = force_ttl if force_ttl is not None else (600 if hours < 3 else 3000 if hours < 72 else 6 * 3600)
    try:
        parsed = fotmob.parse_details(fotmob.match_details(m["fotmob_id"], ttl=ttl))
    except Exception as exc:
        log.warning("Contexte FotMob %s indisponible : %s", m["fotmob_id"], exc)
        row = conn.execute("SELECT data FROM match_context WHERE match_id=?", (m["id"],)).fetchone()
        return json.loads(row["data"]) if row else None
    _store_details(conn, m["id"], m["fotmob_id"], parsed, False)
    return {**parsed, "finished": False}


def stored_context(conn, match_id: str) -> dict | None:
    row = conn.execute("SELECT data FROM match_context WHERE match_id=?", (match_id,)).fetchone()
    return json.loads(row["data"]) if row else None


def team_ratings(conn, team_fid: str | None, before_iso: str, season_start_iso: str) -> dict[str, dict]:
    """Note moyenne FotMob (pondérée par les minutes) de chaque joueur de l'équipe sur la saison."""
    if not team_fid:
        return {}
    rows = conn.execute(
        """SELECT pr.player_fid, pr.name, SUM(pr.rating * pr.minutes) / SUM(pr.minutes) AS avg,
                  COUNT(*) AS apps, SUM(pr.minutes) AS minutes
           FROM player_ratings pr JOIN matches m ON m.id = pr.match_id
           WHERE pr.team_fid = ? AND pr.rating IS NOT NULL AND m.kickoff < ? AND m.kickoff >= ?
           GROUP BY pr.player_fid""", (team_fid, before_iso, season_start_iso))
    return {r["player_fid"]: dict(r) for r in rows}


def fotmob_team_id(conn, understat_id: str) -> str | None:
    row = conn.execute("SELECT fotmob_id FROM team_map WHERE understat_id=?", (understat_id,)).fetchone()
    return row["fotmob_id"] if row else None


def utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
