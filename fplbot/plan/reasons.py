"""Plain-language reasoning for the decision card: how the squad was built and why each player is in it.

Everything here is derived from the same numbers the optimiser used, so the
reasons can be checked against the model and challenged in code review.
"""
from __future__ import annotations

from collections import Counter

from statistics import median

from ..model.project import PlayerProjection, TeamContext
from .squad import SquadPlan

PART_WORDS = {
    "appearance": "minutes", "goals": "goal threat", "assists": "chance creation", "clean_sheet": "clean-sheet chance",
    "saves": "saves", "defensive_contribution": "defensive contributions", "bonus": "bonus",
}
POS_WORDS = {"GKP": "goalkeepers", "DEF": "defenders", "MID": "midfielders", "FWD": "forwards"}


def _weighted_total(p: PlayerProjection, gws: list[int]) -> float:
    return sum(0.85 ** i * p.xp_by_gw[g] for i, g in enumerate(gws))


def _value_rank(p: PlayerProjection, pool: list[PlayerProjection]) -> tuple[int, int]:
    """Rank by points per £m among players in his position who are expected to play."""
    same = [q for q in pool if q.position == p.position and q.minutes_next >= 45]
    same.sort(key=lambda q: q.total / q.price, reverse=True)
    ids = [q.element for q in same]
    return (ids.index(p.element) + 1 if p.element in ids else len(ids) + 1), len(ids)


def _minutes_line(p: PlayerProjection) -> str:
    e = p.evidence
    n = int(e.get("n_matches", 0))
    if n == 0:
        return "no match record, so minutes are a guess"
    return (f"plays in {e['p_play']:.0%} of recent team matches and lasts 60+ in {e['p60']:.0%} "
            f"(about {e.get('mins_if_play', 0):.0f} mins when he plays)")


def _drivers(p: PlayerProjection) -> str:
    parts = sorted(((k, v) for k, v in p.parts_next.items() if k in PART_WORDS and k != "appearance" and v > 0.15),
                   key=lambda kv: -kv[1])[:3]
    if not parts:
        return "mostly appearance points"
    e = p.evidence
    out = []
    for k, v in parts:
        detail = ""
        if k == "goals":
            detail = f" ({e.get('xg90', 0):.2f} xG per 90)"
        elif k == "assists":
            detail = f" ({e.get('xa90', 0):.2f} xA per 90)"
        elif k == "defensive_contribution":
            detail = f" (hits the threshold in {e.get('dc_hit', 0):.0%} of full games)"
        elif k == "saves":
            detail = f" ({e.get('saves90', 0):.1f} saves per 90)"
        elif k == "bonus":
            detail = f" ({e.get('bonus90', 0):.2f} bonus per 90)"
        out.append(f"{PART_WORDS[k]} +{v:.2f}{detail}")
    return ", ".join(out)


def _fixture_run(p: PlayerProjection, gws: list[int]) -> str:
    bits = []
    for g in gws:
        fx = ", ".join(p.fixtures_by_gw.get(g, [])) or "blank"
        bits.append(f"GW{g} {fx} {p.xp_by_gw[g]:.1f}")
    return "; ".join(bits)


def _alternative(p: PlayerProjection, plan: SquadPlan, pool: list[PlayerProjection], full_clubs: set[str]) -> str:
    """Compare with the best unpicked player in his position at a similar or lower price."""
    in_squad = {q.element for q in plan.squad}
    rivals = [q for q in pool if q.position == p.position and q.element not in in_squad
              and q.price <= p.price + 5 and q.status != "u"]
    if not rivals:
        return "no comparable alternative"
    best = max(rivals, key=lambda q: _weighted_total(q, plan.gws))
    mine, theirs = _weighted_total(p, plan.gws), _weighted_total(best, plan.gws)
    diff = best.price - p.price
    price_txt = f"{abs(diff) / 10:.1f}m {'more' if diff > 0 else 'less'}" if diff else "same price"
    if mine >= theirs:
        return (f"beats the best similar-priced option, {best.name} ({best.team}, {price_txt}), "
                f"by {mine - theirs:.1f} weighted xP over the horizon")
    why = "his club already has 3 players in the squad" if best.team in full_clubs else \
        "the money is worth more elsewhere in the squad"
    return (f"{best.name} ({best.team}, {price_txt}) projects {theirs - mine:.1f} more on his own, "
            f"but {why}")


def _fixture_split(p: PlayerProjection, gws: list[int]) -> str | None:
    if not p.neutral_by_gw:
        return None
    neutral = sum(p.neutral_by_gw.get(g, 0.0) for g in gws)
    effect = p.total - neutral
    word = "easier" if effect > 0 else "harder"
    return (f"{neutral:.1f} of his {p.total:.1f} would come against average opponents; his fixtures are "
            f"{word} than average, worth {effect:+.1f}")


def _pct(x: float) -> str:
    return f"{abs(x - 1) * 100:.0f}% {'above' if x > 1 else 'below'} average"


def club_lines(plan: SquadPlan, ctx: TeamContext | None) -> list[str]:
    if ctx is None:
        return ["  Team ratings not available."]
    lines = [f"  Ratings come from expected goals for and against, recent matches weighted more (1.00 = league average)."]
    for club, n in Counter(p.team for p in plan.squad).most_common():
        t = ctx.teams.get(club)
        if t is None:
            continue
        o_att, o_def = ctx.opponent_average(club, plan.gws)
        run = ", ".join(f"{o} ({'H' if h else 'A'})" for g in plan.gws for o, h in t.opponents.get(g, [])) or "none"
        conc = abs(t.defence - 1) * 100
        conc_txt = "about average" if conc < 1 else f"{conc:.0f}% {'more' if t.defence > 1 else 'less'} than average"
        lines.append(f"  {club} x{n}: attack {t.attack:.2f} (creates {_pct(t.attack)}), defence {t.defence:.2f} "
                     f"(concedes {conc_txt}).")
        lines.append(f"    Opponents GW{plan.gws[0]}-{plan.gws[-1]}: {run}. Their average attack {o_att:.2f}, "
                     f"average defence {o_def:.2f}.")
    return lines


