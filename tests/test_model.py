import math
from datetime import date, datetime, timezone

import pytest

from fplbot.datastore import DataStore, Fixture, PlayerMatch
from fplbot.model import availability, backtest, ratings
from fplbot.model.players import Profile, build_profile, position_priors
from fplbot.model.project import project_upcoming
from fplbot.model.xp import build_state, poisson_floor_mean, project_fixture
from fplbot.scoring import normalise
from fplbot.sources import current, history

PTS = normalise(None)
UTC = timezone.utc


def pm(season="2025-26", gw=1, fixture=1, code=100, team=1, opponent=2, home=True, position="MID",
       minutes=90, xg=0.3, xa=0.1, points=3, **kw):
    base = dict(season=season, gw=gw, fixture=fixture, code=code, element=code, name=f"p{code}", team=team,
                opponent=opponent, home=home, position=position, n_fixtures=1, minutes=minutes, starts=1,
                goals=0, assists=0, xg=xg, xa=xa, xgc=1.0, clean_sheets=0, goals_conceded=1, saves=0,
                pens_saved=0, pens_missed=0, yellow=0, red=0, own_goals=0, bonus=0, bps=10, dc=None,
                points=points, value=50, fpl_xp=None)
    base.update(kw)
    return PlayerMatch(**base)


