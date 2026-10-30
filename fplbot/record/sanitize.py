"""Strip secrets from recorded web requests before anything is written to disk.

What is kept: request methods, hosts, paths, query and body key names, and for
the FPL game API the non-secret values (player ids, positions, captain flags,
chip names) needed to learn how a team is saved.

What is removed: passwords, cookies, login tokens, authorisation headers, OAuth
codes and states, email addresses, and any long random-looking string. On login
hosts every value is removed and only key names remain.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlsplit

REDACTED = "[REDACTED]"
GAME_HOST = "fantasy.premierleague.com"

SENSITIVE_KEY = re.compile(
    r"pass|pwd|token|secret|code|auth|cookie|session|csrf|email|e-mail|otp|state|verifier|nonce|"
    r"challenge|assertion|credential|signature|key|username|login|phone|birth|dob|address|(?:^|[_-])ip(?:$|[_-])",
    re.IGNORECASE)
# Keys that look sensitive by the pattern above but are plain game data.
SAFE_KEYS = {"element", "element_type", "team_code", "code", "position", "is_captain", "is_vice_captain",
             "multiplier", "chip", "event", "entry", "name", "short_name", "favourite_team", "player_first_name",
             "player_last_name", "id", "freehit", "wildcard", "bboost", "3xc"}
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}")
LONG_RANDOM = re.compile(r"^[A-Za-z0-9+/=_.-]{32,}$")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def is_auth_host(host: str) -> bool:
    """Anything to do with logging in: the PL account site and the identity provider."""
    h = host.lower()
    return h != GAME_HOST and ("account" in h or "auth" in h or "login" in h or "ping" in h or "identity" in h
                               or "sso" in h or "oauth" in h)


def is_relevant_host(host: str) -> bool:
    h = host.lower()
    return h == GAME_HOST or "premierleague" in h or is_auth_host(h)


def _sensitive_key(key: str) -> bool:
    return key not in SAFE_KEYS and bool(SENSITIVE_KEY.search(key))


def scrub_string(s: str) -> str:
    if JWT.search(s) or LONG_RANDOM.match(s) or EMAIL.search(s):
        return REDACTED
    return s


def scrub(obj, all_values: bool = False, key: str | None = None):
    """Recursively scrub a JSON value. `all_values` replaces every scalar with its type name."""
    if key is not None and _sensitive_key(key):
        return REDACTED
    if isinstance(obj, dict):
        return {k: scrub(v, all_values, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, all_values) for v in obj]
    if all_values:
        return f"<{type(obj).__name__}>"
    if isinstance(obj, str):
        return scrub_string(obj)
    return obj


def shape(obj, depth: int = 0):
    """Types only, lists cut to their first item: shows a response's layout without its data."""
    if depth > 6:
        return "..."
    if isinstance(obj, dict):
        return {k: (REDACTED if _sensitive_key(k) else shape(v, depth + 1)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [shape(obj[0], depth + 1), f"... {len(obj)} items"] if obj else []
    return f"<{type(obj).__name__}>"


def _scrub_path(path: str) -> str:
    return "/".join(REDACTED if (LONG_RANDOM.match(seg) or JWT.search(seg)) else seg for seg in path.split("/"))


def url(u: str) -> dict:
    parts = urlsplit(u)
    auth = is_auth_host(parts.hostname or "")
    query = {}
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        query[k] = REDACTED if (auth or _sensitive_key(k)) else scrub_string(v)
    return {"host": parts.hostname, "path": _scrub_path(parts.path), "query": query}


SAFE_HEADER_VALUES = {"content-type", "accept", "x-requested-with", "origin"}


def headers(h: dict[str, str]) -> dict[str, str]:
    """Header names, with values only for harmless headers. Shows how auth is sent without the secret."""
    out = {}
    for name, value in h.items():
        n = name.lower()
        if n in SAFE_HEADER_VALUES:
            out[n] = value
        elif n == "authorization":
            out[n] = (value.split(" ", 1)[0] + " " + REDACTED) if " " in value else REDACTED
        elif n == "cookie":
            out[n] = "names: " + ", ".join(sorted(c.split("=", 1)[0].strip() for c in value.split(";") if c.strip()))
        elif n.startswith(":") or n in ("user-agent", "accept-language", "accept-encoding", "referer",
                                        "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"):
            continue
        else:
            out[n] = REDACTED
    return out


def body(raw: str | None, content_type: str | None, auth_host: bool):
    if not raw:
        return None
    ct = (content_type or "").lower()
    if "json" in ct or raw.lstrip().startswith(("{", "[")):
        try:
            return {"json": scrub(json.loads(raw), all_values=auth_host)}
        except ValueError:
            pass
    if "x-www-form-urlencoded" in ct or ("=" in raw and " " not in raw):
        return {"form": {k: (REDACTED if (auth_host or _sensitive_key(k)) else scrub_string(v))
                         for k, v in parse_qsl(raw, keep_blank_values=True)}}
    return {"text": f"<{len(raw)} characters, not recorded>"}


def leak_check(text: str, secrets: list[str]) -> list[str]:
    """Return reasons the cleaned output is unsafe to save (empty means safe)."""
    problems = []
    for s in secrets:
        if s and len(s) >= 4 and s in text:
            problems.append("contains a saved secret (password or token)")
    if JWT.search(text):
        problems.append("contains something that looks like a login token")
    if EMAIL.search(text):
        problems.append("contains an email address")
    return problems
