"""The current season from the FPL API (bootstrap-static, fixtures, event/{gw}/live)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..datastore import Fixture, PlayerMatch
from ..scoring import ELEMENT_TYPE_TO_POS

# Stats that `explain` reports per fixture (used to split double gameweeks).
_EXPLAIN_KEYS = {
    "minutes": "minutes", "goals_scored": "goals", "assists": "assists", "clean_sheets": "clean_sheets",
    "goals_conceded": "goals_conceded", "saves": "saves", "penalties_saved": "pens_saved",
    "penalties_missed": "pens_missed", "yellow_cards": "yellow", "red_cards": "red",
    "own_goals": "own_goals", "bonus": "bonus",
}


def season_label(bootstrap: dict) -> str:
    first = min(e["deadline_time"] for e in bootstrap["events"])
    y = datetime.fromisoformat(first.replace("Z", "+00:00")).year
    return f"{y}-{str(y + 1)[-2:]}"


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse(bootstrap: dict, fixtures_json: list, lives: dict[int, dict]
          ) -> tuple[str, list[PlayerMatch], list[Fixture], dict[int, tuple[str, str, int]]]:
    """Build match rows for every finished gameweek in `lives` ({gw: event live JSON})."""
    season = season_label(bootstrap)
    teams = {t["id"]: (t["name"], t.get("short_name"), t["code"]) for t in bootstrap["teams"]}
    elements = {e["id"]: e for e in bootstrap["elements"]}

    fixtures = [Fixture(season=season, id=f["id"], gw=f.get("event"), team_h=f["team_h"], team_a=f["team_a"],
                        kickoff=f.get("kickoff_time"), finished=bool(f.get("finished")),
                        score_h=f.get("team_h_score"), score_a=f.get("team_a_score")) for f in fixtures_json]
    by_gw_team: dict[tuple[int, int], list[Fixture]] = {}
    for f in fixtures:
        if f.gw is None:
            continue
        by_gw_team.setdefault((f.gw, f.team_h), []).append(f)
        by_gw_team.setdefault((f.gw, f.team_a), []).append(f)

    matches = []
    for gw, live in lives.items():
        for le in live.get("elements", []):
            el = elements.get(le["id"])
            if el is None:
                continue
            team_fx = sorted(by_gw_team.get((gw, el["team"]), []), key=lambda f: f.id)
            if not team_fx:
                continue  # blank gameweek for this team
            s = le["stats"]
            per_fx = {f.id: {} for f in team_fx}
            for ex in le.get("explain", []):
                if ex.get("fixture") in per_fx:
                    for st in ex.get("stats", []):
                        key = _EXPLAIN_KEYS.get(st["identifier"])
                        if key:
                            per_fx[ex["fixture"]][key] = st["value"]
            total_min = s.get("minutes", 0) or 0
            for f in team_fx:
                vals = per_fx[f.id] if len(team_fx) > 1 else {k: s.get(api, 0) for api, k in _EXPLAIN_KEYS.items()}
                mins = vals.get("minutes", 0) or 0
                share = (mins / total_min) if total_min else (1 / len(team_fx))
                home = f.team_h == el["team"]
                matches.append(PlayerMatch(
                    season=season, gw=gw, fixture=f.id, code=el["code"], element=el["id"], name=el["web_name"],
                    team=el["team"], opponent=f.team_a if home else f.team_h, home=home,
                    position=ELEMENT_TYPE_TO_POS[el["element_type"]], n_fixtures=len(team_fx),
                    minutes=mins, starts=round(_f(s.get("starts")) * share) if total_min else 0,
                    goals=vals.get("goals", 0), assists=vals.get("assists", 0),
                    xg=_f(s.get("expected_goals")) * share, xa=_f(s.get("expected_assists")) * share,
                    xgc=_f(s.get("expected_goals_conceded")) * share,
                    clean_sheets=vals.get("clean_sheets", 0), goals_conceded=vals.get("goals_conceded", 0),
                    saves=vals.get("saves", 0), pens_saved=vals.get("pens_saved", 0),
                    pens_missed=vals.get("pens_missed", 0), yellow=vals.get("yellow", 0), red=vals.get("red", 0),
                    own_goals=vals.get("own_goals", 0), bonus=vals.get("bonus", 0),
                    bps=round(_f(s.get("bps")) * share),
                    dc=round(_f(s.get("defensive_contribution")) * share) if len(team_fx) == 1 else None,
                    points=round(_f(s.get("total_points")) * share), value=None, fpl_xp=None))
    return season, matches, fixtures, teams


def load_snapshot_dir(folder: Path) -> tuple[dict, list, dict[int, dict]]:
    """Read a samples/<date>/ folder written by `fplbot capture`."""
    bootstrap = json.loads((folder / "bootstrap-static.json").read_text(encoding="utf-8"))
    fixtures = json.loads((folder / "fixtures.json").read_text(encoding="utf-8"))
    lives = {}
    for p in folder.glob("event-*-live.json"):
        lives[int(p.stem.split("-")[1])] = json.loads(p.read_text(encoding="utf-8"))
    return bootstrap, fixtures, lives
