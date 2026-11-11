"""Absences et composition probable / officielle.

Priorité des sources pour l'état d'un joueur :
1. correction manuelle de l'utilisateur ;
2. composition officielle (publiée ~1 h avant) : titulaire = présent, remplaçant = demi-absent,
   hors feuille de match = absent ;
3. liste FotMob des indisponibles (blessure, suspension) : « incertain » compte pour moitié ;
4. à défaut de FotMob : heuristique (titulaire régulier absent du dernier match).

Impacts calculés :
- offensif  = part de l'équipe dans (xG + xA) portée par les absents ;
- défensif  = part des minutes des défenseurs/gardien absents, rapportée à 5 postes ;
- qualité   = part de la « qualité » de l'effectif perdue, où la qualité d'un joueur vaut
              temps de jeu × (note moyenne − 6), notes FotMob de la saison.
"""
import logging
from datetime import datetime, timezone

from . import context
from .names import norm, similarity
from .sources import understat

log = logging.getLogger(__name__)
REGULAR_SHARE = 0.45
RATING_FLOOR = 6.0


def get_roster(conn, match_id: str) -> list[dict]:
    if not conn.execute("SELECT 1 FROM rosters_fetched WHERE match_id=?", (match_id,)).fetchone():
        data = understat.match_data(match_id)
        rows = [(match_id, p["team_id"], p["player_id"], p["player"], p.get("position"), int(p.get("time") or 0))
                for side in ("h", "a") for p in data.get("rosters", {}).get(side, {}).values()]
        conn.executemany("INSERT OR REPLACE INTO rosters VALUES(?,?,?,?,?,?)", rows)
        conn.execute("INSERT OR IGNORE INTO rosters_fetched VALUES(?)", (match_id,))
        conn.commit()
    return [dict(r) for r in conn.execute("SELECT * FROM rosters WHERE match_id=?", (match_id,))]


def manual_overrides(conn, match_id: str) -> dict[str, str]:
    return {r["player_id"]: r["status"] for r in
            conn.execute("SELECT player_id, status FROM manual_absences WHERE match_id=?", (match_id,))}


def _find(name: str, candidates: dict[str, dict], key="name", threshold=0.82):
    """Meilleur candidat par nom (gère accents, prénoms abrégés)."""
    best, best_s = None, 0.0
    n = norm(name)
    last = n.split()[-1] if n else ""
    for cid, c in candidates.items():
        cn = norm(c[key] or "")
        s = similarity(name, c[key] or "")
        if last and cn.split() and cn.split()[-1] == last and (n[:1] == cn[:1] or len(n.split()) == 1 or len(cn.split()) == 1):
            s = max(s, 0.9)
        if s > best_s:
            best, best_s = cid, s
    return best if best_s >= threshold else None


def _pos_label(pos: str | None) -> str:
    toks = set((pos or "").split())
    if "GK" in toks:
        return "GB"
    if "D" in toks:
        return "DEF"
    if "M" in toks:
        return "MIL"
    if "F" in toks:
        return "ATT"
    return "–"


