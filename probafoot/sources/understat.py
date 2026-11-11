"""Source Understat : calendrier, résultats, xG, stats joueurs, compositions."""
import json
import math

from ..http import fetch

BASE = "https://understat.com"
XHR = {"X-Requested-With": "XMLHttpRequest", "Referer": BASE + "/"}


def league_data(league: str, season: int, ttl: float = math.inf) -> dict:
    """{'teams': {...}, 'players': [...], 'dates': [...]} pour une ligue/saison."""
    return json.loads(fetch(f"{BASE}/getLeagueData/{league}/{season}", ttl=ttl, headers=XHR))


def match_data(match_id: str) -> dict:
    """Compositions (joueurs ayant joué) d'un match terminé : immuable, cache infini."""
    return json.loads(fetch(f"{BASE}/getMatchData/{match_id}", headers=XHR))
