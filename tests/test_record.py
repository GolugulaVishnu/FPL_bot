import json
import os

import pytest

from fplbot.record import recorder, sanitize

CHROME = "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"
PASSWORD = "hunter2-Secret!"
EMAIL = "owner@example.com"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlLWZvci10ZXN0"


def test_scrub_keeps_game_data_and_removes_secrets():
    data = {"picks": [{"element": 5, "position": 1, "is_captain": True, "multiplier": 2}], "chip": "bboost",
            "chips": [{"name": "bboost"}], "access_token": TOKEN, "email": EMAIL, "note": TOKEN}
    out = sanitize.scrub(data)
    assert out["picks"][0] == {"element": 5, "position": 1, "is_captain": True, "multiplier": 2}
    assert out["chip"] == "bboost" and out["chips"] == [{"name": "bboost"}]
    assert out["access_token"] == out["email"] == out["note"] == sanitize.REDACTED


def test_auth_hosts_keep_key_names_only():
    b = sanitize.body(f"username={EMAIL}&password={PASSWORD}&grant_type=password", "application/x-www-form-urlencoded", True)
    assert b == {"form": {"username": "[REDACTED]", "password": "[REDACTED]", "grant_type": "[REDACTED]"}}
    u = sanitize.url("https://account.premierleague.com/as/authorize?client_id=abc&code=xyz&state=s1")
    assert set(u["query"].values()) == {"[REDACTED]"}
    h = sanitize.headers({"Authorization": f"Bearer {TOKEN}", "Cookie": "pl_session=abc; csrftoken=def",
                          "Content-Type": "application/json", "X-CSRFToken": "zzz"})
    assert h == {"authorization": "Bearer [REDACTED]", "cookie": "names: csrftoken, pl_session",
                 "content-type": "application/json", "x-csrftoken": "[REDACTED]"}


def test_leak_check():
    assert sanitize.leak_check('{"a": 1}', [PASSWORD]) == []
    assert sanitize.leak_check(f'{{"a": "{PASSWORD}"}}', [PASSWORD])
    assert sanitize.leak_check(f'"{TOKEN}"', [])
    assert sanitize.leak_check(f'"{EMAIL}"', [])


PAGE = f"""<html><body>FPL test<script>
async function go() {{
  await fetch("https://account.premierleague.com/as/token", {{method: "POST",
    headers: {{"Content-Type": "application/x-www-form-urlencoded"}},
    body: "username={EMAIL}&password={PASSWORD}&code=abc123"}});
  await fetch("/api/me/", {{headers: {{"Authorization": "Bearer {TOKEN}"}}}});
  await fetch("/api/my-team/123/", {{method: "POST",
    headers: {{"Content-Type": "application/json", "Authorization": "Bearer {TOKEN}"}},
    body: JSON.stringify({{picks: [{{element: 5, position: 1, is_captain: true, is_vice_captain: false}}], chip: "bboost"}})}});
  await fetch("/static/app.js");
  document.title = "done";
}}
go();
</script></body></html>"""


def _setup(context):
    def handle(route):
        url = route.request.url
        cors = {"access-control-allow-origin": "https://fantasy.premierleague.com",
                "access-control-allow-headers": "*", "access-control-allow-methods": "*"}
        if url.rstrip("/") == "https://fantasy.premierleague.com":
            route.fulfill(status=200, content_type="text/html", body=PAGE)
        elif "/api/me/" in url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"player": {"email": EMAIL, "entry": 123, "first_name": "A"}}))
        elif "/api/my-team/" in url:
            route.fulfill(status=200, content_type="application/json", body=route.request.post_data or "{}")
        elif "account.premierleague.com" in url:
            route.fulfill(status=200, content_type="application/json", headers=cors,
                          body=json.dumps({"access_token": TOKEN, "expires_in": 300}))
        else:
            route.fulfill(status=200, content_type="text/javascript", body="")
    context.route("**/*", handle)


@pytest.mark.skipif(not os.path.exists(CHROME), reason="no local Chromium")
def test_recorder_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    monkeypatch.setenv("FPLBOT_CHROMIUM", CHROME)
    rec = recorder.run(headless=True, setup=_setup,
                       on_ready=lambda page: page.wait_for_function("document.title === 'done'", timeout=10000))
    out = recorder.save(rec, tmp_path, [PASSWORD, TOKEN])
    text = out.read_text()
    for secret in (PASSWORD, TOKEN, EMAIL, "abc123"):
        assert secret not in text
    data = json.loads(text)["requests"]
    paths = [(r["method"], r["url"]["path"]) for r in data]
    assert ("POST", "/as/token") in paths and ("GET", "/api/me/") in paths and ("POST", "/api/my-team/123/") in paths
    assert not any("/static/" in p for _, p in paths)
    save = next(r for r in data if r["url"]["path"] == "/api/my-team/123/")
    assert save["request_body"]["json"]["picks"][0]["element"] == 5
    assert save["request_body"]["json"]["chip"] == "bboost"
    assert save["request_headers"]["authorization"] == "Bearer [REDACTED]"
    me = next(r for r in data if r["url"]["path"] == "/api/me/")
    assert me["response"]["json_shape"]["player"]["entry"] == "<int>"


def test_save_refuses_leaky_recording(tmp_path):
    rec = recorder.Recording()
    rec.entries.append({"oops": PASSWORD})
    with pytest.raises(recorder.LeakError):
        recorder.save(rec, tmp_path, [PASSWORD])
    assert not list(tmp_path.iterdir())
