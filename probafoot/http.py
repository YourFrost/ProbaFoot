"""Téléchargement poli : limitation de débit par hôte + cache disque."""
import hashlib
import logging
import math
import threading
import time
from urllib.parse import urlparse

import requests

from .config import CACHE_DIR, UNDERSTAT_DELAY

log = logging.getLogger(__name__)
_lock = threading.Lock()
_last_call: dict[str, float] = {}
USER_AGENT = "Mozilla/5.0 (compatible; ProbaFoot/1.0; usage personnel)"


def fetch(url: str, ttl: float = math.inf, headers: dict | None = None) -> bytes:
    """Renvoie le contenu d'une URL, depuis le cache s'il a moins de `ttl` secondes."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / hashlib.sha1(url.encode()).hexdigest()
    if path.exists() and time.time() - path.stat().st_mtime < ttl:
        return path.read_bytes()

    host = urlparse(url).netloc
    with _lock:
        wait = _last_call.get(host, 0) + UNDERSTAT_DELAY - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.time()

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT, **(headers or {})}, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        if path.exists():
            log.warning("Échec de %s, utilisation du cache périmé", url)
            return path.read_bytes()
        raise
    path.write_bytes(resp.content)
    return resp.content
