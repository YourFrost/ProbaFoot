"""Stockage SQLite."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DATA_DIR, DB_PATH

write_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches(
    id TEXT PRIMARY KEY, league TEXT, season INTEGER, kickoff TEXT,
    home_id TEXT, home TEXT, away_id TEXT, away TEXT,
    is_result INTEGER, hg INTEGER, ag INTEGER, hxg REAL, axg REAL,
    hnpxg REAL, anpxg REAL, hxpts REAL, axpts REAL, updated_at TEXT);
CREATE INDEX IF NOT EXISTS idx_matches_kickoff ON matches(kickoff);
CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league, season);

CREATE TABLE IF NOT EXISTS players(
    league TEXT, season INTEGER, player_id TEXT, name TEXT, team TEXT, position TEXT,
    games INTEGER, minutes INTEGER, goals INTEGER, xg REAL, assists INTEGER, xa REAL,
    PRIMARY KEY(league, season, player_id));

CREATE TABLE IF NOT EXISTS rosters(
    match_id TEXT, team_id TEXT, player_id TEXT, player TEXT, position TEXT, minutes INTEGER,
    PRIMARY KEY(match_id, player_id));
CREATE TABLE IF NOT EXISTS rosters_fetched(match_id TEXT PRIMARY KEY);

CREATE TABLE IF NOT EXISTS odds(
    match_id TEXT PRIMARY KEY, odds_h REAL, odds_d REAL, odds_a REAL,
    over25 REAL, under25 REAL, updated_at TEXT);

CREATE TABLE IF NOT EXISTS predictions(
    match_id TEXT, source TEXT, created_at TEXT, updated_at TEXT, model_version TEXT,
    p_home REAL, p_draw REAL, p_away REAL, xg_home REAL, xg_away REAL, pick TEXT, data TEXT,
    PRIMARY KEY(match_id, source));

CREATE TABLE IF NOT EXISTS manual_absences(
    match_id TEXT, team_id TEXT, player_id TEXT, player TEXT, status TEXT,
    PRIMARY KEY(match_id, player_id));

CREATE TABLE IF NOT EXISTS weights_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, weights TEXT, params TEXT,
    n_samples INTEGER, logloss_before REAL, logloss_after REAL, note TEXT);

CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

-- FotMob : correspondance des équipes, calendrier coupes/Europe, contexte des matchs, notes
CREATE TABLE IF NOT EXISTS team_map(fotmob_id TEXT PRIMARY KEY, understat_id TEXT, name TEXT);
CREATE TABLE IF NOT EXISTS calendar(
    fotmob_id TEXT PRIMARY KEY, comp_id INTEGER, comp TEXT, kind TEXT, kickoff TEXT,
    home_fid TEXT, home TEXT, away_fid TEXT, away TEXT, hs INTEGER, as_ INTEGER, finished INTEGER);
CREATE INDEX IF NOT EXISTS idx_calendar_kickoff ON calendar(kickoff);
CREATE TABLE IF NOT EXISTS match_context(match_id TEXT PRIMARY KEY, fotmob_id TEXT, fetched_at TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS player_ratings(
    fotmob_match_id TEXT, match_id TEXT, team_fid TEXT, player_fid TEXT, name TEXT,
    rating REAL, minutes INTEGER, started INTEGER, PRIMARY KEY(fotmob_match_id, player_fid));
CREATE INDEX IF NOT EXISTS idx_ratings_team ON player_ratings(team_fid);

-- Cotes par bookmaker
CREATE TABLE IF NOT EXISTS odds_books(
    match_id TEXT, bookmaker TEXT, h REAL, d REAL, a REAL, over25 REAL, under25 REAL, updated_at TEXT,
    PRIMARY KEY(match_id, bookmaker));

-- Alertes et suivi de la fenêtre « composition officielle »
CREATE TABLE IF NOT EXISTS alerts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, kind TEXT, match_id TEXT, title TEXT, body TEXT, seen INTEGER);
CREATE TABLE IF NOT EXISTS lineup_events(
    match_id TEXT PRIMARY KEY, lineup_at TEXT, minutes_before REAL, p_before TEXT, p_after TEXT, market_at TEXT);

-- Cotes de clôture et handicap asiatique (historique football-data)
CREATE TABLE IF NOT EXISTS odds_closing(match_id TEXT PRIMARY KEY, h REAL, d REAL, a REAL, over25 REAL, under25 REAL);
CREATE TABLE IF NOT EXISTS odds_ah(match_id TEXT PRIMARY KEY, line REAL, h REAL, a REAL, close_line REAL, close_h REAL, close_a REAL);

-- Historique des cotes (un point à chaque changement, relevé toutes les heures)
CREATE TABLE IF NOT EXISTS odds_history(
    match_id TEXT, bookmaker TEXT, ts TEXT, h REAL, d REAL, a REAL,
    PRIMARY KEY(match_id, bookmaker, ts));

-- Buts attendus implicites des cotes (pour les ratings « cotes passées »)
CREATE TABLE IF NOT EXISTS odds_implied(match_id TEXT PRIMARY KEY, lh REAL, la REAL);

-- Bankroll : 'manual' = paris saisis, 'auto' = simulation automatique sur les value bets
CREATE TABLE IF NOT EXISTS bets(
    id INTEGER PRIMARY KEY AUTOINCREMENT, book TEXT, created_at TEXT, match_id TEXT,
    market TEXT, selection TEXT, odds REAL, stake REAL, bookmaker TEXT, p_model REAL, edge REAL,
    status TEXT, profit REAL, settled_at TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS idx_bets_match ON bets(match_id);
"""

MIGRATIONS = [("matches", "fotmob_id", "TEXT"), ("bets", "closing_odds", "REAL"), ("bets", "clv", "REAL"), ("bets", "score", "REAL")]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        for table, col, typ in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, json.dumps(value)))
