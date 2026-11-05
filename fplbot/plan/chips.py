"""Chip decision for a gameweek (system-flow.md, section 5). One chip at most.

Order of checks when more than one qualifies: Bench Boost, Triple Captain, Wildcard, Free Hit.
Wildcard and Free Hit checks are not built yet; this module says so on the card
rather than silently skipping them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .squad import SquadPlan

BENCH_BOOST_THRESHOLD = 14.5   # owner's rule: projected total of the 4 bench players
# Safety floor (added 2026-11-05, pending owner approval): Triple Captain needs at least this projection.
TRIPLE_CAPTAIN_MIN_XP = 8.0


@dataclass
class ChipDecision:
    chip: str | None                  # "bboost", "3xc", "wildcard", "freehit" or None
    lines: list[str] = field(default_factory=list)


def decide(plan: SquadPlan, chips_available: set[str], first_gameweek: bool,
           best_later_captain: tuple[float, int] | None = None) -> ChipDecision:
    """`best_later_captain`: (xP, gameweek) of the best captain score among the squad for the rest of
    the Triple Captain chip window after this week. Without it, the planning horizon is used instead."""
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
        if best_later_captain is not None:
            best_later, best_gw = best_later_captain
            span = f"the rest of the chip window (best: GW{best_gw})"
        else:
            best_later = max((max(p.xp_by_gw[g] for p in plan.squad) for g in plan.gws[1:]), default=0.0)
            span = f"the rest of the {len(plan.gws)}-week horizon"
        xp = cap.xp_by_gw[g0]
        ok = xp >= best_later and xp >= TRIPLE_CAPTAIN_MIN_XP
        verdict = "qualifies" if ok else "hold"
        if ok and chip:
            verdict = "qualifies, but only one chip per gameweek and Bench Boost comes first"
        why = "" if ok or xp >= TRIPLE_CAPTAIN_MIN_XP else f" (below the {TRIPLE_CAPTAIN_MIN_XP:.0f}-point floor)"
        lines.append(f"Triple Captain: {cap.name} projects {xp:.2f} this week; best captain score in "
                     f"{span} is {best_later:.2f} -> {verdict}{why}.")
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
