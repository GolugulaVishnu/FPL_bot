"""Pick the best 15-man squad within the rules, plus the XI, bench order, captain and vice-captain.

Used for the initial squad (unlimited free transfers before the team's first
deadline) and later for Wildcard and Free Hit weeks. It is a mixed-integer
program solved with HiGHS (scipy): maximise expected points over the planning
horizon, nearer gameweeks weighted more, where each gameweek's XI and captain
are chosen from the squad and the bench counts a little (it covers auto-subs).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from ..model.project import PlayerProjection
from .rules import SquadRules

GW_DECAY = 0.85          # weight of each later gameweek relative to the one before
BENCH_WEIGHT = 0.1       # bench points count this much (auto-sub cover)
SHORTLIST_PER_POS = 45   # best candidates per position kept for the solver
CHEAP_PER_POS = 8        # plus the cheapest per position, as budget fillers


@dataclass
class SquadPlan:
    squad: list[PlayerProjection]
    xi: list[PlayerProjection]
    bench: list[PlayerProjection]          # in substitution order; bench[0] is the reserve goalkeeper
    captain: PlayerProjection
    vice: PlayerProjection
    gws: list[int]
    objective: float
    cost: int

    @property
    def xi_points_next(self) -> float:
        g = self.gws[0]
        return sum(p.xp_by_gw[g] for p in self.xi) + self.captain.xp_by_gw[g]


def _shortlist(projs: list[PlayerProjection], weights: list[float], gws: list[int]) -> list[PlayerProjection]:
    keep: dict[int, PlayerProjection] = {}
    for pos in ("GKP", "DEF", "MID", "FWD"):
        cands = [p for p in projs if p.position == pos]
        score = lambda p: sum(w * p.xp_by_gw[g] for w, g in zip(weights, gws))
        for p in sorted(cands, key=score, reverse=True)[:SHORTLIST_PER_POS]:
            keep[p.element] = p
        playing = [p for p in cands if p.minutes_next > 0 or score(p) > 0]
        for p in sorted(playing, key=lambda p: p.price)[:CHEAP_PER_POS]:
            keep[p.element] = p
    return list(keep.values())


def pick_squad(projs: list[PlayerProjection], gws: list[int], rules: SquadRules,
               team_of: dict[int, int], budget: int | None = None) -> SquadPlan:
    """`team_of`: element id -> team id (for the club limit)."""
    budget = rules.budget if budget is None else budget
    weights = [GW_DECAY ** i for i in range(len(gws))]
    cands = [p for p in _shortlist(projs, weights, gws) if p.status != "u"]
    n, G = len(cands), len(gws)
    # Variable layout: x[p], then s[p, g] (starter), then c[p, g] (captain).
    nx, ns = n, n * G
    nv = nx + 2 * ns
    sidx = lambda i, g: nx + i * G + g
    cidx = lambda i, g: nx + ns + i * G + g

    obj = np.zeros(nv)
    for i, p in enumerate(cands):
        for g, gw in enumerate(gws):
            xp = p.xp_by_gw[gw] * weights[g]
            obj[i] += BENCH_WEIGHT * xp
            obj[sidx(i, g)] += xp - BENCH_WEIGHT * xp
            obj[cidx(i, g)] += xp
    ri, ci, vals, lo, hi = [], [], [], [], []

    def add(coefs: dict[int, float], lower: float, upper: float) -> None:
        row = len(lo)
        for k, v in coefs.items():
            ri.append(row)
            ci.append(k)
            vals.append(v)
        lo.append(lower)
        hi.append(upper)

    add({i: p.price for i, p in enumerate(cands)}, 0, budget)
    for pos, cnt in rules.squad_count.items():
        add({i: 1 for i, p in enumerate(cands) if p.position == pos}, cnt, cnt)
    for team in set(team_of[p.element] for p in cands):
        add({i: 1 for i, p in enumerate(cands) if team_of[p.element] == team}, 0, rules.club_limit)
    for g in range(G):
        add({sidx(i, g): 1 for i in range(n)}, rules.starters, rules.starters)
        for pos in rules.xi_min:
            add({sidx(i, g): 1 for i, p in enumerate(cands) if p.position == pos}, rules.xi_min[pos], rules.xi_max[pos])
        add({cidx(i, g): 1 for i in range(n)}, 1, 1)
        for i in range(n):
            add({sidx(i, g): 1, i: -1}, -np.inf, 0)
            add({cidx(i, g): 1, sidx(i, g): -1}, -np.inf, 0)

    a = coo_matrix((vals, (ri, ci)), shape=(len(lo), nv)).tocsr()
    res = milp(-obj, constraints=LinearConstraint(a, lo, hi),
               integrality=np.ones(nv), bounds=Bounds(0, 1), options={"time_limit": 120})
    if res.x is None:
        raise RuntimeError(f"squad optimiser found no solution: {res.message}")
    x = np.round(res.x).astype(int)

    squad = [p for i, p in enumerate(cands) if x[i]]
    g0 = gws[0]
    xi = [p for i, p in enumerate(cands) if x[sidx(i, 0)]]
    xi_ids = {p.element for p in xi}
    bench_rest = [p for p in squad if p.element not in xi_ids]
    gk = [p for p in bench_rest if p.position == "GKP"]
    # Bench order (rules file C2): likeliest to play first, then expected points.
    outfield = sorted((p for p in bench_rest if p.position != "GKP"),
                      key=lambda p: (round(p.minutes_next / 30), p.xp_by_gw[g0]), reverse=True)
    captain, vice = choose_captains(xi, g0)
    return SquadPlan(squad=sorted(squad, key=_pos_order), xi=sorted(xi, key=_pos_order), bench=gk + outfield,
                     captain=captain, vice=vice, gws=gws, objective=float(-res.fun),
                     cost=sum(p.price for p in squad))


def choose_captains(xi: list[PlayerProjection], gw: int) -> tuple[PlayerProjection, PlayerProjection]:
    """Captain: highest expected points. Vice: next highest among starters expected to play 60+ minutes (rules file C3)."""
    ranked = sorted(xi, key=lambda p: p.xp_by_gw[gw], reverse=True)
    captain = ranked[0]
    likely = [p for p in ranked[1:] if p.minutes_next >= 60] or ranked[1:]
    return captain, likely[0]


def _pos_order(p: PlayerProjection) -> tuple[int, float]:
    return ({"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}[p.position], -p.total)
