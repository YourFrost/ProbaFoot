"""Chargement des matchs en mémoire + index rapides (équipe, confrontation, ligue)."""
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime

import numpy as np

from . import models
from .config import DEFAULT_PARAMS


def parse_ts(kickoff: str) -> float:
    return datetime.fromisoformat(kickoff.replace("Z", "+00:00")).timestamp()


class LeagueArrays:
    """Matchs joués d'une ligue sous forme de tableaux numpy triés par date."""

    def __init__(self, games: list[dict], team_ids: set[str]):
        self.idx = {tid: i for i, tid in enumerate(sorted(team_ids))}
        self.n_teams = len(self.idx)
        self.ts = np.array([g["ts"] for g in games], dtype=float)
        self.h = np.array([self.idx[g["home_id"]] for g in games], dtype=int)
        self.a = np.array([self.idx[g["away_id"]] for g in games], dtype=int)
        self.hg = np.array([g["hg"] for g in games], dtype=float)
        self.ag = np.array([g["ag"] for g in games], dtype=float)
        self.hx = np.array([g["hx"] for g in games], dtype=float)
        self.ax = np.array([g["ax"] for g in games], dtype=float)


class ImpliedArrays:
    """Buts attendus implicites des cotes, par ligue, triés par date."""

    def __init__(self, games: list[dict], implied: dict, idx: dict):
        self.n_teams = len(idx)
        self.ts = np.array([g["ts"] for g in games], dtype=float)
        self.h = np.array([idx[g["home_id"]] for g in games], dtype=int)
        self.a = np.array([idx[g["away_id"]] for g in games], dtype=int)
        self.lh = np.array([implied[g["id"]][0] for g in games], dtype=float)
        self.la = np.array([implied[g["id"]][1] for g in games], dtype=float)


