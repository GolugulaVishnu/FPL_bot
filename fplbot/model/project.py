"""Project every current player's expected points for the next few gameweeks."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..datastore import DataStore
from ..scoring import ELEMENT_TYPE_TO_POS, normalise
from ..sources.current import season_label
from . import availability
from .players import Profile
from .xp import build_state, project_fixture


@dataclass
class PlayerProjection:
    element: int
    code: int
    name: str
    team: str
    position: str
    price: int                       # tenths of £1m (now_cost)
    status: str
    xp_by_gw: dict[int, float]
    parts_next: dict[str, float]     # breakdown for the next gameweek
    minutes_next: float
    notes: list[str] = field(default_factory=list)
    # Evidence behind the numbers, for the decision card's reasoning.
    fixtures_by_gw: dict[int, list[str]] = field(default_factory=dict)   # e.g. {9: ["LIV (A)"]}
    evidence: dict[str, float] = field(default_factory=dict)             # p_play, p60, xg90, xa90, ...

    @property
    def total(self) -> float:
        return sum(self.xp_by_gw.values())


def previous_season(season: str) -> str:
    y = int(season[:4]) - 1
    return f"{y}-{str(y + 1)[-2:]}"


def project_upcoming(store: DataStore, bootstrap: dict, fixtures_json: list, now: datetime,
                     horizon: int = 6) -> tuple[list[int], list[PlayerProjection]]:
    season = season_label(bootstrap)
    upcoming = sorted((e for e in bootstrap["events"]
                       if datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")) > now),
                      key=lambda e: e["id"])[:horizon]
    if not upcoming:
        return [], []
    gws = [e["id"] for e in upcoming]
    gw_start = {e["id"]: datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")) for e in upcoming}

    positions = {e["code"]: ELEMENT_TYPE_TO_POS[e["element_type"]] for e in bootstrap["elements"]}
    prior = previous_season(season)
    state = build_state(store, season, gws[0], prior if prior in store.seasons() else None, positions)
    pts = normalise(bootstrap.get("game_config", {}).get("scoring"))
    teams = {t["id"]: t for t in bootstrap["teams"]}

    fixtures_by_team_gw: dict[tuple[int, int], list[tuple[int, bool]]] = {}
    for f in fixtures_json:
        if f.get("event") in gw_start:
            fixtures_by_team_gw.setdefault((f["team_h"], f["event"]), []).append((f["team_a"], True))
            fixtures_by_team_gw.setdefault((f["team_a"], f["event"]), []).append((f["team_h"], False))

    out = []
    for el in bootstrap["elements"]:
        pos = ELEMENT_TYPE_TO_POS[el["element_type"]]
        prof = state.profiles.get(el["code"]) or Profile(code=el["code"], position=pos,
                                                         notes=["no match history: projected as not playing"])
        prof.position = pos
        notes = list(prof.notes)
        tc = state.team_code.get(el["team"])
        xp_by_gw, parts_next, minutes_next, fixtures_by_gw = {}, {}, 0.0, {}
        for i, gw in enumerate(gws):
            fac, why = availability.factor(el.get("status"), el.get("chance_of_playing_next_round"),
                                           el.get("news"), gw_start[gw], i, now)
            if why and i == 0:
                notes.append(why)
            total = 0.0
            fx = fixtures_by_team_gw.get((el["team"], gw), [])
            fixtures_by_gw[gw] = [f"{teams[o]['short_name']} ({'H' if h else 'A'})" for o, h in fx]
            for j, (opp, home) in enumerate(fx):
                p = project_fixture(prof, tc, state.team_code.get(opp), home, state.ratings, pts, fac)
                total += p.xp
                if i == 0:
                    minutes_next += p.exp_minutes
                    for k, v in p.parts.items():
                        parts_next[k] = parts_next.get(k, 0.0) + v
            if not fx and i == 0:
                notes.append("no fixture next gameweek (blank)")
            if len(fx) > 1 and i == 0:
                notes.append(f"{len(fx)} fixtures next gameweek (double)")
            xp_by_gw[gw] = total
        out.append(PlayerProjection(
            element=el["id"], code=el["code"], name=el["web_name"], team=teams[el["team"]]["short_name"],
            position=pos, price=el["now_cost"], status=el.get("status", "a"), xp_by_gw=xp_by_gw,
            parts_next=parts_next, minutes_next=minutes_next, notes=notes, fixtures_by_gw=fixtures_by_gw,
            evidence={"p_play": prof.p_play, "p60": prof.p60, "mins_if_play": prof.mins_if_play,
                      "xg90": prof.rates.get("xg", 0.0), "xa90": prof.rates.get("xa", 0.0),
                      "saves90": prof.rates.get("saves", 0.0), "bonus90": prof.rates.get("bonus", 0.0),
                      "dc_hit": prof.dc_hit, "n_matches": float(prof.n_matches), "nineties": prof.nineties}))
    return gws, out


def format_table(gws: list[int], projs: list[PlayerProjection], top: int = 30, position: str | None = None) -> str:
    rows = [p for p in projs if position is None or p.position == position]
    rows.sort(key=lambda p: -p.total)
    head = f"{'Player':<18}{'Team':<5}{'Pos':<4}{'£m':>5}" + "".join(f"{'GW' + str(g):>6}" for g in gws) + f"{'Total':>7}  Notes"
    lines = [head, "-" * len(head)]
    for p in rows[:top]:
        lines.append(f"{p.name[:17]:<18}{p.team:<5}{p.position:<4}{p.price / 10:>5.1f}"
                     + "".join(f"{p.xp_by_gw[g]:>6.2f}" for g in gws) + f"{p.total:>7.2f}  {'; '.join(p.notes)}")
    return "\n".join(lines)
