"""Alertes : composition officielle publiée, nouveau pari conseillé.

Affichées dans l'interface (cloche + notification du navigateur). Envoi Telegram optionnel :
définir les variables d'environnement PROBAFOOT_TELEGRAM_TOKEN et PROBAFOOT_TELEGRAM_CHAT
avant de lancer le serveur (rien n'est envoyé sinon).
"""
import logging
import os

import requests

from .db import now_iso

log = logging.getLogger(__name__)


def create(conn, kind: str, match_id: str | None, title: str, body: str) -> bool:
    """Crée une alerte (une seule par couple type/match/titre)."""
    if conn.execute("SELECT 1 FROM alerts WHERE kind=? AND match_id IS ? AND title=?", (kind, match_id, title)).fetchone():
        return False
    conn.execute("INSERT INTO alerts(created_at, kind, match_id, title, body, seen) VALUES(?,?,?,?,?,0)",
                 (now_iso(), kind, match_id, title, body))
    _telegram(f"{title}\n{body}")
    return True


def _telegram(text: str):
    token, chat = os.environ.get("PROBAFOOT_TELEGRAM_TOKEN"), os.environ.get("PROBAFOOT_TELEGRAM_CHAT")
    if not token or not chat:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text}, timeout=10)
    except requests.RequestException as exc:
        log.warning("Envoi Telegram impossible : %s", exc)


def recent(conn, limit: int = 30) -> dict:
    rows = [dict(r) for r in conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))]
    unseen = conn.execute("SELECT COUNT(*) FROM alerts WHERE seen=0").fetchone()[0]
    return {"alerts": rows, "unseen": unseen, "telegram": bool(os.environ.get("PROBAFOOT_TELEGRAM_TOKEN"))}


def mark_seen(conn):
    conn.execute("UPDATE alerts SET seen=1 WHERE seen=0")