class Dataset:
    def __init__(self, conn, params: dict | None = None):
        params = params or DEFAULT_PARAMS
        rows = [dict(r) for r in conn.execute("SELECT * FROM matches ORDER BY kickoff, id")]
        for r in rows:
            r["ts"] = parse_ts(r["kickoff"])
            # xG sans penalty si dispo (plus prédictif), sinon xG, sinon buts
            r["hx"] = _first(r["hnpxg"], r["hxg"], r["hg"])
            r["ax"] = _first(r["anpxg"], r["axg"], r["ag"])
        self.matches = {r["id"]: r for r in rows}
        self.played = [r for r in rows if r["is_result"] and r["hg"] is not None]

        self.team_games = defaultdict(list)
        self.pair_games = defaultdict(list)
        self.season_teams = defaultdict(set)
        league_teams = defaultdict(set)
        for r in rows:
            self.season_teams[(r["league"], r["season"])].update((r["home_id"], r["away_id"]))
            league_teams[r["league"]].update((r["home_id"], r["away_id"]))
        for r in self.played:
            self.team_games[r["home_id"]].append(r)
            self.team_games[r["away_id"]].append(r)
            self.pair_games[frozenset((r["home_id"], r["away_id"]))].append(r)
        self._team_ts = {t: [g["ts"] for g in gs] for t, gs in self.team_games.items()}

        self.leagues = {
            lg: LeagueArrays([g for g in self.played if g["league"] == lg], teams)
            for lg, teams in league_teams.items()
        }

        # Cotes des matchs passés -> buts attendus implicites (calculés une fois, mis en cache)
        implied = {r["match_id"]: (r["lh"], r["la"]) for r in conn.execute("SELECT * FROM odds_implied")}
        new = []
        self.implied_probs = {}  # probabilités 1N2 d'avant-match (pour la forme « vs attendu »)
        for o in conn.execute("SELECT * FROM odds"):
            p = models.market_probs(dict(o))
            if p and o["match_id"] in self.matches:
                self.implied_probs[o["match_id"]] = p
            if not p or o["match_id"] in implied or o["match_id"] not in self.matches:
                continue
            over = None
            if o["over25"] and o["under25"]:
                over = (1 / o["over25"]) / (1 / o["over25"] + 1 / o["under25"])
            implied[o["match_id"]] = models.implied_goals(p, over)
            new.append((o["match_id"], *implied[o["match_id"]]))
        if new:
            try:
                conn.executemany("INSERT OR REPLACE INTO odds_implied VALUES(?,?,?)", new)
                conn.commit()
            except Exception:  # base occupée : on recalculera la prochaine fois
                pass
        self.implied = {}
        for lg, la in self.leagues.items():
            games = sorted((m for mid, m in self.matches.items() if mid in implied and m["league"] == lg),
                           key=lambda m: m["ts"])
            self.implied[lg] = ImpliedArrays(games, implied, la.idx)

        # Coupes et matchs européens (FotMob), rattachés aux équipes Understat
        fm2us = {r["fotmob_id"]: r["understat_id"] for r in conn.execute("SELECT * FROM team_map")}
        self.cup_games = defaultdict(list)
        for c in conn.execute("SELECT * FROM calendar ORDER BY kickoff"):
            c = dict(c)
            c["ts"] = parse_ts(c["kickoff"])
            for fid, opp in ((c["home_fid"], c["away"]), (c["away_fid"], c["home"])):
                if fid in fm2us:
                    self.cup_games[fm2us[fid]].append({**c, "opponent": opp})
        self._cup_ts = {t: [g["ts"] for g in gs] for t, gs in self.cup_games.items()}
        self.season_games = defaultdict(list)  # (ligue, saison) -> tous les matchs (standings / restants)
        for r in rows:
            self.season_games[(r["league"], r["season"])].append(r)

    def last_any(self, team_id: str, ts: float) -> tuple[float | None, str | None]:
        """Dernier match toutes compétitions avant ts : (timestamp, compétition)."""
        lg = self.last_game(team_id, ts)
        best = (lg["ts"], "Championnat") if lg else (None, None)
        cts = self._cup_ts.get(team_id, [])
        i = bisect_left(cts, ts)
        if i > 0 and (best[0] is None or cts[i - 1] > best[0]):
            best = (cts[i - 1], self.cup_games[team_id][i - 1]["comp"])
        return best

    def next_cup(self, team_id: str, ts: float) -> dict | None:
        """Prochain match de coupe / européen après ts."""
        cts = self._cup_ts.get(team_id, [])
        i = bisect_left(cts, ts + 3600)
        return self.cup_games[team_id][i] if i < len(cts) else None

    def prev_cup(self, team_id: str, ts: float) -> dict | None:
        cts = self._cup_ts.get(team_id, [])
        i = bisect_left(cts, ts)
        return self.cup_games[team_id][i - 1] if i > 0 else None

    def games_before(self, team_id: str, ts: float, n: int | None = None) -> list[dict]:
        games = self.team_games.get(team_id, [])
        end = bisect_left(self._team_ts.get(team_id, []), ts)
        return games[max(0, end - n):end] if n else games[:end]

    def last_game(self, team_id: str, ts: float) -> dict | None:
        g = self.games_before(team_id, ts, 1)
        return g[0] if g else None

    def pair_before(self, a: str, b: str, ts: float) -> list[dict]:
        return [g for g in self.pair_games.get(frozenset((a, b)), []) if g["ts"] < ts]

    def priors(self, league: str, season: int, params: dict) -> dict[int, tuple]:
        """A priori attaque/défense des promus (absents de la ligue la saison précédente)."""
        prev = self.season_teams.get((league, season - 1))
        if not prev:
            return {}
        idx = self.leagues[league].idx
        return {idx[t]: (params["promoted_att"], params["promoted_def"])
                for t in self.season_teams[(league, season)] - prev}


def _first(*vals):
    for v in vals:
        if v is not None:
            return float(v)
    return 0.0
