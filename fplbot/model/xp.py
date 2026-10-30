"""Expected FPL points for one player in one fixture, broken down by source.

Each part follows the 2026/27 points table (rules file A9):
appearance, goals, assists, clean sheet, goals conceded, saves,
defensive contribution, bonus and cards.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..datastore import DataStore, PlayerMatch
from ..scoring import SAVES_PER_POINT, GOALS_CONCEDED_PER_DEDUCTION
from . import ratings as ratings_mod
from .players import Profile, build_profile, position_priors


def poisson_floor_mean(lam: float, k: int) -> float:
    """E[floor(X / k)] for X ~ Poisson(lam)."""
    if lam <= 0:
        return 0.0
    top = int(lam + 10 * math.sqrt(lam) + 20)
    p = math.exp(-lam)
    total = 0.0
    for n in range(top + 1):
        if n > 0:
            p *= lam / n
        total += p * (n // k)
    return total


@dataclass
class Projection:
    xp: float
    parts: dict[str, float] = field(default_factory=dict)
    exp_minutes: float = 0.0


def project_fixture(prof: Profile, team: int, opponent: int, home: bool, rt: ratings_mod.Ratings,
                    pts: dict[str, dict[str, float]], avail: float = 1.0) -> Projection:
    pos = prof.position
    p_play = prof.p_play * avail
    p60 = prof.p60 * avail
    p_short = max(0.0, p_play - p60)
    exp_min = min(p60 * prof.mins_if_60 + p_short * min(prof.mins_if_play, 59.0), 90.0)
    frac = exp_min / 90.0

    team_xg = rt.expected_xg(team, opponent, home)
    opp_xg = rt.expected_xg(opponent, team, not home)
    att_adj = team_xg / max(rt.average_xg_for(team), 0.05)

    parts = {}
    parts["appearance"] = p_short * pts["short_play"][pos] + p60 * pts["long_play"][pos]
    parts["goals"] = prof.rates.get("xg", 0.0) * frac * att_adj * pts["goals_scored"][pos]
    parts["assists"] = prof.rates.get("xa", 0.0) * frac * att_adj * pts["assists"][pos]

    on_pitch_60 = prof.mins_if_60 / 90.0
    parts["clean_sheet"] = p60 * math.exp(-opp_xg * on_pitch_60) * pts["clean_sheets"][pos]

    if pts["goals_conceded"][pos]:
        lam = opp_xg * frac
        parts["goals_conceded"] = poisson_floor_mean(lam, GOALS_CONCEDED_PER_DEDUCTION) * pts["goals_conceded"][pos]
    if pts["saves"][pos]:
        # More saves against stronger attacks: scale by the opponent's xG relative to average.
        lam = prof.rates.get("saves", 0.0) * frac * (opp_xg / max(rt.mean_xg, 0.05))
        parts["saves"] = poisson_floor_mean(lam, SAVES_PER_POINT) * pts["saves"][pos]
    if pts["defensive_contribution"][pos]:
        parts["defensive_contribution"] = p60 * prof.dc_hit * pts["defensive_contribution"][pos]
    parts["bonus"] = prof.rates.get("bonus", 0.0) * frac * pts["bonus"][pos]
    parts["cards"] = prof.rates.get("yellow", 0.0) * frac * pts["yellow_cards"][pos]

    return Projection(xp=sum(parts.values()), parts=parts, exp_minutes=exp_min)


# --- Building the model state from the data store ---------------------------------

@dataclass
class ModelState:
    season: str
    ratings: ratings_mod.Ratings
    profiles: dict[int, Profile]          # by player code
    team_code: dict[int, int]             # this season's team id -> stable team code


def _team_matches(rows: list[PlayerMatch], team_codes: dict[tuple[str, int], int],
                  season_order: dict[str, int], cutoff_gw: int) -> list[ratings_mod.TeamMatch]:
    xg: dict[tuple[str, int, int], float] = {}
    meta: dict[tuple[str, int, int], tuple[int, bool, int]] = {}
    for r in rows:
        if r.xg is None:
            continue
        key = (r.season, r.fixture, r.team)
        xg[key] = xg.get(key, 0.0) + r.xg
        meta[key] = (r.opponent, r.home, r.gw)
    out = []
    for (season, _fx, team), total in xg.items():
        opp, home, gw = meta[(season, _fx, team)]
        tc, oc = team_codes.get((season, team)), team_codes.get((season, opp))
        if tc is None or oc is None:
            continue
        age = (cutoff_gw - gw) + 38 * season_order[season]
        out.append(ratings_mod.TeamMatch(tc, oc, home, total, age))
    return out


def build_state(store: DataStore, season: str, before_gw: int, prior_season: str | None,
                positions: dict[int, str] | None = None) -> ModelState:
    """Fit ratings and player profiles from all data before `before_gw` of `season` (plus last season).

    `positions`: current position by player code (from the live API); defaults to the latest row's position.
    """
    rows = store.matches(season, before_gw=before_gw)
    prior_rows = store.matches(prior_season) if prior_season else []
    team_codes = {(season, tid): c for tid, (_n, _s, c) in store.teams(season).items()}
    if prior_season:
        team_codes.update({(prior_season, tid): c for tid, (_n, _s, c) in store.teams(prior_season).items()})
    order = {season: 0}
    if prior_season:
        order[prior_season] = 1

    all_rows = prior_rows + rows
    tm = _team_matches(all_rows, team_codes, order, before_gw)
    current_codes = {c for (s, _t), c in team_codes.items() if s == season}
    rt = ratings_mod.fit(tm, known_teams=current_codes)

    priors = position_priors(all_rows)
    by_player: dict[int, list[PlayerMatch]] = {}
    for r in all_rows:
        by_player.setdefault(r.code, []).append(r)
    profiles = {}
    for code, prs in by_player.items():
        pos = (positions or {}).get(code) or prs[-1].position
        profiles[code] = build_profile(code, pos, prs, season, priors)
    team_code = {tid: c for (s, tid), c in team_codes.items() if s == season}
    return ModelState(season, rt, profiles, team_code)
