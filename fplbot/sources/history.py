"""Past seasons from the public vaastav/Fantasy-Premier-League archive (MIT licence).

Files are downloaded once into the cache folder; finished seasons never change.
"""
from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

import requests

from ..datastore import Fixture, PlayerMatch

BASE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/{season}/{file}"
FILES = ("gws/merged_gw.csv", "players_raw.csv", "teams.csv", "fixtures.csv")
POS = {"GK": "GKP", "GKP": "GKP", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}

log = logging.getLogger("fplbot.history")


def download(season: str, cache: Path, session: requests.Session | None = None) -> Path:
    """Download the season's files into cache/history/<season>/ unless already there."""
    session = session or requests.Session()
    out = cache / "history" / season
    out.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        target = out / f.replace("/", "_")
        if target.exists() and target.stat().st_size > 0:
            continue
        r = session.get(BASE.format(season=season, file=f), timeout=60)
        r.raise_for_status()
        target.write_bytes(r.content)
        log.info("downloaded %s %s", season, f)
    return out


def _rows(path: Path) -> list[dict]:
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _int(v, default=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse(season: str, folder: Path) -> tuple[list[PlayerMatch], list[Fixture], dict[int, tuple[str, str, int]]]:
    teams_rows = _rows(folder / "teams.csv")
    teams = {_int(t["id"]): (t["name"], t.get("short_name"), _int(t["code"])) for t in teams_rows}
    team_by_name = {t["name"]: _int(t["id"]) for t in teams_rows}
    code_by_element = {_int(p["id"]): _int(p["code"]) for p in _rows(folder / "players_raw.csv")}

    fixtures = []
    for f in _rows(folder / "fixtures.csv"):
        fixtures.append(Fixture(
            season=season, id=_int(f["id"]), gw=_int(f["event"], None) if f.get("event") else None,
            team_h=_int(f["team_h"]), team_a=_int(f["team_a"]), kickoff=f.get("kickoff_time") or None,
            finished=f.get("finished") == "True",
            score_h=_int(f["team_h_score"], None) if f.get("team_h_score") not in ("", None) else None,
            score_a=_int(f["team_a_score"], None) if f.get("team_a_score") not in ("", None) else None))

    raw = _rows(folder / "gws_merged_gw.csv")
    per_gw = {}
    for r in raw:
        per_gw[(r["element"], r["GW"])] = per_gw.get((r["element"], r["GW"]), 0) + 1

    matches = []
    for r in raw:
        pos = POS.get(r.get("position", ""))
        if pos is None:  # e.g. "AM" (2024/25 assistant managers)
            continue
        element = _int(r["element"])
        team = team_by_name.get(r.get("team", ""))
        if team is None:
            continue
        fpl_xp = _float(r.get("xP"))
        matches.append(PlayerMatch(
            season=season, gw=_int(r["GW"]), fixture=_int(r["fixture"]),
            code=code_by_element.get(element, -element), element=element, name=r.get("name"),
            team=team, opponent=_int(r["opponent_team"]), home=r.get("was_home") == "True",
            position=pos, n_fixtures=per_gw[(r["element"], r["GW"])],
            minutes=_int(r["minutes"]), starts=_int(r["starts"], None) if r.get("starts") not in ("", None) else None,
            goals=_int(r["goals_scored"]), assists=_int(r["assists"]),
            xg=_float(r.get("expected_goals")), xa=_float(r.get("expected_assists")),
            xgc=_float(r.get("expected_goals_conceded")),
            clean_sheets=_int(r["clean_sheets"]), goals_conceded=_int(r["goals_conceded"]),
            saves=_int(r["saves"]), pens_saved=_int(r["penalties_saved"]), pens_missed=_int(r["penalties_missed"]),
            yellow=_int(r["yellow_cards"]), red=_int(r["red_cards"]), own_goals=_int(r["own_goals"]),
            bonus=_int(r["bonus"]), bps=_int(r["bps"]),
            dc=_int(r["defensive_contribution"], None) if r.get("defensive_contribution") not in ("", None) else None,
            points=_int(r["total_points"]), value=_int(r.get("value"), None),
            fpl_xp=fpl_xp if fpl_xp else None))
    return matches, fixtures, teams
