"""Save a snapshot of live FPL data into the repo so the model can be built against real data."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .fpl_api import FplPublicClient
from .schedule import latest_checked_event, parse_events

SAMPLES_DIR = "samples"


def capture(client: FplPublicClient, repo: Path, now: datetime | None = None) -> list[Path]:
    """Fetch bootstrap-static, fixtures and the latest finished gameweek's live data.

    Always fetches fresh (no cache) and writes to samples/<UTC date>/.
    """
    now = now or datetime.now(timezone.utc)
    out = repo / SAMPLES_DIR / now.strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)

    bootstrap = client.bootstrap(max_age=0)
    files = {"bootstrap-static.json": bootstrap, "fixtures.json": client.fixtures(max_age=0)}
    last = latest_checked_event(parse_events(bootstrap))
    if last is not None:
        files[f"event-{last.id}-live.json"] = client.event_live(last.id, max_age=0)

    written = []
    for name, data in files.items():
        p = out / name
        p.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        written.append(p)
    return written
