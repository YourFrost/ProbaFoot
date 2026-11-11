"""Source football-data.co.uk : cotes bookmakers (historique + matchs de la semaine)."""
import io
import math
from datetime import datetime

import pandas as pd

from ..http import fetch

BASE = "https://www.football-data.co.uk"


def _read_csv(raw: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(io.StringIO(raw.decode(enc)), on_bad_lines="skip")
        except UnicodeDecodeError:
            continue
    return pd.DataFrame()


def _num(row, *cols):
    for c in cols:
        v = row.get(c)
        if v is not None and not pd.isna(v):
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v > 1.0:
                return v
    return None


# Préfixe de colonne football-data -> nom du bookmaker (cotes 1N2 : <préfixe>H/D/A)
BOOKMAKERS = {
    "B365": "Bet365", "BFD": "Betfred", "BMGM": "BetMGM", "BV": "BetVictor", "BW": "Bwin",
    "CL": "Coral", "LB": "Ladbrokes", "PS": "Pinnacle", "IW": "Interwetten", "VC": "VC Bet", "PP": "Paddy Power", "SKB": "Sky Bet",
    "WH": "William Hill", "1XB": "1xBet", "BFE": "Betfair Exchange", "Max": "Max", "Avg": "Avg",
}
# Préfixe des colonnes +/-2.5 buts -> préfixe 1N2 correspondant
OU_PREFIX = {"B365": "B365", "P": "PS", "BFE": "BFE", "Max": "Max", "Avg": "Avg", "BW": "BW", "WH": "WH"}


def _books(row) -> dict:
    out = {}
    for pre, name in BOOKMAKERS.items():
        h, d, a = _num(row, pre + "H"), _num(row, pre + "D"), _num(row, pre + "A")
        if h and d and a:
            out[name] = {"h": h, "d": d, "a": a, "over25": None, "under25": None}
    if "Max" not in out:  # avant 2019/20 : colonnes BetBrain
        h, d, a = _num(row, "BbMxH"), _num(row, "BbMxD"), _num(row, "BbMxA")
        if h and d and a:
            out["Max"] = {"h": h, "d": d, "a": a, "over25": _num(row, "BbMx>2.5"), "under25": _num(row, "BbMx<2.5")}
    for ou, pre in OU_PREFIX.items():
        name = BOOKMAKERS[pre]
        o, u = _num(row, ou + ">2.5"), _num(row, ou + "<2.5")
        if o and u:
            out.setdefault(name, {"h": None, "d": None, "a": None})
            out[name].update(over25=o, under25=u)
    return out


def _flt(row, *cols):
    for c in cols:
        v = row.get(c)
        if v is not None and not pd.isna(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _rows(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        if pd.isna(r.get("HomeTeam")) or pd.isna(r.get("Date")):
            continue
        try:
            d = datetime.strptime(str(r["Date"]), "%d/%m/%Y").date()
        except ValueError:
            try:
                d = datetime.strptime(str(r["Date"]), "%d/%m/%y").date()
            except ValueError:
                continue
        out.append({
            "div": r.get("Div"),
            "date": d,
            "home": str(r["HomeTeam"]),
            "away": str(r["AwayTeam"]),
            # cotes moyennes d'avant-match (pas de clôture : même info qu'en live)
            "odds_h": _num(r, "AvgH", "BbAvH", "B365H", "PSH"),
            "odds_d": _num(r, "AvgD", "BbAvD", "B365D", "PSD"),
            "odds_a": _num(r, "AvgA", "BbAvA", "B365A", "PSA"),
            "over25": _num(r, "Avg>2.5", "BbAv>2.5", "B365>2.5"),
            "under25": _num(r, "Avg<2.5", "BbAv<2.5", "B365<2.5"),
            "books": _books(r),
            # cotes de clôture (juste avant le coup d'envoi) : référence pour mesurer la qualité d'un pari
            "close": {"h": _num(r, "PSCH", "AvgCH"), "d": _num(r, "PSCD", "AvgCD"), "a": _num(r, "PSCA", "AvgCA"),
                      "over25": _num(r, "PC>2.5", "AvgC>2.5"), "under25": _num(r, "PC<2.5", "AvgC<2.5")},
            # handicap asiatique : ligne (pour l'équipe à domicile) et meilleures cotes
            "ah": {"line": _flt(r, "AHh", "BbAHh"), "h": _num(r, "MaxAHH", "BbMxAHH", "AvgAHH"), "a": _num(r, "MaxAHA", "BbMxAHA", "AvgAHA"),
                   "close_line": _flt(r, "AHCh"), "close_h": _num(r, "PCAHH", "AvgCAHH"), "close_a": _num(r, "PCAHA", "AvgCAHA")},
        })
    return out


def season_odds(div: str, season: int, ttl: float = math.inf) -> list[dict]:
    code = f"{season % 100:02d}{(season + 1) % 100:02d}"
    return _rows(_read_csv(fetch(f"{BASE}/mmz4281/{code}/{div}.csv", ttl=ttl)))


def upcoming_odds(ttl: float = 3000) -> list[dict]:
    return _rows(_read_csv(fetch(f"{BASE}/fixtures.csv", ttl=ttl)))
