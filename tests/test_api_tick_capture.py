import json
import subprocess
from datetime import datetime, timezone

import pytest

from fplbot import paths, tick
from fplbot.capture import capture
from fplbot.config import Config, generate_topics
from fplbot.fpl_api import FplBlocked, FplPublicClient
from fplbot.store import Store

from .conftest import make_bootstrap

BOOT = make_bootstrap([
    (8, "2026-10-23T17:30:00Z", True, True),
    (9, "2026-10-31T11:00:00Z", False, False),
]) | {"teams": [], "elements": []}


class FakeResponse:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, routes, status=200):
        self.routes, self.status, self.calls, self.headers = routes, status, [], {}

    def get(self, url, timeout=None):
        self.calls.append(url)
        path = url.split("/api/", 1)[1]
        return FakeResponse(self.status, self.routes.get(path, {}))


class FakeNtfy:
    def __init__(self, heartbeats=None, control=None):
        self.sent, self.heartbeats, self.control = [], heartbeats, control or []

    def send(self, topic, message, **kw):
        self.sent.append((topic, message, kw))
        return True

    def poll(self, topic, since="12h"):
        if "heartbeat" in topic:
            if self.heartbeats is None:
                raise OSError("offline")
            return self.heartbeats
        return self.control


def client_with(routes, status=200):
    return FplPublicClient(paths.cache_dir(), session=FakeSession(routes, status), min_interval=0)


def test_client_caches_and_reports_blocking():
    c = client_with({"bootstrap-static/": BOOT})
    assert c.bootstrap() == BOOT
    c.bootstrap()
    assert len(c.session.calls) == 1
    c.bootstrap(max_age=0)
    assert len(c.session.calls) == 2
    with pytest.raises(FplBlocked):
        client_with({}, status=403).fixtures(max_age=0)


def test_capture_writes_snapshot(tmp_path):
    c = client_with({"bootstrap-static/": BOOT, "fixtures/": [{"id": 1}], "event/8/live/": {"elements": []}})
    files = capture(c, tmp_path, now=datetime(2026, 10, 30, tzinfo=timezone.utc))
    names = sorted(f.name for f in files)
    assert names == ["bootstrap-static.json", "event-8-live.json", "fixtures.json"]
    assert json.loads((tmp_path / "samples/2026-10-30/fixtures.json").read_text()) == [{"id": 1}]


def _cfg(role):
    cfg = Config(role=role)
    generate_topics(cfg)
    return cfg


def test_primary_tick_heartbeats_and_runs_due_jobs():
    ntfy = FakeNtfy()
    store = Store(paths.db_path())
    c = client_with({"bootstrap-static/": BOOT, "fixtures/": []})
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    result = tick.run(_cfg("primary"), now=now, ntfy=ntfy, client=c, store=store)
    assert "daily: FPL data refreshed" in result and "plan: not built yet" in result
    assert any("heartbeat" in t for t, _, _ in ntfy.sent)
    st = store.get_state()
    assert st["daily_done_date"] == "2026-10-30" and st["plan_done_event"] == 9 and st["post_gw_done_event"] == 8
    assert tick.run(_cfg("primary"), now=now, ntfy=ntfy, client=c, store=store) == "nothing due"


def test_backup_stands_by_while_primary_alive_or_unreadable():
    c = client_with({"bootstrap-static/": BOOT})
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    for beats in ([{"message": "alive"}], None):
        r = tick.run(_cfg("backup"), now=now, ntfy=FakeNtfy(heartbeats=beats), client=c, store=Store(paths.db_path()))
        assert r.startswith("standby")


def test_backup_takes_over_and_alerts_once_per_hour():
    c = client_with({"bootstrap-static/": BOOT, "fixtures/": []})
    store, ntfy, cfg = Store(paths.db_path()), FakeNtfy(heartbeats=[]), _cfg("backup")
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    tick.run(cfg, now=now, ntfy=ntfy, client=c, store=store)
    tick.run(cfg, now=now.replace(minute=15), ntfy=ntfy, client=c, store=store)
    alerts = [m for t, m, _ in ntfy.sent if t == cfg.topic_alerts]
    assert len(alerts) == 1 and "taking over" in alerts[0]


def test_pause_message_stops_jobs_and_alerts_once():
    c = client_with({"bootstrap-static/": BOOT})
    store, cfg = Store(paths.db_path()), _cfg("primary")
    ntfy = FakeNtfy(control=[{"id": "m1", "message": "pause"}])
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    assert tick.run(cfg, now=now, ntfy=ntfy, client=c, store=store) == "paused"
    assert tick.run(cfg, now=now, ntfy=ntfy, client=c, store=store) == "paused"
    assert len([1 for t, _, _ in ntfy.sent if t == cfg.topic_alerts]) == 1
    ntfy.control.append({"id": "m2", "message": "resume"})
    assert tick.run(cfg, now=now, ntfy=ntfy, client=c, store=store) != "paused"


def test_blocked_by_fpl_alerts_and_makes_no_moves():
    store, cfg, ntfy = Store(paths.db_path()), _cfg("primary"), FakeNtfy()
    r = tick.run(cfg, now=datetime(2026, 10, 30, 12, tzinfo=timezone.utc), ntfy=ntfy,
                 client=client_with({}, status=403), store=store)
    assert r == "error: blocked by FPL"
    assert any("will not work around" in m for _, m, _ in ntfy.sent)


def test_cli_module_runs():
    out = subprocess.run(["python3", "-m", "fplbot", "--help"], capture_output=True, text=True, cwd=paths.REPO_ROOT)
    assert out.returncode == 0 and "capture" in out.stdout
