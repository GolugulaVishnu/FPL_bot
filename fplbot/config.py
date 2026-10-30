"""Local, per-machine settings. Stored in the data folder, never in the repo."""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths

DEFAULT_FPL_EMAIL = "soohzabimaru864@gmail.com"
DEFAULT_NTFY_SERVER = "https://ntfy.sh"
ROLES = ("primary", "backup")


@dataclass
class Config:
    role: str = "primary"
    fpl_email: str = DEFAULT_FPL_EMAIL
    ntfy_server: str = DEFAULT_NTFY_SERVER
    # Topic names act as passwords on ntfy.sh: anyone who knows one can read it.
    topic_alerts: str = ""
    topic_control: str = ""
    topic_heartbeat: str = ""
    extra: dict = field(default_factory=dict)

    def topics_set(self) -> bool:
        return bool(self.topic_alerts and self.topic_control and self.topic_heartbeat)


def new_topic(kind: str) -> str:
    return f"fplbot-{kind}-{secrets.token_urlsafe(18)}"


def generate_topics(cfg: Config) -> None:
    cfg.topic_alerts = new_topic("alerts")
    cfg.topic_control = new_topic("control")
    cfg.topic_heartbeat = new_topic("heartbeat")


def load(path: Path | None = None) -> Config:
    path = path or paths.config_path()
    if not path.exists():
        return Config()
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {k: v for k, v in raw.items() if k in Config.__dataclass_fields__}
    return Config(**known)


def save(cfg: Config, path: Path | None = None) -> None:
    if cfg.role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    path = path or paths.config_path()
    path.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
