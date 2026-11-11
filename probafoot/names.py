"""Rapprochement des noms d'équipes entre sources (Understat vs football-data)."""
import re
import unicodedata
from difflib import SequenceMatcher

# Nom football-data normalisé -> nom Understat normalisé
ALIASES = {
    "man city": "manchester city",
    "man united": "manchester united",
    "nott m forest": "nottingham forest",
    "wolves": "wolverhampton wanderers",
    "newcastle": "newcastle united",
    "sheffield united": "sheffield united",
    "paris sg": "paris saint germain",
    "ath madrid": "atletico madrid",
    "ath bilbao": "athletic club",
    "betis": "real betis",
    "celta": "celta vigo",
    "sociedad": "real sociedad",
    "vallecano": "rayo vallecano",
    "espanol": "espanyol",
    "la coruna": "deportivo la coruna",
    "sp gijon": "sporting gijon",
    "oviedo": "real oviedo",
    "m gladbach": "borussia m gladbach",
    "ein frankfurt": "eintracht frankfurt",
    "fc koln": "fc cologne",
    "leverkusen": "bayer leverkusen",
    "rb leipzig": "rasenballsport leipzig",
    "dortmund": "borussia dortmund",
    "hertha": "hertha berlin",
    "milan": "ac milan",
    "st etienne": "saint etienne",
    "st pauli": "st pauli",
}
_STOP = {"fc", "cf", "afc", "sc", "ssc", "as", "ac", "us", "club", "de", "calcio", "1913", "1907"}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return ALIASES.get(s, s)


def similarity(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if na == nb:
        return 1.0
    ta, tb = set(na.split()) - _STOP, set(nb.split()) - _STOP
    jacc = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    contain = 0.9 if (na in nb or nb in na) else 0.0
    return max(jacc, contain, SequenceMatcher(None, na, nb).ratio())
