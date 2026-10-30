"""Save a snapshot of live FPL data into the repo so the model can be built against real data."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .data import fetch_current
from .fpl_api import FplPublicClient

SAMPLES_DIR = "samples"


def capture(client: FplPublicClient, repo: Path, now: datetime | None = None) -> list[Path]:
    """Fetch bootstrap-static, fixtures and every finished gameweek's live data into samples/<UTC date>/.

    Bootstrap and fixtures are always fetched fresh. Finished gameweeks are cached
    for good after the first fetch, so a repeat capture costs two requests.
    """
    now = now or datetime.now(timezone.utc)
    out = repo / SAMPLES_DIR / now.strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)

    bootstrap, fixtures, lives = fetch_current(client, bootstrap_max_age=0)
    files = {"bootstrap-static.json": bootstrap, "fixtures.json": fixtures}
    files.update({f"event-{gw}-live.json": live for gw, live in sorted(lives.items())})

    written = []
    for name, data in files.items():
        p = out / name
        p.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        written.append(p)
    return written
