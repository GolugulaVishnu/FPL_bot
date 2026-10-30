"""Push notifications and remote control over ntfy (https://ntfy.sh)."""
from __future__ import annotations

import json
import logging

import requests

from .logs import scrub

log = logging.getLogger("fplbot.notify")


def _header_safe(text: str) -> str:
    # HTTP headers must be latin-1; keep titles plain.
    return scrub(text).encode("latin-1", "replace").decode("latin-1")


class Ntfy:
    def __init__(self, server: str, session: requests.Session | None = None, timeout: float = 10):
        self.server = server.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout

    def send(self, topic: str, message: str, title: str | None = None,
             priority: str = "default", tags: list[str] | None = None) -> bool:
        headers = {"Priority": priority}
        if title:
            headers["Title"] = _header_safe(title)
        if tags:
            headers["Tags"] = ",".join(tags)
        try:
            r = self.session.post(f"{self.server}/{topic}", data=scrub(message).encode("utf-8"),
                                  headers=headers, timeout=self.timeout)
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            log.warning("ntfy send failed: %s", type(e).__name__)
            return False

    def poll(self, topic: str, since: str = "12h") -> list[dict]:
        """Return cached messages on a topic (ntfy.sh keeps them about 12 hours)."""
        r = self.session.get(f"{self.server}/{topic}/json", params={"poll": "1", "since": since},
                             timeout=self.timeout)
        r.raise_for_status()
        out = []
        for line in r.text.splitlines():
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("event") == "message":
                out.append(msg)
        return out