def position_value(pool: list[PlayerProjection]) -> dict[str, float]:
    """Median expected points per £m over the horizon, among players expected to play 60+ minutes."""
    out = {}
    for pos in ("GKP", "DEF", "MID", "FWD"):
        vals = [p.total / (p.price / 10) for p in pool if p.position == pos and p.minutes_next >= 60 and p.price]
        out[pos] = median(vals) if vals else 0.0
    return out


def player_reasons(plan: SquadPlan, pool: list[PlayerProjection]) -> list[str]:
    g0 = plan.gws[0]
    clubs = Counter(p.team for p in plan.squad)
    full = {c for c, n in clubs.items() if n >= 3}
    xi_ids = {p.element for p in plan.xi}
    lines = []
    for p in plan.squad:
        role = ("captain" if p is plan.captain else "vice-captain" if p is plan.vice else
                "starter" if p.element in xi_ids else f"bench {12 + plan.bench.index(p)}")
        rank, of = _value_rank(p, pool)
        lines.append(f"  {p.name} ({p.team}, {p.position}, {p.price / 10:.1f}m) - {role}")
        lines.append(f"    Projection: {p.xp_by_gw[g0]:.2f} xP in GW{g0}, {p.total:.1f} over {len(plan.gws)} weeks.")
        lines.append(f"    Minutes: {_minutes_line(p)}.")
        lines.append(f"    Points come from: {_drivers(p)}.")
        lines.append(f"    Fixtures: {_fixture_run(p, plan.gws)}.")
        split = _fixture_split(p, plan.gws)
        if split:
            lines.append(f"    Fixtures vs form: {split}.")
        lines.append(f"    Value: #{rank} of {of} {POS_WORDS[p.position]} for xP per £m over the horizon.")
        lines.append(f"    Versus alternatives: {_alternative(p, plan, pool, full)}.")
        if p.notes:
            lines.append(f"    Watch: {'; '.join(p.notes)}.")
        lines.append("")
    return lines


def squad_story(plan: SquadPlan, pool: list[PlayerProjection], budget: int) -> list[str]:
    g0 = plan.gws[0]
    lines = []
    xi_pos = Counter(p.position for p in plan.xi)
    formation = f"{xi_pos['DEF']}-{xi_pos['MID']}-{xi_pos['FWD']}"
    spend = {pos: sum(p.price for p in plan.squad if p.position == pos) for pos in ("GKP", "DEF", "MID", "FWD")}
    priciest = max(plan.squad, key=lambda p: p.price)
    top_overall = sorted((q for q in pool if q.status != "u"), key=lambda q: q.total, reverse=True)[:5]
    bench_cost = sum(p.price for p in plan.bench)
    bench_xp = sum(p.xp_by_gw[g0] for p in plan.bench)
    stacks = [f"{c} x{n}" for c, n in Counter(p.team for p in plan.squad).most_common() if n >= 2]
    defs = [p for p in plan.squad if p.position == "DEF"]
    dc_def = sum(p.parts_next.get("defensive_contribution", 0.0) for p in defs)
    xp_def = sum(p.xp_by_gw[g0] for p in defs)

    lines.append(f"  1. Goal: the most expected points over GW{plan.gws[0]}-{plan.gws[-1]}, nearer weeks counting more, "
                 f"within {budget / 10:.1f}m, 2/5/5/3 and max 3 per club.")
    lines.append(f"  2. Highest projected players over the horizon: "
                 + ", ".join(f"{q.name} {q.total:.1f}" for q in top_overall) + ".")
    lines.append(f"  3. Biggest spend: {priciest.name} at {priciest.price / 10:.1f}m "
                 f"({priciest.total:.1f} xP over the horizon). That leaves {(budget - priciest.price) / 10:.1f}m "
                 f"for the other 14, about {(budget - priciest.price) / 140:.1f}m each.")
    lines.append(f"  4. Money by position: GKP {spend['GKP'] / 10:.1f}m, DEF {spend['DEF'] / 10:.1f}m, "
                 f"MID {spend['MID'] / 10:.1f}m, FWD {spend['FWD'] / 10:.1f}m.")
    pv = position_value(pool)
    best = max(pv, key=pv.get)
    lines.append(f"     Value by position (median xP per £m over the horizon, players expected to play 60+): "
                 + ", ".join(f"{k} {v:.2f}" for k, v in pv.items()) + f". Best value right now: {POS_WORDS[best]}.")
    lines.append(f"     Defensive contribution points are {dc_def:.1f} of the defenders' {xp_def:.1f} projected in GW{g0}.")
    lines.append(f"  5. Formation {formation}: the XI is whichever 11 project most in GW{g0} within the formation rules.")
    if stacks:
        lines.append(f"  6. Clubs with more than one player: {', '.join(stacks)}. The optimiser has no club preference "
                     f"beyond the 3-player limit; the club ratings and fixtures behind these picks are under CLUBS.")
    lines.append(f"  7. Bench: {bench_cost / 10:.1f}m on 4 players projecting {bench_xp:.1f} in GW{g0}. "
                 f"Bench points count at 10% in the optimiser (auto-sub cover), so cheap but playing bench players win.")
    lines.append(f"  8. Captain: the starter with the highest GW{g0} projection; vice: next highest who is expected "
                 f"to play 60+ minutes.")
    return lines
