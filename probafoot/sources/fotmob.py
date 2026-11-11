"""Source FotMob : calendrier toutes compétitions, compositions, indisponibles, notes, météo, arbitre."""
import json
import math
from datetime import date

from ..http import fetch

BASE = "https://www.fotmob.com/api/data"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"}

LEAGUE_IDS = {"EPL": 47, "La_liga": 87, "Bundesliga": 54, "Serie_A": 55, "Ligue_1": 53}
EUROPE = {42: "Ligue des champions", 73: "Ligue Europa", 10216: "Ligue Conférence"}
CUPS = {132: "FA Cup", 133: "EFL Cup", 138: "Copa del Rey", 209: "DFB Pokal",
        141: "Coppa Italia", 134: "Coupe de France"}


def competition_kind(league: dict) -> tuple[str | None, str | None]:
    """('europe'|'cup'|None, nom affiché) pour une compétition de la réponse FotMob."""
    pid, name = league.get("primaryId"), league.get("name", "")
    if pid in EUROPE:
        return "europe", EUROPE[pid]
    if league.get("ccode") == "INT" and "Conference League" in name and "Women" not in name:
        return "europe", "Ligue Conférence"
    if pid in CUPS:
        return "cup", CUPS[pid]
    return None, None


def matches_on(day: date, ttl: float) -> list[dict]:
    raw = fetch(f"{BASE}/matches?date={day:%Y%m%d}", ttl=ttl, headers=HEADERS)
    return json.loads(raw).get("leagues", [])


def match_details(fotmob_id: str, ttl: float = math.inf) -> dict:
    return json.loads(fetch(f"{BASE}/matchDetails?matchId={fotmob_id}", ttl=ttl, headers=HEADERS))


# Pays -> bookmaker affiché par FotMob (grilles de cotes distinctes)
ODDS_COUNTRIES = {"ENG": "Bet365", "FRA": "Unibet", "GBR": "Betfred", "DEU": "Interwetten", "IRL": "Paddy Power"}


def match_odds(fotmob_id: str, ccode: str, ttl: float) -> dict | None:
    """Cotes 1N2 actuelles d'un bookmaker (selon le pays) : {'h','d','a','bookmaker'}."""
    raw = fetch(f"{BASE}/matchOdds?matchId={fotmob_id}&ccode3={ccode}", ttl=ttl, headers=HEADERS)
    if not raw.strip():
        return None
    j = json.loads(raw) or {}
    for mk in ((j.get("odds") or {}).get("matchfactMarkets") or []):
        sel = mk.get("selections") or []
        if len(sel) == 3:
            try:
                h, d, a = (float(str(s.get("oddsDecimal")).replace(",", ".")) for s in sel)
            except (TypeError, ValueError):
                return None
            if min(h, d, a) > 1.0:
                return {"h": h, "d": d, "a": a, "provider": j.get("persistentKey")}
    return None


def live_status(match: dict) -> dict:
    """État d'un match de la liste FotMob : score et minute en direct."""
    st = match.get("status") or {}
    live = st.get("liveTime") or {}
    return {
        "started": bool(st.get("started")), "finished": bool(st.get("finished")),
        "cancelled": bool(st.get("cancelled")), "ongoing": bool(st.get("ongoing")) or (st.get("started") and not st.get("finished")),
        "minute": live.get("short") or live.get("long"),
        "score": st.get("scoreStr") or (f"{match['home'].get('score')} - {match['away'].get('score')}"
                                        if match["home"].get("score") is not None else None),
        "reason": (st.get("reason") or {}).get("short"),
    }


def _minutes(p: dict, started: bool) -> int:
    subs = (p.get("performance") or {}).get("substitutionEvents") or []
    t_in = next((e["time"] for e in subs if e.get("type") == "subIn"), None)
    t_out = next((e["time"] for e in subs if e.get("type") == "subOut"), None)
    if started:
        return int(t_out or 90)
    if t_in is not None:
        return max(int((t_out or 90) - t_in), 1)
    return 0


def parse_details(d: dict) -> dict:
    """Extrait ce qui nous sert d'un matchDetails FotMob."""
    content = d.get("content") or {}
    lineup = content.get("lineup") or {}
    info = (content.get("matchFacts") or {}).get("infoBox") or {}
    teams = {}
    for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
        t = lineup.get(key) or {}
        starters = t.get("starters") or []
        subs = t.get("subs") or []
        players = []
        for p, started in [(p, True) for p in starters] + [(p, False) for p in subs]:
            perf = p.get("performance") or {}
            players.append({"id": str(p.get("id")), "name": p.get("name"), "started": started,
                            "rating": perf.get("rating"), "minutes": _minutes(p, started),
                            "position_id": p.get("usualPlayingPositionId")})
        teams[side] = {
            "team_id": str(t.get("id")) if t.get("id") else None, "name": t.get("name"),
            "formation": t.get("formation"), "players": players, "n_starters": len(starters),
            "unavailable": [{"id": str(u.get("id")), "name": u.get("name"),
                             "type": (u.get("unavailability") or {}).get("type"),
                             "expected_return": (u.get("unavailability") or {}).get("expectedReturn")}
                            for u in t.get("unavailable") or []],
        }
    ref = info.get("Referee") or {}
    stats = {s.get("type"): s.get("value") for s in ref.get("stats") or []}
    stadium = info.get("Stadium") or {}
    w = content.get("weather") or {}
    return {
        "lineup_type": lineup.get("lineupType"),
        "lineup_confirmed": lineup.get("lineupType") != "predicted"
                            and all(teams.get(s, {}).get("n_starters") == 11 for s in ("home", "away")),
        "teams": teams,
        "weather": {k: w.get(k) for k in ("temperature", "windSpeed", "precipitation", "precipChance",
                                          "snow", "description")} if w else None,
        "referee": {"name": ref.get("text"), "matches": stats.get("matches"),
                    "yellow_per_match": stats.get("yellowCards"), "red_total": stats.get("redCards"),
                    "penalties_total": stats.get("penalties"), "fouls_per_match": stats.get("fouls")}
                   if ref.get("text") else None,
        "stadium": {k: stadium.get(k) for k in ("name", "city", "capacity")} if stadium else None,
    }
