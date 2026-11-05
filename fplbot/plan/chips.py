"""Chip decision for a gameweek (system-flow.md, section 5). One chip at most.

Order of checks when more than one qualifies: Bench Boost, Triple Captain, Wildcard, Free Hit.
Wildcard and Free Hit checks are not built yet; this module says so on the card
rather than silently skipping them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .squad import SquadPlan

BENCH_BOOST_THRESHOLD = 14.5   # owner's rule: projected total of the 4 bench players
# Owner's rule (2026-11-05): play Triple Captain at 8+ projected points, judging the rest of the chip
# window (to GW19) including players who could be transferred in. A later week only justifies holding
# the chip if it is clearly better, by more than TRIPLE_CAPTAIN_MARGIN points.
TRIPLE_CAPTAIN_MIN_XP = 8.0
TRIPLE_CAPTAIN_MARGIN = 1.0


@dataclass
class ChipDecision:
    chip: str | None                  # "bboost", "3xc", "wildcard", "freehit" or None
    lines: list[str] = field(default_factory=list)


def decide(plan: SquadPlan, chips_available: set[str], first_gameweek: bool,
           best_later_captain: tuple | None = None) -> ChipDecision:
    """`best_later_captain`: (xP, gameweek[, player]) of the best captain score for the rest of the
    Triple Captain chip window, over owned players and affordable transfer targets. Without it, the
    planning horizon over the squad is used instead."""
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
            best_later, best_gw = best_later_captain[0], best_later_captain[1]
            who = f" {best_later_captain[2]}" if len(best_later_captain) > 2 else ""
            span = f"the rest of the chip window, owned or affordable players (best:{who} GW{best_gw})"
        else:
            best_later = max((max(p.xp_by_gw[g] for p in plan.squad) for g in plan.gws[1:]), default=0.0)
            span = f"the rest of the {len(plan.gws)}-week horizon"
        xp = cap.xp_by_gw[g0]
        ok = xp >= TRIPLE_CAPTAIN_MIN_XP and xp >= best_later - TRIPLE_CAPTAIN_MARGIN
        verdict = "qualifies" if ok else "hold"
        if not ok and xp >= TRIPLE_CAPTAIN_MIN_XP:
            verdict = f"hold (a later week is more than {TRIPLE_CAPTAIN_MARGIN:.0f} point better)"
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
