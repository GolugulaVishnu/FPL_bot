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
SIGNUP_URL_HINTS = ("joinmypl", "/join", "register", "signup", "sign-up", "create-account")
SIGNIN_HOST_HINT = "account.premierleague.com"
WORKER_PATH = "/api/me/"   # small JSON address with no page scripts
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


def _short(e: Exception | None) -> str:
    """First line of a browser error, with any registered secret removed."""
    from .logs import scrub
    return scrub(str(e).strip().splitlines()[0][:200]) if e else "unknown error"


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
        self._worker = None   # quiet tab the bot sends its requests from
        self.login_layout: list[dict] = []   # sign-in page layouts seen (no values), for diagnosis

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
        try:
            raw = request.all_headers()   # .headers can leave some headers out
        except Exception:
            raw = request.headers
        h = {k.lower(): v for k, v in raw.items()}
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
            self.snapshot_login_page()
            if self._on_signup_page():
                raise LoginFailed("sign-in went to the account sign-up page (Join MyPL) instead of signing in; "
                                  "run 'fplbot login --manual' and sign in yourself once")
            if API_HOST in self.page.url and "/api/" not in self.page.url and self._wait_for_token(2):
                break
            if self.human_check_visible():
                self._handle_human_check(wait_for_human)
                continue
            em = self._first_visible(EMAIL_FIELDS)
            pw = self._first_visible(PASSWORD_FIELDS)
            if em is not None and not em.input_value():
                em.fill(email)
            if pw is not None and not pw.input_value():
                pw.fill(password)
            # Press Enter in the field so the form that holds it is the one submitted.
            # Clicking buttons by label risks a "Join" or "Register" button.
            field = pw or em
            if field is not None:
                field.press("Enter")
        entry = self._entry_if_logged_in(wait=20)
        if not entry:
            if self.human_check_visible():
                self._handle_human_check(wait_for_human)
                entry = self._entry_if_logged_in(wait=20)
            if not entry:
                raise LoginFailed("the FPL site did not confirm the sign-in; check the password with "
                                  "'fplbot setup --reset', or run 'fplbot login --manual'")
        return entry

    def login_manually(self, timeout: float = 600) -> int:
        """Open the site and let the owner sign in by hand; the bot only watches and records the page layout."""
        self.page.goto(self.site + "/", wait_until="domcontentloaded")
        # One loop both records sign-in pages and notices when the site has signed in
        # (straight away if the profile still remembers the session).
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.page.wait_for_timeout(500)
            for pg in list(self._ctx.pages):
                if not pg.is_closed() and SIGNIN_HOST_HINT in pg.url:
                    self.snapshot_login_page(pg)
            if self._auth:
                try:
                    entry = self._entry_if_logged_in(wait=5)
                except SessionError as e:
                    log.info("sign-in check not ready yet: %s", e)
                    entry = None
                if entry:
                    return entry
        raise LoginFailed("no sign-in seen in the window within 10 minutes")

    def _on_signup_page(self) -> bool:
        u = self.page.url.lower()
        return any(k in u for k in SIGNUP_URL_HINTS)

    def snapshot_login_page(self, page=None) -> None:
        """Record the visible form layout of a sign-in page: field types and button labels, never values."""
        page = page or self.page
        if API_HOST in page.url:
            return
        try:
            snap = page.evaluate(
                """() => {
                     const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                     const txt = el => (el.innerText || el.value || el.getAttribute("aria-label") || "").trim().slice(0, 40);
                     return {
                       page: location.host + location.pathname,
                       title: document.title.slice(0, 80),
                       inputs: [...document.querySelectorAll("input")].filter(vis).map(i => ({
                         type: i.type, name: i.name, id: i.id, autocomplete: i.autocomplete,
                         placeholder: (i.placeholder || "").slice(0, 40), in_form: !!i.form})),
                       buttons: [...document.querySelectorAll("button, input[type=submit], [role=button]")].filter(vis)
                         .map(b => ({tag: b.tagName.toLowerCase(), type: b.type || "", id: b.id, text: txt(b),
                                     in_form_with_password: !!(b.form && b.form.querySelector("input[type=password]"))})),
                       links: [...document.querySelectorAll("a")].filter(vis).map(txt)
                         .filter(t => /join|sign|log|register|forgot|continue/i.test(t)).slice(0, 15),
                     };
                   }""")
        except Exception:
            return
        if not self.login_layout or self.login_layout[-1] != snap:
            self.login_layout.append(snap)

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
        from playwright.sync_api import Error as PwError
        script = """async ([url, method, headers, body]) => {
                 const r = await fetch(url, {method, headers, credentials: "include",
                                             body: body === null ? undefined : JSON.stringify(body)});
                 let data = null;
                 try { data = await r.json(); } catch (e) {}
                 return {status: r.status, data};
               }"""
        # The site redirects after sign-in; a request started mid-navigation is lost, so wait and retry.
        # Retrying a save is safe: each save sends the whole lineup, so sending it twice changes nothing.
        last = None
        for attempt in range(5):
            try:
                page = self._worker_page()
                page.wait_for_load_state("load", timeout=15000)
                result = page.evaluate(script, [self.site + path, method, headers, body])
                return ApiResponse(result["status"], result["data"])
            except PwError as e:
                if "closed" in str(e).lower():
                    raise SessionError("the browser window was closed") from e
                # A hiccup in the bot's own tab; reopen it and retry.
                last = e
                self._worker = None
                log.info("request to %s interrupted (attempt %d): %s", path, attempt + 1, _short(e))
                try:
                    self.page.wait_for_timeout(1500 * (attempt + 1))
                except PwError as e2:
                    raise SessionError("the browser window was closed") from e2
        raise SessionError(f"request to {path} failed in the browser: {_short(last)}") from last

    def _worker_page(self):
        """The bot's own tab, parked on a small FPL API address.

        It has no scripts, so it never redirects, and it is on the FPL site, so
        requests from it carry the site's cookies. The main tab is left alone to
        sign in and refresh its login without the bot interrupting it.
        """
        if self._worker is None or self._worker.is_closed():
            self._worker = self._ctx.new_page()
            self._worker.goto(self.site + WORKER_PATH, wait_until="domcontentloaded")
        return self._worker

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
