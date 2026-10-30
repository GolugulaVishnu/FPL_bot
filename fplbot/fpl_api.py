"""Read-only client for the public FPL API, with an on-disk cache.

Requests are spaced out and cached so the bot stays low-frequency (CLAUDE.md).
A 403 means FPL's bot protection refused the request: the bot stops and
reports it, and never tries to get around it.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import requests

BASE_URL = "https://fantasy.premierleague.com/api/"
USER_AGENT = "fplbot/0.1 (personal FPL team manager)"

log = logging.getLogger("fplbot.api")


class FplError(RuntimeError):
    pass


class FplBlocked(FplError):
    """FPL refused the request (HTTP 403). Needs a human; do not retry around it."""


class FplPublicClient:
    def __init__(self, cache_dir: Path, session: requests.Session | None = None,
                 min_interval: float = 2.0, timeout: float = 20):
        self.cache_dir = cache_dir
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.min_interval = min_interval
        self.timeout = timeout
        self._last_request = 0.0

    def _cache_file(self, path: str) -> Path:
        name = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "root"
        return self.cache_dir / f"{name}.json"

    def cache_age(self, path: str) -> float | None:
        f = self._cache_file(path)
        return time.time() - f.stat().st_mtime if f.exists() else None

    def get(self, path: str, max_age: float = 6 * 3600) -> dict | list:
        """Return JSON for `path`, from cache if it is younger than `max_age` seconds."""
        f = self._cache_file(path)
        age = self.cache_age(path)
        if age is not None and age < max_age:
            return json.loads(f.read_text(encoding="utf-8"))

        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        try:
            r = self.session.get(BASE_URL + path, timeout=self.timeout)
        except requests.RequestException as e:
            raise FplError(f"FPL request failed for {path}: {type(e).__name__}") from e
        if r.status_code == 403:
            raise FplBlocked(f"FPL refused {path} (HTTP 403)")
        if r.status_code != 200:
            raise FplError(f"FPL returned HTTP {r.status_code} for {path}")
        data = r.json()
        f.write_text(json.dumps(data), encoding="utf-8")
        return data

    def bootstrap(self, max_age: float = 6 * 3600) -> dict:
        return self.get("bootstrap-static/", max_age)

    def fixtures(self, max_age: float = 6 * 3600) -> list:
        return self.get("fixtures/", max_age)

    def event_live(self, event_id: int, max_age: float = 3600) -> dict:
        return self.get(f"event/{event_id}/live/", max_age)

    def element_summary(self, element_id: int, max_age: float = 24 * 3600) -> dict:
        return self.get(f"element-summary/{element_id}/", max_age)
