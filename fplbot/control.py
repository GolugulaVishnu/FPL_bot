"""Kill switch, run lock and primary/backup failover (system-flow.md, section 2)."""
from __future__ import annotations

import os
import time
from pathlib import Path

HEARTBEAT_WINDOW = "30m"
STALE_LOCK_SECONDS = 30 * 60


# --- Kill switch ---------------------------------------------------------

def apply_control_messages(messages: list[dict], flag: Path, last_seen_id: str | None) -> str | None:
    """Apply 'pause' / 'resume' messages from the ntfy control topic to the local flag file.

    ntfy.sh only keeps messages for about 12 hours, so the state is copied into a
    local flag file. Returns the id of the newest message handled.
    """
    newest = last_seen_id
    ids = [m.get("id") for m in messages]
    start = ids.index(last_seen_id) + 1 if last_seen_id in ids else 0
    for m in messages[start:]:
        cmd = (m.get("message") or "").strip().lower()
        if cmd == "pause":
            flag.write_text("paused from ntfy control topic\n", encoding="utf-8")
        elif cmd == "resume":
            flag.unlink(missing_ok=True)
        newest = m.get("id", newest)
    return newest


def is_paused(flag: Path) -> bool:
    return flag.exists()


# --- Run lock ------------------------------------------------------------

class LockBusy(RuntimeError):
    pass


class RunLock:
    """Stops two runs on the same machine overlapping. A lock older than 30 min is treated as stale."""

    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> "RunLock":
        if self.path.exists() and time.time() - self.path.stat().st_mtime > STALE_LOCK_SECONDS:
            self.path.unlink(missing_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as e:
            raise LockBusy("another run is in progress") from e
        os.write(self.fd, str(os.getpid()).encode())
        return self

    def __exit__(self, *exc) -> None:
        if self.fd is not None:
            os.close(self.fd)
        self.path.unlink(missing_ok=True)


# --- Failover ------------------------------------------------------------

def backup_should_run(recent_heartbeats: list[dict] | None) -> bool:
    """The backup runs only when the primary has posted no heartbeat in the last 30 minutes.

    `None` means the heartbeat topic could not be read; the backup then stays in
    standby, because the read-back before every FPL write is what prevents double
    submits and a network blip on the backup should not make it take over.
    """
    if recent_heartbeats is None:
        return False
    return len(recent_heartbeats) == 0
