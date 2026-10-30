"""Chip decision for a gameweek (system-flow.md, section 5). One chip at most.

Order of checks when more than one qualifies: Bench Boost, Triple Captain, Wildcard, Free Hit.
Wildcard and Free Hit checks are not built yet; this module says so on the card
rather than silently skipping them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .squad import SquadPlan

BENCH_BOOST_THRESHOLD = 14.5   # owner's rule: projected total of the 4 bench players


@dataclass
class ChipDecision:
    chip: str | None                  # "bboost", "3xc", "wildcard", "freehit" or None
    lines: list[str] = field(default_factory=list)


def decide(plan: SquadPlan, chips_available: set[str], first_gameweek: bool) -> ChipDecision:
    g0 = plan.gws[0]
    lines = []
    bench_total = sum(p.xp_by_gw[g0] for p in plan.bench)
    chip = None

    if "bboost" in chips_available:
        ok = bench_total >= BENCH_BOOST_THRESHOLD
        lines.append(f"Bench Boost: bench projects {bench_total:.1f} pts against the {BENCH_BOOST_THRESHOLD} threshold "
                     f"-> {'PLAY' if ok else 'hold'}.")
        if ok:
            chip = "bboost"
    else:
        lines.append("Bench Boost: not available.")

    cap = plan.captain
    if "3xc" in chips_available:
        best_later = max((max(p.xp_by_gw[g] for p in plan.squad) for g in plan.gws[1:]), default=0.0)
        ok = cap.xp_by_gw[g0] >= best_later
        verdict = "qualifies" if ok else "hold"
        if ok and chip:
            verdict = "qualifies, but only one chip per gameweek and Bench Boost comes first"
        lines.append(f"Triple Captain: {cap.name} projects {cap.xp_by_gw[g0]:.2f} this week; best captain score "
                     f"in the rest of the {len(plan.gws)}-week horizon is {best_later:.2f} -> {verdict}.")
        if ok and not chip:
            chip = "3xc"
    else:
        lines.append("Triple Captain: not available.")

    if first_gameweek:
        lines.append("Wildcard: not needed (transfers are already unlimited before the team's first deadline).")
        lines.append("Free Hit: not allowed in a team's first gameweek.")
    else:
        lines.append("Wildcard / Free Hit: checks not built yet, so held this week.")
    return ChipDecision(chip, lines)
