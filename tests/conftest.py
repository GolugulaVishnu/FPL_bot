import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point the data folder at a temp dir so tests never touch real config or keychain data."""
    monkeypatch.setenv("FPLBOT_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def make_bootstrap(events):
    """events: list of (id, iso_deadline, finished, data_checked)."""
    return {"events": [
        {"id": i, "deadline_time": d, "finished": f, "data_checked": c} for i, d, f, c in events
    ]}
