"""Where the bot keeps its files.

The repo holds code and the cards the bot publishes. Everything else (database,
cache, logs, local config) lives in a per-user data folder outside the repo so
it is never committed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    override = os.environ.get("FPLBOT_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "fplbot"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "fplbot"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "fplbot"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_dir() -> Path:
    d = data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "config.json"


def db_path() -> Path:
    return data_dir() / "fplbot.sqlite3"


def pause_flag() -> Path:
    return data_dir() / "PAUSED"
