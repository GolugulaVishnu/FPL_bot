"""Secrets live in the OS keychain (Windows Credential Manager / macOS Keychain).

Nothing in this module prints or logs a secret value. Every value read is also
registered with the log scrubber so it can never reach a log file by accident.
"""
from __future__ import annotations

import keyring

from .logs import register_secret

SERVICE = "fpl-bot"
GITHUB_TOKEN_KEY = "github-token"


class MissingSecret(RuntimeError):
    pass


def _get(username: str, what: str) -> str:
    value = keyring.get_password(SERVICE, username)
    if not value:
        raise MissingSecret(f"{what} is not saved on this machine. Run: fplbot setup")
    register_secret(value)
    return value


def fpl_password(email: str) -> str:
    return _get(email, "The FPL password")


def github_token() -> str:
    return _get(GITHUB_TOKEN_KEY, "The GitHub token")


def has_fpl_password(email: str) -> bool:
    return bool(keyring.get_password(SERVICE, email))


def has_github_token() -> bool:
    return bool(keyring.get_password(SERVICE, GITHUB_TOKEN_KEY))


def set_fpl_password(email: str, value: str) -> None:
    keyring.set_password(SERVICE, email, value)


def set_github_token(value: str) -> None:
    keyring.set_password(SERVICE, GITHUB_TOKEN_KEY, value)
