"""Match-level player data and fixtures, in the bot's SQLite file.

One row per player per gameweek per team fixture (`player_match`). Past seasons
come from the public vaastav/Fantasy-Premier-League archive, the current season
from the FPL API. Players are matched across seasons by FPL's stable `code`.
"""
from __future__ import annotations

import sqlite3
from dataclasses import astuple, dataclass, fields
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS player_match (
  season TEXT NOT NULL, gw INTEGER NOT NULL, fixture INTEGER NOT NULL,
  code INTEGER NOT NULL, element INTEGER NOT NULL, name TEXT,
  team INTEGER NOT NULL, opponent INTEGER NOT NULL, home INTEGER NOT NULL,
  position TEXT NOT NULL, n_fixtures INTEGER NOT NULL DEFAULT 1,
  minutes INTEGER NOT NULL, starts INTEGER, goals INTEGER, assists INTEGER,
  xg REAL, xa REAL, xgc REAL, clean_sheets INTEGER, goals_conceded INTEGER,
  saves INTEGER, pens_saved INTEGER, pens_missed INTEGER,
  yellow INTEGER, red INTEGER, own_goals INTEGER, bonus INTEGER, bps INTEGER,
  dc INTEGER, points INTEGER, value INTEGER, fpl_xp REAL,
  PRIMARY KEY (season, gw, code, fixture)
);
CREATE INDEX IF NOT EXISTS pm_season_gw ON player_match(season, gw);
CREATE INDEX IF NOT EXISTS pm_code ON player_match(code);
CREATE TABLE IF NOT EXISTS fixture (
  season TEXT NOT NULL, id INTEGER NOT NULL, gw INTEGER,
  team_h INTEGER NOT NULL, team_a INTEGER NOT NULL, kickoff TEXT,
  finished INTEGER NOT NULL, score_h INTEGER, score_a INTEGER,
  PRIMARY KEY (season, id)
);
CREATE TABLE IF NOT EXISTS team (
  season TEXT NOT NULL, id INTEGER NOT NULL, name TEXT NOT NULL, short_name TEXT, code INTEGER,
  PRIMARY KEY (season, id)
);
"""


@dataclass
class PlayerMatch:
    season: str
    gw: int
    fixture: int
    code: int
    element: int
    name: str
    team: int
    opponent: int
    home: bool
    position: str
    n_fixtures: int
    minutes: int
    starts: int | None
    goals: int
    assists: int
    xg: float | None
    xa: float | None
    xgc: float | None
    clean_sheets: int
    goals_conceded: int
    saves: int
    pens_saved: int
    pens_missed: int
    yellow: int
    red: int
    own_goals: int
    bonus: int
    bps: int
    dc: int | None
    points: int
    value: int | None
    fpl_xp: float | None


@dataclass
class Fixture:
    season: str
    id: int
    gw: int | None
    team_h: int
    team_a: int
    kickoff: str | None
    finished: bool
    score_h: int | None
    score_a: int | None


PM_COLS = [f.name for f in fields(PlayerMatch)]
FX_COLS = [f.name for f in fields(Fixture)]


class DataStore:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def replace_season(self, season: str, matches: list[PlayerMatch], fixtures: list[Fixture],
                       teams: dict[int, tuple[str, str | None, int]]) -> None:
        """Replace everything stored for `season` in one transaction."""
        with self.conn:
            for table in ("player_match", "fixture", "team"):
                self.conn.execute(f"DELETE FROM {table} WHERE season = ?", (season,))
            self.conn.executemany(
                f"INSERT OR REPLACE INTO player_match ({','.join(PM_COLS)}) VALUES ({','.join('?' * len(PM_COLS))})",
                [astuple(m) for m in matches])
            self.conn.executemany(
                f"INSERT OR REPLACE INTO fixture ({','.join(FX_COLS)}) VALUES ({','.join('?' * len(FX_COLS))})",
                [astuple(f) for f in fixtures])
            self.conn.executemany("INSERT OR REPLACE INTO team VALUES (?, ?, ?, ?, ?)",
                                  [(season, tid, n, s, c) for tid, (n, s, c) in teams.items()])

    def seasons(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT season FROM player_match ORDER BY season")]

    def matches(self, season: str, before_gw: int | None = None, gw: int | None = None) -> list[PlayerMatch]:
        q, args = f"SELECT {','.join(PM_COLS)} FROM player_match WHERE season = ?", [season]
        if before_gw is not None:
            q += " AND gw < ?"
            args.append(before_gw)
        if gw is not None:
            q += " AND gw = ?"
            args.append(gw)
        q += " ORDER BY gw, fixture"
        out = []
        for row in self.conn.execute(q, args):
            m = PlayerMatch(*row)
            m.home = bool(m.home)
            out.append(m)
        return out

    def fixtures(self, season: str) -> list[Fixture]:
        out = []
        for row in self.conn.execute(f"SELECT {','.join(FX_COLS)} FROM fixture WHERE season = ? ORDER BY kickoff", (season,)):
            f = Fixture(*row)
            f.finished = bool(f.finished)
            out.append(f)
        return out

    def teams(self, season: str) -> dict[int, tuple[str, str | None, int]]:
        """{season team id: (name, short name, stable team code)}"""
        return {r[0]: (r[1], r[2], r[3]) for r in self.conn.execute(
            "SELECT id, name, short_name, code FROM team WHERE season = ?", (season,))}