def team_absences(conn, ds, m: dict, side: str, overrides: dict, ctx: dict | None = None,
                  fetch_rosters: bool = True) -> dict:
    tid, team = m[f"{side}_id"], m[side]
    season_games = [g for g in ds.games_before(tid, m["ts"]) if g["season"] == m["season"]]
    n_games = len(season_games)
    kickoff_iso = datetime.fromtimestamp(m["ts"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    season_start = f"{m['season']}-07-01T00:00:00Z"

    # Stats Understat (xG, xA, minutes) + notes FotMob, rapprochées par le nom
    players = [dict(r) for r in conn.execute(
        "SELECT * FROM players WHERE league=? AND season=?", (m["league"], m["season"]))
        if team in [t.strip() for t in (r["team"] or "").split(",")]]
    team_fid = context.fotmob_team_id(conn, tid)
    ratings = context.team_ratings(conn, team_fid, kickoff_iso, season_start)
    rated_left = dict(ratings)
    squad = []
    for p in players:
        fid = _find(p["name"], rated_left)
        r = rated_left.pop(fid, None) if fid else None
        squad.append({"player_id": p["player_id"], "fid": fid, "name": p["name"], "position": _pos_label(p["position"]),
                      "minutes": p["minutes"] or 0, "xg": p["xg"] or 0, "xa": p["xa"] or 0,
                      "rating": round(r["avg"], 2) if r else None, "apps": r["apps"] if r else None})
    for fid, r in rated_left.items():  # joueurs notés par FotMob mais absents des stats Understat
        if r["minutes"] >= 90:
            squad.append({"player_id": f"fm{fid}", "fid": fid, "name": r["name"], "position": "–",
                          "minutes": r["minutes"], "xg": 0, "xa": 0, "rating": round(r["avg"], 2), "apps": r["apps"]})

    # Sources d'information sur la disponibilité
    tctx = (ctx or {}).get("teams", {}).get(side) if ctx else None
    confirmed = bool(ctx and ctx.get("lineup_confirmed") and tctx)
    starters, bench = {}, {}
    if confirmed:
        for p in tctx["players"]:
            (starters if p["started"] else bench)[p["id"]] = p
    unavailable = {u["id"]: u for u in (tctx or {}).get("unavailable", [])}
    if tctx:
        for u in unavailable.values():  # blessés sans temps de jeu cette saison : affichés quand même
            if not any(s["fid"] == u["id"] for s in squad) and not _find(u["name"], {s["player_id"]: s for s in squad}):
                squad.append({"player_id": f"fm{u['id']}", "fid": u["id"], "name": u["name"], "position": "–",
                              "minutes": 0, "xg": 0, "xa": 0, "rating": None, "apps": None})

    present_last, heuristic = set(), False
    last = season_games[-1] if season_games else None
    if not tctx and last and fetch_rosters:
        try:
            present_last = {r["player_id"] for r in get_roster(conn, last["id"]) if r["team_id"] == tid}
            heuristic = bool(present_last)
        except Exception as exc:
            log.warning("Composition indisponible pour %s : %s", last["id"], exc)

    team_att = sum(s["xg"] + s["xa"] for s in squad) or 1.0
    rated = [s["rating"] for s in squad if s["rating"]]
    median_rating = sorted(rated)[len(rated) // 2] if rated else 6.6
    for s in squad:
        s["share_min"] = round(min(s["minutes"] / (90 * max(n_games, 1)), 1.0), 3)
        s["share_att"] = round((s["xg"] + s["xa"]) / team_att, 3)
        s["quality"] = s["share_min"] * max((s["rating"] or median_rating) - RATING_FLOOR, 0.1)

        # état automatique
        weight, label = 0.0, "présent"
        if confirmed:
            if _in(s, starters):
                weight, label = 0.0, "titulaire"
            elif _in(s, bench):
                weight, label = 0.5, "remplaçant"
            else:
                weight, label = 1.0, "hors groupe"
        elif tctx:
            u = unavailable.get(s["fid"]) if s["fid"] else None
            if u is None:
                key = _find(s["name"], unavailable)
                u = unavailable.get(key) if key else None
            if u:
                doubtful = (u.get("expected_return") or "").lower().startswith("doubt")
                typ = {"injury": "blessé", "suspension": "suspendu", "international": "sélection"}.get(u.get("type"), u.get("type") or "indisponible")
                weight, label = (0.5, f"incertain ({typ})") if doubtful else (1.0, typ)
                s["expected_return"] = u.get("expected_return")
        elif heuristic and n_games >= 2 and s["share_min"] >= REGULAR_SHARE and s["player_id"] not in present_last:
            weight, label = 1.0, "absent du dernier match"
        s["auto_weight"], s["auto_label"] = weight, label

        ov = overrides.get(s["player_id"])
        s["override"] = ov
        s["weight"] = 1.0 if ov == "absent" else 0.0 if ov == "present" else weight
        s["absent"] = s["weight"] > 0

    total_q = sum(s["quality"] for s in squad if s["share_min"] >= 0.1) or 1.0
    att_share = sum(s["weight"] * s["share_att"] for s in squad)
    def_share = sum(s["weight"] * s["share_min"] * (1.5 if s["position"] == "GB" else 1.0) / 5
                    for s in squad if s["position"] in ("DEF", "GB"))
    rating_share = sum(s["weight"] * s["quality"] for s in squad if s["share_min"] >= 0.1) / total_q

    usual = sorted([s for s in squad if s["rating"]], key=lambda s: -s["minutes"])[:11]
    xi = [s for s in squad if confirmed and _in(s, starters) and s["rating"]]
    source = ("Composition officielle" if confirmed else "FotMob (blessés / suspendus)" if tctx
              else "Heuristique (dernier match)" if heuristic else "Aucune info de composition")
    squad.sort(key=lambda s: (-s["weight"], -s["minutes"]))
    for s in squad:
        s.pop("quality", None)
    return {
        "team_id": tid, "att_share": round(att_share, 4), "def_share": round(def_share, 4),
        "rating_share": round(rating_share, 4), "source": source, "lineup_confirmed": confirmed,
        "formation": tctx.get("formation") if confirmed else None,
        "xi_rating": round(sum(s["rating"] for s in xi) / len(xi), 2) if xi else None,
        "usual_xi_rating": round(sum(s["rating"] for s in usual) / len(usual), 2) if usual else None,
        "last_match_id": last["id"] if last else None, "roster_checked": bool(tctx) or heuristic,
        "absent": [s for s in squad if s["absent"]], "squad": squad,
    }


def _in(s: dict, group: dict) -> bool:
    if s["fid"] and s["fid"] in group:
        return True
    return _find(s["name"], group) is not None
