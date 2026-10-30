"""Local SQLite store: job state and the run log."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  machine TEXT NOT NULL,
  job TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT
);
"""


class Store:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def get_state(self) -> dict:
        return {k: json.loads(v) for k, v in self.conn.execute("SELECT key, value FROM state")}

    def set_state(self, key: str, value) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO state(key, value) VALUES(?, ?) "
                              "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                              (key, json.dumps(value)))

    def log_run(self, machine: str, job: str, status: str, detail: str = "") -> None:
        with self.conn:
            self.conn.execute("INSERT INTO run_log(ts, machine, job, status, detail) VALUES(?, ?, ?, ?, ?)",
                              (datetime.now(timezone.utc).isoformat(timespec="seconds"), machine, job, status, detail))

    def recent_runs(self, limit: int = 10) -> list[tuple]:
        return list(self.conn.execute(
            "SELECT ts, machine, job, status, detail FROM run_log ORDER BY id DESC LIMIT ?", (limit,)))
