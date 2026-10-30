"""Team attack and defence strength, fitted to expected goals (xG).

Model: a team's xG in a match = league mean x its attack x the opponent's
defence x a home or away factor. Recent matches count more (time decay), and
every team is pulled toward a prior so a few matches can't swing it far.
Teams are keyed by FPL's stable team code, so last season carries over.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TeamMatch:
    team: int          # team code
    opponent: int      # team code
    home: bool
    xg_for: float
    age: float         # gameweeks ago (last season counts as further back)


@dataclass
class Ratings:
    mean_xg: float
    home_factor: float  # multiply home team's xG by this, divide away team's by it
    attack: dict[int, float]
    defence: dict[int, float]  # >1 means concedes more than average

    def expected_xg(self, team: int, opponent: int, home: bool) -> float:
        h = self.home_factor if home else 1 / self.home_factor
        return self.mean_xg * self.attack.get(team, 1.0) * self.defence.get(opponent, 1.0) * h

    def average_xg_for(self, team: int) -> float:
        return self.mean_xg * self.attack.get(team, 1.0)


HALF_LIFE_GW = 12.0
PRIOR_MATCHES = 4.0
# Teams with no top-flight history in the data (promoted) start weaker.
NEW_TEAM_PRIOR = (0.85, 1.15)


def fit(matches: list[TeamMatch], known_teams: set[int] | None = None, iterations: int = 30) -> Ratings:
    if not matches:
        return Ratings(1.35, 1.1, {}, {})
    w = [0.5 ** (m.age / HALF_LIFE_GW) for m in matches]
    wsum = sum(w)
    mean = sum(wi * m.xg_for for wi, m in zip(w, matches)) / wsum

    home_w = sum(wi for wi, m in zip(w, matches) if m.home)
    away_w = wsum - home_w
    if home_w > 0 and away_w > 0:
        home_mean = sum(wi * m.xg_for for wi, m in zip(w, matches) if m.home) / home_w
        away_mean = sum(wi * m.xg_for for wi, m in zip(w, matches) if not m.home) / away_w
        hf = math.sqrt(home_mean / away_mean) if away_mean > 0 else 1.0
    else:
        hf = 1.0

    teams = {m.team for m in matches} | {m.opponent for m in matches} | (known_teams or set())
    seen = {m.team for m in matches}
    prior_att = {t: (1.0 if t in seen else NEW_TEAM_PRIOR[0]) for t in teams}
    prior_def = {t: (1.0 if t in seen else NEW_TEAM_PRIOR[1]) for t in teams}
    att, dfn = dict(prior_att), dict(prior_def)

    for _ in range(iterations):
        num = {t: PRIOR_MATCHES * prior_att[t] for t in teams}
        den = {t: PRIOR_MATCHES for t in teams}
        for wi, m in zip(w, matches):
            h = hf if m.home else 1 / hf
            num[m.team] += wi * m.xg_for
            den[m.team] += wi * mean * dfn[m.opponent] * h
        att = {t: num[t] / den[t] for t in teams}

        num = {t: PRIOR_MATCHES * prior_def[t] for t in teams}
        den = {t: PRIOR_MATCHES for t in teams}
        for wi, m in zip(w, matches):
            h = hf if m.home else 1 / hf
            num[m.opponent] += wi * m.xg_for
            den[m.opponent] += wi * mean * att[m.team] * h
        dfn = {t: num[t] / den[t] for t in teams}

    return Ratings(mean, hf, att, dfn)
