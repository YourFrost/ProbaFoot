"""Informations de contexte : classement, derby, repos toutes compétitions, prochain match européen.

Testées comme facteurs de calcul (fatigue, rotation, enjeu, derby, météo) : aucune n'améliorait
la précision sur le backtest, elles sont donc seulement affichées."""
from collections import defaultdict
from functools import lru_cache

from .names import similarity

DAY = 86400.0

DERBIES = [
    # Angleterre
    ("Arsenal", "Tottenham"), ("Liverpool", "Everton"), ("Manchester City", "Manchester United"),
    ("Chelsea", "Tottenham"), ("Arsenal", "Chelsea"), ("Newcastle United", "Sunderland"),
    ("Aston Villa", "Wolverhampton Wanderers"), ("Crystal Palace", "Brighton"), ("West Ham", "Tottenham"),
    ("Chelsea", "Fulham"), ("Leeds", "Manchester United"),
    # Espagne
    ("Real Madrid", "Atletico Madrid"), ("Real Madrid", "Barcelona"), ("Barcelona", "Espanyol"),
    ("Sevilla", "Real Betis"), ("Athletic Club", "Real Sociedad"), ("Valencia", "Levante"),
    ("Real Madrid", "Rayo Vallecano"), ("Getafe", "Real Madrid"),
    # Allemagne
    ("Borussia Dortmund", "Schalke 04"), ("Bayern Munich", "Borussia Dortmund"),
    ("FC Cologne", "Borussia M.Gladbach"), ("Hamburger SV", "Werder Bremen"), ("Hamburger SV", "St. Pauli"),
    ("Hertha Berlin", "Union Berlin"), ("Eintracht Frankfurt", "Mainz 05"), ("VfB Stuttgart", "Freiburg"),
    # Italie
    ("Inter", "AC Milan"), ("Roma", "Lazio"), ("Juventus", "Torino"), ("Genoa", "Sampdoria"),
    ("Inter", "Juventus"), ("Napoli", "Roma"), ("Fiorentina", "Juventus"),
    # France
    ("Paris Saint Germain", "Marseille"), ("Lyon", "Saint-Etienne"), ("Nice", "Monaco"),
    ("Lille", "Lens"), ("Nantes", "Rennes"), ("Marseille", "Nice"), ("Lyon", "Marseille"),
]


@lru_cache(maxsize=4096)
def is_derby(home: str, away: str) -> bool:
    for a, b in DERBIES:
        if (similarity(home, a) > 0.85 and similarity(away, b) > 0.85) or \
           (similarity(home, b) > 0.85 and similarity(away, a) > 0.85):
            return True
    return False


def rest_and_rotation(ds, m: dict) -> dict:
    """Jours de repos (toutes compétitions) et prochain match de coupe/Europe."""
    out = {}
    for side, s in (("home", "h"), ("away", "a")):
        tid = m[f"{side}_id"]
        last_ts, last_comp = ds.last_any(tid, m["ts"])
        nxt = ds.next_cup(tid, m["ts"])
        out[f"rest_{s}"] = round((m["ts"] - last_ts) / DAY, 1) if last_ts else None
        out[f"rest_comp_{s}"] = last_comp
        days_next = (nxt["ts"] - m["ts"]) / DAY if nxt else None
        out[f"next_cup_{s}"] = ({"comp": nxt["comp"], "kind": nxt["kind"], "days": round(days_next, 1),
                                 "opponent": nxt["opponent"], "kickoff": nxt["kickoff"]}
                                if nxt and days_next <= 7 else None)
        # rotation probable si un match européen arrive dans les 3 jours suivants
        out[f"rotation_{s}"] = int(bool(nxt and nxt["kind"] == "europe" and days_next <= 3.5))
    return out


def standings(ds, league: str, season: int, ts: float) -> tuple[list[dict], dict]:
    """Classement avant ts + nombre de matchs restants par équipe."""
    table = defaultdict(lambda: {"pts": 0, "gd": 0, "gf": 0, "played": 0, "total": 0})
    for g in ds.season_games.get((league, season), []):
        for tid in (g["home_id"], g["away_id"]):
            table[tid]["total"] += 1
            table[tid]["team"] = g["home"] if tid == g["home_id"] else g["away"]
            table[tid]["team_id"] = tid
        if g["is_result"] and g["hg"] is not None and g["ts"] < ts:
            h, a = table[g["home_id"]], table[g["away_id"]]
            h["played"] += 1
            a["played"] += 1
            h["gf"] += g["hg"]
            a["gf"] += g["ag"]
            h["gd"] += g["hg"] - g["ag"]
            a["gd"] += g["ag"] - g["hg"]
            if g["hg"] > g["ag"]:
                h["pts"] += 3
            elif g["hg"] < g["ag"]:
                a["pts"] += 3
            else:
                h["pts"] += 1
                a["pts"] += 1
    rows = sorted(table.values(), key=lambda r: (-r["pts"], -r["gd"], -r["gf"]))
    for i, r in enumerate(rows):
        r["pos"] = i + 1
        r["remaining"] = r["total"] - r["played"]
    return rows, {r["team_id"]: r for r in rows}


def positions(ds, m: dict) -> dict:
    """Classement et points des deux équipes avant le match."""
    _, by_id = standings(ds, m["league"], m["season"], m["ts"])
    out = {}
    for side, s in (("home", "h"), ("away", "a")):
        r = by_id.get(m[f"{side}_id"]) or {}
        out[f"pos_{s}"] = r.get("pos") if r.get("played") else None
        out[f"pts_{s}"] = r.get("pts") if r.get("played") else None
    return out
