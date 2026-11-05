"""Pick the best 15-man squad within the rules, plus the XI, bench order, captain and vice-captain.

Used for the initial squad (unlimited free transfers before the team's first
deadline) and later for Wildcard and Free Hit weeks. It is a mixed-integer
program solved with HiGHS (scipy): maximise expected points over the planning
horizon, nearer gameweeks weighted more, where each gameweek's XI and captain
are chosen from the squad and the bench counts a little (it covers auto-subs).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from ..model.project import PlayerProjection
from .rules import SquadRules

GW_DECAY = 0.85          # weight of each later gameweek relative to the one before
BENCH_WEIGHT = 0.1       # bench points count this much (auto-sub cover)
SHORTLIST_PER_POS = 45   # best candidates per position kept for the solver
CHEAP_PER_POS = 8        # plus the cheapest per position, as budget fillers
HIT_COST = 4             # points per transfer beyond the free ones (rules file A5)
# Owner's rules (2026-11-05): saving free transfers is the default, because saved ones cover later
# injuries, form dips and fixture swings without hits. A transfer is made when the incoming player
# projects at least TRANSFER_GAIN_BAR more points over the horizon (unweighted total), or when the
# outgoing player is out long-term (no expected points in LONG_INJURY_WEEKS of the horizon weeks),
# in which case any real upgrade will do.
TRANSFER_GAIN_BAR = 10.0
LONG_INJURY_WEEKS = 3


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
    # Transfer mode only: players sold and bought, and the hit taken.
    sold: list[PlayerProjection] = field(default_factory=list)
    bought: list[PlayerProjection] = field(default_factory=list)
    hits: int = 0
    free_transfers: int | None = None
    bank_after: int | None = None

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
               team_of: dict[int, int], budget: int | None = None,
               current: dict[int, int] | None = None, bank: int = 0,
               free_transfers: int | None = None) -> SquadPlan:
    """Best squad, XI and captain over the horizon.

    `team_of`: element id -> team id (for the club limit).
    Transfer mode: `current` maps the owned players' element ids to their selling
    prices, `bank` is money in the bank and `free_transfers` the free transfers
    available (None = unlimited). Owned players are valued at their selling price,
    new ones at today's price, and each transfer beyond the free ones costs
    HIT_COST points.
    """
    weights = [GW_DECAY ** i for i in range(len(gws))]
    by_id = {p.element: p for p in projs}
    cands = [p for p in _shortlist(projs, weights, gws) if p.status != "u"]
    if current is not None:
        # Incoming players must be fully available (owner's rule); owned players stay candidates whatever their status.
        cands = [p for p in cands if p.status == "a" or p.element in current]
        have = {p.element for p in cands}
        cands += [by_id[e] for e in current if e in by_id and e not in have]
        budget = bank + sum(current.values())
    budget = rules.budget if budget is None else budget
    n, G = len(cands), len(gws)
    # Variable layout: x[p], then s[p, g] (starter), then c[p, g] (captain), then (transfer mode) extra transfers.
    nx, ns = n, n * G
    transfer_mode = current is not None and free_transfers is not None
    nv = nx + 2 * ns + (1 if transfer_mode else 0)
    eidx = nx + 2 * ns
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

    cost_of = {i: (current[p.element] if current and p.element in current else p.price) for i, p in enumerate(cands)}
    add(cost_of, 0, budget)
    if transfer_mode:
        new = [i for i, p in enumerate(cands) if p.element not in current]
        # extra >= transfers - free; each extra costs a hit, each transfer must clear the minimum gain.
        add({**{i: 1 for i in new}, eidx: -1}, -np.inf, free_transfers)
        add({i: 1 for i in new}, 0, rules.transfer_cap)
        obj[eidx] -= HIT_COST
        # The bar is in unweighted points over the horizon; the objective is weighted, so scale it.
        bar = TRANSFER_GAIN_BAR * sum(weights) / len(weights)
        for i in new:
            obj[i] -= bar
        # Keeping a long-term absentee costs the bar, so selling him and buying a replacement nets out.
        for i, p in enumerate(cands):
            if p.element in current and long_term_out(p, gws):
                obj[i] -= bar
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
    upper = np.ones(nv)
    if transfer_mode:
        upper[eidx] = rules.squad_size
    res = milp(-obj, constraints=LinearConstraint(a, lo, hi),
               integrality=np.ones(nv), bounds=Bounds(0, upper), options={"time_limit": 120})
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
    plan = SquadPlan(squad=sorted(squad, key=_pos_order), xi=sorted(xi, key=_pos_order), bench=gk + outfield,
                     captain=captain, vice=vice, gws=gws, objective=float(-res.fun),
                     cost=sum(cost_of[i] for i in range(n) if x[i]))
    if current is not None:
        ids = {p.element for p in squad}
        plan.sold = sorted((by_id[e] for e in current if e in by_id and e not in ids), key=_pos_order)
        plan.bought = sorted((p for p in squad if p.element not in current), key=_pos_order)
        plan.hits = int(x[eidx]) if transfer_mode else 0
        plan.free_transfers = free_transfers
        plan.bank_after = budget - plan.cost
    return plan


def long_term_out(p: PlayerProjection, gws: list[int]) -> bool:
    """Not available and no expected points in at least LONG_INJURY_WEEKS of the horizon weeks."""
    return p.status != "a" and sum(1 for g in gws if p.xp_by_gw.get(g, 0.0) < 0.5) >= LONG_INJURY_WEEKS


def choose_captains(xi: list[PlayerProjection], gw: int) -> tuple[PlayerProjection, PlayerProjection]:
    """Captain: highest expected points. Vice: next highest among starters expected to play 60+ minutes (rules file C3)."""
    ranked = sorted(xi, key=lambda p: p.xp_by_gw[gw], reverse=True)
    captain = ranked[0]
    likely = [p for p in ranked[1:] if p.minutes_next >= 60] or ranked[1:]
    return captain, likely[0]


def _pos_order(p: PlayerProjection) -> tuple[int, float]:
    return ({"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}[p.position], -p.total)
