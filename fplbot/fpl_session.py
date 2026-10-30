"""Logged-in access to the owner's FPL team, through a real browser on the owner's machine.

The FPL site sits behind Cloudflare and DataDome bot checks, and its game API
needs a login token that the site's own JavaScript creates after sign-in (sent
as `x-api-authorization`). So the bot does not call the API from Python: it
opens the site in a browser, signs in like a person, and makes its requests
from inside the page with the token the site itself uses. The token is held in
memory only and never logged.

The browser profile lives in the local data folder (never the repo) so the
sign-in is remembered between runs and the bot logs in rarely. If FPL shows a
CAPTCHA or other human check, the bot stops and asks the owner; it never tries
to get around it.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .logs import register_secret

log = logging.getLogger("fplbot.session")

SITE = "https://fantasy.premierleague.com"
API_HOST = "fantasy.premierleague.com"
HUMAN_CHECK_HOSTS = ("captcha-delivery.com", "challenges.cloudflare.com", "hcaptcha.com", "recaptcha")
LOGIN_LINKS = ['a:has-text("Log in")', 'button:has-text("Log in")', 'a:has-text("Sign in")', 'button:has-text("Sign in")']
EMAIL_FIELDS = ['input[type="email"]', 'input[autocomplete="username"]', 'input[name*="email" i]',
                'input[id*="email" i]', 'input[name*="user" i]']
PASSWORD_FIELDS = ['input[type="password"]']
SUBMIT_BUTTONS = ['button[type="submit"]', 'input[type="submit"]', 'button:has-text("Sign in")',
                  'button:has-text("Log in")', 'button:has-text("Continue")', 'button:has-text("Next")']
COOKIE_ACCEPT = ['#onetrust-accept-btn-handler', 'button:has-text("Accept All Cookies")', 'button:has-text("Accept all")']


class SessionError(RuntimeError):
    pass


class HumanCheck(SessionError):
    """FPL wants a person (CAPTCHA, bot check). The bot must stop, not work around it."""


class LoginFailed(SessionError):
    pass


@dataclass
class ApiResponse:
    status: int
    data: object


def profile_dir() -> Path:
    d = paths.data_dir() / "browser-profile"
    d.mkdir(parents=True, exist_ok=True)
    return d


class FplBrowser:
    def __init__(self, headless: bool = False, site: str = SITE, profile: Path | None = None, setup=None):
        self.headless = headless
        self.site = site.rstrip("/")
        self.profile = profile or profile_dir()
        self._setup = setup            # tests: install fake routes on the context
        self._auth: str | None = None   # x-api-authorization value, memory only
        self._csrf: str | None = None   # x-csrftoken value, memory only
        self._pw = self._ctx = self.page = None

    # --- lifecycle -------------------------------------------------------
    def __enter__(self) -> "FplBrowser":
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        exe = os.environ.get("FPLBOT_CHROMIUM") or None
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(self.profile), headless=self.headless, executable_path=exe, viewport={"width": 1280, "height": 900})
        if self._setup:
            self._setup(self._ctx)
        self._ctx.on("request", self._capture_headers)
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def __exit__(self, *exc) -> None:
        try:
            self._ctx.close()
        finally:
            self._pw.stop()
            self._auth = self._csrf = None

    def _capture_headers(self, request) -> None:
        if API_HOST not in request.url or "/api/" not in request.url:
            return
        h = {k.lower(): v for k, v in request.headers.items()}
        if h.get("x-api-authorization"):
            self._auth = h["x-api-authorization"]
            register_secret(self._auth)
        if h.get("x-csrftoken"):
            self._csrf = h["x-csrftoken"]
            register_secret(self._csrf)

    # --- checks ----------------------------------------------------------
    def human_check_visible(self) -> bool:
        for frame in self.page.frames:
            if any(h in (frame.url or "") for h in HUMAN_CHECK_HOSTS):
                try:
                    el = frame.frame_element()
                    if el.is_visible() and (el.bounding_box() or {}).get("height", 0) > 30:
                        return True
                except Exception:
                    return True
        return False

    def _first_visible(self, selectors: list[str]):
        for sel in selectors:
            loc = self.page.locator(sel)
            try:
                for i in range(min(loc.count(), 5)):
                    item = loc.nth(i)
                    if item.is_visible():
                        return item
            except Exception:
                continue
        return None

    def _accept_cookies(self) -> None:
        btn = self._first_visible(COOKIE_ACCEPT)
        if btn:
            try:
                btn.click(timeout=3000)
            except Exception:
                pass

    def _wait_for_token(self, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._auth:
                return True
            self.page.wait_for_timeout(500)
        return bool(self._auth)

    # --- login -----------------------------------------------------------
    def login(self, email: str, password: str, wait_for_human: float = 0) -> int:
        """Sign in if needed and return the team (entry) id.

        `wait_for_human`: seconds to wait for the owner to clear a human check in the
        open window (interactive runs). 0 means stop straight away (scheduled runs).
        """
        register_secret(password)
        self.page.goto(self.site + "/", wait_until="domcontentloaded")
        self._accept_cookies()
        entry = self._entry_if_logged_in(wait=8)
        if entry:
            return entry

        link = self._first_visible(LOGIN_LINKS)
        if link is None:
            raise LoginFailed("could not find the 'Log in' link on the FPL site")
        link.click()
        for _step in range(8):
            self.page.wait_for_timeout(2500)
            if API_HOST in self.page.url and "/api/" not in self.page.url and self._wait_for_token(2):
                break
            if self.human_check_visible():
                self._handle_human_check(wait_for_human)
                continue
            filled = False
            em = self._first_visible(EMAIL_FIELDS)
            if em is not None and not em.input_value():
                em.fill(email)
                filled = True
            pw = self._first_visible(PASSWORD_FIELDS)
            if pw is not None and not pw.input_value():
                pw.fill(password)
                filled = True
            btn = self._first_visible(SUBMIT_BUTTONS)
            if btn is not None and (filled or em is not None or pw is not None):
                btn.click()
        entry = self._entry_if_logged_in(wait=20)
        if not entry:
            if self.human_check_visible():
                self._handle_human_check(wait_for_human)
                entry = self._entry_if_logged_in(wait=20)
            if not entry:
                raise LoginFailed("signed in, but the FPL site did not confirm the team; check the password with: fplbot setup --reset")
        return entry

    def _handle_human_check(self, wait_for_human: float) -> None:
        if wait_for_human <= 0:
            raise HumanCheck("FPL is asking for a human check (CAPTCHA). Run 'fplbot login' at the machine and solve it.")
        log.info("human check shown; waiting up to %.0fs for the owner", wait_for_human)
        end = time.monotonic() + wait_for_human
        while time.monotonic() < end and self.human_check_visible():
            self.page.wait_for_timeout(1000)
        if self.human_check_visible():
            raise HumanCheck("The human check was not completed in time.")

    def _entry_if_logged_in(self, wait: float) -> int | None:
        if not self._wait_for_token(wait):
            return None
        me = self.get("/api/me/")
        player = (me.data or {}).get("player") if isinstance(me.data, dict) else None
        return (player or {}).get("entry") if me.status == 200 else None

    # --- API calls from inside the page ---------------------------------
    def _fetch(self, method: str, path: str, body=None) -> ApiResponse:
        if not self._auth:
            raise SessionError("not signed in")
        headers = {"x-api-authorization": self._auth, "accept": "application/json"}
        if method != "GET":
            if not self._csrf:
                raise SessionError("the site's save token (x-csrftoken) is not known yet; run: fplbot login --probe")
            headers["x-csrftoken"] = self._csrf
            headers["content-type"] = "application/json"
        result = self.page.evaluate(
            """async ([url, method, headers, body]) => {
                 const r = await fetch(url, {method, headers, credentials: "include",
                                             body: body === null ? undefined : JSON.stringify(body)});
                 let data = null;
                 try { data = await r.json(); } catch (e) {}
                 return {status: r.status, data};
               }""",
            [self.site + path, method, headers, body])
        return ApiResponse(result["status"], result["data"])

    def get(self, path: str) -> ApiResponse:
        return self._fetch("GET", path)

    def post(self, path: str, body) -> ApiResponse:
        return self._fetch("POST", path, body)

    def my_team(self, entry: int) -> dict:
        r = self.get(f"/api/my-team/{entry}/")
        if r.status != 200 or not isinstance(r.data, dict):
            raise SessionError(f"could not read the team (HTTP {r.status})")
        return r.data

    # --- finding where the save token comes from ---------------------------
    def probe_csrf_source(self) -> dict:
        """Names (never values) of browser storage, cookies and meta tags, and which one holds the save token."""
        found = self.page.evaluate(
            """(token) => {
                 const where = [];
                 const names = {localStorage: [], sessionStorage: [], cookies: [], meta: []};
                 for (const [label, store] of [["localStorage", localStorage], ["sessionStorage", sessionStorage]]) {
                   for (let i = 0; i < store.length; i++) {
                     const k = store.key(i); names[label].push(k);
                     const v = store.getItem(k) || "";
                     if (token && v === token) where.push(label + ":" + k);
                     else if (token && v.includes(token)) where.push(label + ":" + k + " (inside a JSON value)");
                   }
                 }
                 for (const c of document.cookie.split(";")) {
                   const [k, ...rest] = c.trim().split("="); if (!k) continue; names.cookies.push(k);
                   if (token && decodeURIComponent(rest.join("=")) === token) where.push("cookie:" + k);
                 }
                 for (const m of document.querySelectorAll("meta[name]")) {
                   names.meta.push(m.getAttribute("name"));
                   if (token && m.getAttribute("content") === token) where.push("meta:" + m.getAttribute("name"));
                 }
                 return {names, where};
               }""", self._csrf)
        found["save_token_seen"] = bool(self._csrf)
        return found
