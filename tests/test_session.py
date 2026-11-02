import json
import os

import pytest

CHROME = "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"
pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="no local Chromium")

TOKEN = "Bearer secret-token-123"
CSRF = "csrf-abc-987"

HOME = f"""<html><body><a href="https://account.premierleague.com/login">Log in</a><script>
const q = new URLSearchParams(location.search);
if (q.get("code")) {{ localStorage.setItem("tok", "{TOKEN}"); localStorage.setItem("csrf", "{CSRF}"); }}
const tok = localStorage.getItem("tok");
if (tok) fetch("/api/me/", {{headers: {{"x-api-authorization": tok}}}});
window.siteSave = () => fetch("/api/my-team/42/", {{method: "POST",
  headers: {{"x-api-authorization": tok, "x-csrftoken": localStorage.getItem("csrf"), "content-type": "application/json"}},
  body: JSON.stringify({{picks: [], chip: null}})}});
</script></body></html>"""

LOGIN = """<html><body>
<form action="https://account.premierleague.com/joinmypl" method="get"><button type="submit">Join MyPL</button></form>
<form onsubmit="event.preventDefault();
  if (document.querySelector('#pw').value === 'right-password') location.href='https://fantasy.premierleague.com/?code=1';">
  <input type="email" id="em"><input type="password" id="pw"><button type="submit">Sign in</button></form>%s</body></html>"""


AUTO_OWNER = """<script>setTimeout(() => {
  document.querySelector('#em').value = 'owner@example.com';
  document.querySelector('#pw').value = 'right-password';
  document.querySelector('#pw').form.requestSubmit(); }, 3000);</script>"""


def routes(captcha=False, owner_signs_in=False):
    def setup(context):
        def handle(route):
            req = route.request
            url = req.url
            h = {k.lower(): v for k, v in req.headers.items()}
            authed = h.get("x-api-authorization") == TOKEN
            if url.startswith("https://fantasy.premierleague.com/api/me/"):
                body = {"player": {"entry": 42} if authed else None}
            elif url.startswith("https://fantasy.premierleague.com/api/my-team/42/"):
                if not authed:
                    return route.fulfill(status=401, body="{}", content_type="application/json")
                if req.method == "POST":
                    ok = h.get("x-csrftoken") == CSRF
                    return route.fulfill(status=200 if ok else 403, content_type="application/json",
                                         body=json.dumps({"saved": ok}))
                body = {"picks": [{"element": 1, "position": 1}], "chips": [],
                        "transfers": {"bank": 11, "limit": 1, "made": 0, "cost": 4, "status": "cost", "value": 989}}
            elif url.startswith("https://fantasy.premierleague.com"):
                owner_click = ('<script>if (!localStorage.getItem("tok") && !location.search) setTimeout(() => '
                               'document.querySelector("a").click(), 1000);</script>') if owner_signs_in else ""
                return route.fulfill(status=200, content_type="text/html", body=HOME + owner_click)
            elif "joinmypl" in url:
                return route.fulfill(status=200, content_type="text/html", body="<html><body>Join MyPL</body></html>")
            elif url.startswith("https://account.premierleague.com/login"):
                frame = '<iframe src="https://challenges.cloudflare.com/x" width="300" height="300"></iframe>' if captcha else ""
                frame += AUTO_OWNER if owner_signs_in else ""
                return route.fulfill(status=200, content_type="text/html", body=LOGIN % frame)
            else:
                return route.fulfill(status=200, content_type="text/html", body="<html></html>")
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        context.route("**/*", handle)
    return setup


@pytest.fixture
def browser_env(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    monkeypatch.setenv("FPLBOT_CHROMIUM", CHROME)
    return tmp_path / "profile"


def test_login_reads_team_and_remembers_session(browser_env):
    from fplbot.fpl_session import FplBrowser
    with FplBrowser(headless=True, profile=browser_env, setup=routes()) as b:
        assert b.login("owner@example.com", "right-password") == 42
        team = b.my_team(42)
        assert team["transfers"]["bank"] == 11
    # Second run: the profile remembers the sign-in, so no form is needed.
    with FplBrowser(headless=True, profile=browser_env, setup=routes()) as b:
        assert b.login("owner@example.com", "wrong-password-unused") == 42


def test_wrong_password_fails_cleanly(browser_env):
    from fplbot.fpl_session import FplBrowser, LoginFailed
    with FplBrowser(headless=True, profile=browser_env, setup=routes()) as b:
        with pytest.raises(LoginFailed):
            b.login("owner@example.com", "wrong")


def test_human_check_stops_the_bot(browser_env):
    from fplbot.fpl_session import FplBrowser, HumanCheck
    with FplBrowser(headless=True, profile=browser_env, setup=routes(captcha=True)) as b:
        with pytest.raises(HumanCheck):
            b.login("owner@example.com", "right-password")


def test_save_needs_token_then_probe_finds_its_source(browser_env):
    from fplbot.fpl_session import FplBrowser, SessionError
    with FplBrowser(headless=True, profile=browser_env, setup=routes()) as b:
        b.login("owner@example.com", "right-password")
        with pytest.raises(SessionError):
            b.post("/api/my-team/42/", {"picks": []})
        b.page.evaluate("siteSave()")      # the owner saving once in the window
        b.page.wait_for_timeout(500)
        probe = b.probe_csrf_source()
        assert probe["save_token_seen"] and "localStorage:csrf" in probe["where"]
        assert CSRF not in json.dumps(probe)  # names only, never values
        assert b.post("/api/my-team/42/", {"picks": []}).data == {"saved": True}


def test_manual_sign_in_records_layout_without_values(browser_env):
    from fplbot.fpl_session import FplBrowser
    with FplBrowser(headless=True, profile=browser_env, setup=routes(owner_signs_in=True)) as b:
        # The fake owner clicks "Log in" and signs in; the bot only watches.
        assert b.login_manually(timeout=30) == 42
        text = json.dumps(b.login_layout)
        assert "right-password" not in text and "owner@example.com" not in text
        page = b.login_layout[0]
        assert {"type": "password"}.items() <= page["inputs"][1].items()
        assert any(btn["text"] == "Join MyPL" for btn in page["buttons"])
