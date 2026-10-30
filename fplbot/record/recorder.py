"""`fplbot record`: open a browser, let the owner log in and save the team by hand,
and record how the FPL website talks to its servers, cleaned of every secret.

The browser profile is temporary: nothing from the session (cookies, tokens) is
kept on disk. Only the cleaned recording is saved, and it is checked again for
leaks before it is written.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import sanitize

START_URL = "https://fantasy.premierleague.com/"


class LeakError(RuntimeError):
    pass


class Recording:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def add(self, request, response) -> None:
        """Record one request/response pair if it belongs to the FPL site or its login."""
        host = urlsplit(request.url).hostname or ""
        if not sanitize.is_relevant_host(host):
            return
        auth = sanitize.is_auth_host(host)
        is_game_api = host == sanitize.GAME_HOST and "/api/" in request.url
        method = request.method
        # Page loads, scripts and images on the game site tell us nothing.
        if not auth and not is_game_api:
            return
        if getattr(request, "resource_type", "") in ("stylesheet", "image", "font", "script", "media"):
            return
        if is_game_api and method == "GET" and not _interesting_get(request.url):
            return

        req_headers = _all_headers(request)
        entry = {
            "method": method,
            "url": sanitize.url(request.url),
            "request_headers": sanitize.headers(req_headers),
            "request_body": sanitize.body(_post_data(request), req_headers.get("content-type"), auth),
        }
        if response is not None:
            resp_headers = _all_headers(response)
            entry["status"] = response.status
            loc = resp_headers.get("location")
            if loc:
                entry["redirect_to"] = sanitize.url(loc)
            set_cookie = resp_headers.get("set-cookie")
            if set_cookie:
                entry["sets_cookies"] = sorted({line.split("=", 1)[0].strip() for line in set_cookie.split("\n") if "=" in line})
            entry["response"] = _response_summary(response, resp_headers, auth, method)
        self.entries.append(entry)

    def to_json(self) -> str:
        return json.dumps({
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "Cleaned recording of the FPL website's own requests. No passwords, cookies or tokens.",
            "requests": self.entries,
        }, indent=1, ensure_ascii=False)


def _interesting_get(u: str) -> bool:
    """Team-related reads only; public data (bootstrap, fixtures, players) is already known."""
    path = urlsplit(u).path
    return any(k in path for k in ("/api/me", "/api/my-team", "/api/entry", "/api/transfers", "/api/team"))


def _all_headers(obj) -> dict[str, str]:
    try:
        h = obj.all_headers()
    except Exception:
        h = obj.headers
    return {k.lower(): v for k, v in h.items()}


def _post_data(request) -> str | None:
    try:
        return request.post_data
    except Exception:
        return None


def _response_summary(response, headers: dict[str, str], auth: bool, method: str):
    ct = headers.get("content-type", "")
    if auth or "json" not in ct:
        return {"content_type": ct.split(";")[0]} if ct else None
    try:
        data = response.json()
    except Exception:
        return {"content_type": ct.split(";")[0], "body": "<unreadable>"}
    # Reads: layout only. Writes: cleaned values, so errors and confirmations are visible.
    return {"json_shape": sanitize.shape(data)} if method == "GET" else {"json": sanitize.scrub(data)}


def save(rec: Recording, out_dir: Path, secrets: list[str]) -> Path:
    text = rec.to_json()
    problems = sanitize.leak_check(text, secrets)
    if problems:
        raise LeakError("Recording not saved: " + "; ".join(sorted(set(problems))))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"fpl-session-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(text + "\n", encoding="utf-8")
    return out


def run(start_url: str = START_URL, headless: bool = False, setup=None, on_ready=None) -> Recording:
    """Open a browser and record until the owner closes it. `setup(context)` and `on_ready(page)` are for tests."""
    from playwright.sync_api import Error as PwError, sync_playwright

    rec = Recording()
    with sync_playwright() as p:
        exe = os.environ.get("FPLBOT_CHROMIUM") or None
        browser = p.chromium.launch(headless=headless, executable_path=exe)
        context = browser.new_context()  # temporary profile: cookies vanish when the browser closes

        def on_finished(request):
            try:
                rec.add(request, request.response())
            except Exception:
                pass

        def on_failed(request):
            try:
                rec.add(request, None)
            except Exception:
                pass

        if setup:
            setup(context)
        context.on("requestfinished", on_finished)
        context.on("requestfailed", on_failed)
        page = context.new_page()
        page.goto(start_url)
        if on_ready:
            on_ready(page)
            page.wait_for_timeout(1000)  # let the last request events arrive
            context.close()
        while True:
            pages = [pg for pg in context.pages if not pg.is_closed()]
            if not pages:
                break
            try:
                pages[0].wait_for_timeout(500)
            except PwError:
                continue
        try:
            browser.close()
        except PwError:
            pass
    return rec
