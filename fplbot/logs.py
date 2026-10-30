"""Logging to a rotating file in the data folder, with secret scrubbing."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from . import paths

_secrets: set[str] = set()


def register_secret(value: str) -> None:
    if value and len(value) >= 4:
        _secrets.add(value)


def scrub(text: str) -> str:
    for s in _secrets:
        text = text.replace(s, "[REDACTED]")
    return text


class _ScrubFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.getMessage())
        record.args = ()
        return True


def setup(verbose: bool = False) -> logging.Logger:
    log = logging.getLogger("fplbot")
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(paths.log_dir() / "fplbot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(_ScrubFilter())
    log.addHandler(fh)
    if sys.stderr is not None:  # pythonw.exe (scheduled runs on Windows) has no console
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh.addFilter(_ScrubFilter())
        log.addHandler(sh)
    return log
