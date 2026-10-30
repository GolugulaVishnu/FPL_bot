"""Keep the data store up to date: past seasons once, the current season daily."""
from __future__ import annotations

import logging
from pathlib import Path

from .datastore import DataStore
from .fpl_api import FplPublicClient
from .schedule import parse_events
from .sources import current, history

DEFAULT_HISTORY = ("2024-25", "2025-26")
FINISHED_EVENT_MAX_AGE = 10 * 365 * 24 * 3600  # a data-checked gameweek never changes

log = logging.getLogger("fplbot.data")


def load_history(store: DataStore, cache: Path, seasons=DEFAULT_HISTORY) -> dict[str, int]:
    counts = {}
    for s in seasons:
        folder = history.download(s, cache)
        m, f, t = history.parse(s, folder)
        store.replace_season(s, m, f, t)
        counts[s] = len(m)
    return counts


def fetch_current(client: FplPublicClient, bootstrap_max_age: float = 6 * 3600) -> tuple[dict, list, dict[int, dict]]:
    """Bootstrap, fixtures and every finished gameweek's live data (finished ones are cached for good)."""
    bootstrap = client.bootstrap(bootstrap_max_age)
    fixtures = client.fixtures(bootstrap_max_age)
    lives = {}
    for e in parse_events(bootstrap):
        if e.finished and e.data_checked:
            lives[e.id] = client.event_live(e.id, max_age=FINISHED_EVENT_MAX_AGE)
    return bootstrap, fixtures, lives


def load_current(store: DataStore, bootstrap: dict, fixtures: list, lives: dict[int, dict]) -> tuple[str, int]:
    season, m, f, t = current.parse(bootstrap, fixtures, lives)
    store.replace_season(season, m, f, t)
    return season, len(m)