def test_poisson_floor_mean_matches_brute_force():
    lam, k = 3.7, 3
    brute = sum(math.exp(-lam) * lam ** n / math.factorial(n) * (n // k) for n in range(60))
    assert poisson_floor_mean(lam, k) == pytest.approx(brute, rel=1e-9)
    assert poisson_floor_mean(0, 2) == 0


def test_return_date_parsing():
    today = date(2026, 10, 30)
    assert availability.return_date("Hamstring injury - Expected back 08 Nov", today) == date(2026, 11, 8)
    assert availability.return_date("Suspended until 03 Jan", today) == date(2027, 1, 3)
    assert availability.return_date("Knock - 75% chance of playing", today) is None


def test_availability_factor():
    now = datetime(2026, 10, 30, tzinfo=UTC)
    gw = datetime(2026, 10, 31, 11, tzinfo=UTC)
    later = datetime(2026, 11, 21, 11, tzinfo=UTC)
    assert availability.factor("a", None, "", gw, 0, now) == (1.0, None)
    assert availability.factor("u", None, "Joined X", later, 3, now)[0] == 0
    assert availability.factor("d", 75, "Knock - 75% chance of playing", gw, 0, now)[0] == 0.75
    out = "Hamstring - Expected back 08 Nov"
    assert availability.factor("i", 0, out, gw, 0, now)[0] == 0
    assert availability.factor("i", 0, out, later, 2, now)[0] == 1
    assert availability.factor("i", 0, "Knee injury - Unknown return date", gw, 0, now)[0] == 0
    assert availability.factor("s", 0, "Suspended", later, 1, now)[0] == 1


def test_ratings_rank_stronger_attack_higher():
    ms = []
    for i in range(10):
        ms += [ratings.TeamMatch(1, 2, True, 2.2, i), ratings.TeamMatch(2, 1, False, 0.6, i),
               ratings.TeamMatch(3, 4, True, 1.3, i), ratings.TeamMatch(4, 3, False, 1.2, i)]
    rt = ratings.fit(ms, known_teams={1, 2, 3, 4, 5})
    assert rt.attack[1] > rt.attack[3] > rt.attack[2]
    assert rt.expected_xg(1, 2, True) > rt.expected_xg(2, 1, False)
    assert rt.attack[5] < 1 and rt.defence[5] > 1  # unseen (promoted) team starts weaker


def test_profile_shrinks_thin_history():
    rows = [pm(gw=g, code=1, minutes=90) for g in range(1, 16)]
    priors = position_priors(rows)
    regular = build_profile(1, "MID", rows, "2025-26", priors)
    newcomer = build_profile(2, "MID", [pm(code=2, minutes=90)], "2025-26", priors)
    benchwarmer = build_profile(3, "MID", [pm(gw=g, code=3, minutes=0) for g in range(1, 16)], "2025-26", priors)
    assert regular.p60 > 0.9
    assert 0.3 < newcomer.p_play < 1.0
    assert benchwarmer.p_play < 0.1


def test_project_fixture_by_position():
    rt = ratings.Ratings(1.4, 1.1, {1: 1.0, 2: 1.0}, {1: 1.0, 2: 1.0})
    gk = Profile(code=1, position="GKP", p_play=1, p60=1, mins_if_play=90, mins_if_60=90,
                 rates={"saves": 3.0, "xg": 0, "xa": 0, "bonus": 0.3, "yellow": 0.05})
    fwd = Profile(code=2, position="FWD", p_play=1, p60=1, mins_if_play=90, mins_if_60=90,
                  rates={"xg": 0.6, "xa": 0.1, "bonus": 0.6, "yellow": 0.1}, dc_hit=0.1)
    g = project_fixture(gk, 1, 2, True, rt, PTS)
    f = project_fixture(fwd, 1, 2, True, rt, PTS)
    assert g.parts["saves"] > 0 and g.parts["clean_sheet"] > 0 and g.parts["goals_conceded"] < 0
    assert f.parts["clean_sheet"] == 0 and f.parts["goals"] > 1.5
    assert project_fixture(fwd, 1, 2, True, rt, PTS, avail=0).xp == 0


def _write(path, header, rows):
    path.write_text(",".join(header) + "\n" + "\n".join(",".join(map(str, r)) for r in rows) + "\n")


def test_history_parse(tmp_path):
    _write(tmp_path / "teams.csv", ["id", "name", "short_name", "code"], [[1, "Arsenal", "ARS", 3], [2, "Spurs", "TOT", 6]])
    _write(tmp_path / "players_raw.csv", ["id", "code"], [[10, 9999]])
    _write(tmp_path / "fixtures.csv", ["id", "event", "team_h", "team_a", "kickoff_time", "finished", "team_h_score", "team_a_score"],
           [[1, 1, 1, 2, "2025-08-16T14:00:00Z", "True", 2, 0]])
    cols = ["name", "position", "team", "xP", "assists", "bonus", "bps", "clean_sheets", "element", "expected_assists",
            "expected_goals", "expected_goals_conceded", "fixture", "goals_conceded", "goals_scored", "minutes",
            "opponent_team", "own_goals", "penalties_missed", "penalties_saved", "red_cards", "saves", "starts",
            "total_points", "value", "was_home", "yellow_cards", "defensive_contribution", "GW"]
    _write(tmp_path / "gws_merged_gw.csv", cols,
           [["Saka", "MID", "Arsenal", 5.1, 1, 3, 40, 1, 10, 0.4, 0.5, 0.2, 1, 0, 1, 90, 2, 0, 0, 0, 0, 0, 1, 12, 100, "True", 0, 13, 1],
            ["Boss", "AM", "Arsenal", 0, 0, 0, 0, 0, 11, 0, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, "True", 0, "", 1]])
    m, f, t = history.parse("2025-26", tmp_path)
    assert len(m) == 1 and m[0].code == 9999 and m[0].team == 1 and m[0].dc == 13 and m[0].fpl_xp == 5.1
    assert t[1] == ("Arsenal", "ARS", 3) and f[0].score_h == 2


def _bootstrap():
    return {
        "events": [{"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": True, "data_checked": True},
                   {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False, "data_checked": False}],
        "teams": [{"id": 1, "name": "A", "short_name": "AAA", "code": 11}, {"id": 2, "name": "B", "short_name": "BBB", "code": 22},
                  {"id": 3, "name": "C", "short_name": "CCC", "code": 33}],
        "elements": [{"id": 5, "code": 555, "web_name": "Striker", "team": 1, "element_type": 4, "now_cost": 80,
                      "status": "a", "chance_of_playing_next_round": None, "news": ""},
                     {"id": 6, "code": 666, "web_name": "Keeper", "team": 2, "element_type": 1, "now_cost": 45,
                      "status": "i", "chance_of_playing_next_round": 0, "news": "Expected back 01 Jan"}],
    }


def test_current_parse_splits_double_gameweek():
    fixtures = [{"id": 1, "event": 1, "team_h": 1, "team_a": 2, "kickoff_time": "x", "finished": True, "team_h_score": 1, "team_a_score": 0},
                {"id": 2, "event": 1, "team_h": 3, "team_a": 1, "kickoff_time": "y", "finished": True, "team_h_score": 0, "team_a_score": 0}]
    live = {"elements": [{"id": 5, "stats": {"minutes": 150, "goals_scored": 1, "expected_goals": "0.9", "total_points": 9,
                                              "starts": 2, "bps": 30},
                          "explain": [{"fixture": 1, "stats": [{"identifier": "minutes", "value": 90}, {"identifier": "goals_scored", "value": 1}]},
                                      {"fixture": 2, "stats": [{"identifier": "minutes", "value": 60}]}]}]}
    season, m, f, t = current.parse(_bootstrap(), fixtures, {1: live})
    assert season == "2026-27" and len(m) == 2
    a, b = sorted(m, key=lambda r: r.fixture)
    assert (a.minutes, a.goals, a.home, a.opponent) == (90, 1, True, 2)
    assert (b.minutes, b.goals, b.home, b.opponent) == (60, 0, False, 3)
    assert a.xg == pytest.approx(0.54) and b.xg == pytest.approx(0.36)


def _store_with_season(tmp_path):
    ds = DataStore(tmp_path / "t.sqlite3")
    rows, fixtures = [], []
    for gw in range(1, 9):
        fx = gw
        fixtures.append(Fixture("2025-26", fx, gw, 1, 2, None, True, 1, 0))
        rows += [pm(gw=gw, fixture=fx, code=1, team=1, opponent=2, home=True, position="FWD", xg=0.7, points=6 + gw % 3),
                 pm(gw=gw, fixture=fx, code=2, team=2, opponent=1, home=False, position="DEF", xg=0.05, points=1 + gw % 2),
                 pm(gw=gw, fixture=fx, code=3, team=2, opponent=1, home=False, position="GKP", xg=0.0, saves=4,
                    points=2, fpl_xp=2.5)]
    ds.replace_season("2025-26", rows, fixtures, {1: ("A", "AAA", 11), 2: ("B", "BBB", 22)})
    return ds


def test_backtest_runs_and_reports(tmp_path):
    ds = _store_with_season(tmp_path)
    res = backtest.run(ds, "2025-26", None, 2, 8)
    assert res.gws == list(range(2, 9)) and res.model.n == 21
    assert res.captain_model and all(c >= 6 for c in res.captain_model)  # picks the striker
    text = backtest.report(res)
    assert "Recent form" in text and "FPL projection" in text


def test_project_upcoming_uses_fixtures_and_availability(tmp_path):
    ds = DataStore(tmp_path / "p.sqlite3")
    rows = [pm(season="2026-27", gw=1, fixture=1, code=555, team=1, opponent=2, position="FWD", xg=0.8),
            pm(season="2026-27", gw=1, fixture=1, code=666, team=2, opponent=1, home=False, position="GKP", saves=5)]
    ds.replace_season("2026-27", rows, [Fixture("2026-27", 1, 1, 1, 2, None, True, 1, 0)],
                      {1: ("A", "AAA", 11), 2: ("B", "BBB", 22), 3: ("C", "CCC", 33)})
    fixtures = [{"id": 3, "event": 2, "team_h": 2, "team_a": 1}, {"id": 4, "event": 2, "team_h": 1, "team_a": 3}]
    gws, projs = project_upcoming(ds, _bootstrap(), fixtures, datetime(2026, 8, 25, tzinfo=UTC), horizon=3)
    assert gws == [2]
    by = {p.name: p for p in projs}
    assert by["Striker"].xp_by_gw[2] > 0 and "2 fixtures next gameweek (double)" in by["Striker"].notes
    assert by["Keeper"].xp_by_gw[2] == 0 and any("out until" in n for n in by["Keeper"].notes)
