"""Decision cards: plain-text records of every decision and why, committed to the repo.

They exist so a human can review the reasoning afterwards and fix biases in the
code (system-flow.md, section 4). They never contain credentials.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..model.project import PlayerProjection
from .chips import ChipDecision
from .reasons import club_lines, player_reasons, squad_story
from .squad import SquadPlan

CHIP_NAMES = {"bboost": "Bench Boost", "3xc": "Triple Captain", "wildcard": "Wildcard", "freehit": "Free Hit", None: "none"}
PART_LABELS = [("appearance", "app"), ("goals", "gls"), ("assists", "ast"), ("clean_sheet", "cs"),
               ("goals_conceded", "gc"), ("saves", "sav"), ("defensive_contribution", "dc"),
               ("bonus", "bon"), ("cards", "crd")]


def card_path(repo: Path, season: str, gw: int, kind: str) -> Path:
    return repo / "decision-cards" / season / f"gw{gw:02d}-{kind}.txt"


def _parts(p: PlayerProjection) -> str:
    return " ".join(f"{lab} {p.parts_next[k]:+.2f}" for k, lab in PART_LABELS if abs(p.parts_next.get(k, 0)) >= 0.05)


def _row(p: PlayerProjection, g0: int, opp: str, tag: str = "") -> str:
    return (f"  {p.position:<4}{(p.name + tag)[:20]:<21}{p.team:<5}{p.price / 10:>5.1f}  {opp:<12}"
            f"{p.xp_by_gw[g0]:>6.2f}{p.total:>7.1f}{p.minutes_next:>6.0f}  {_parts(p)}")


def render(*, season: str, gw: int, kind: str, deadline: datetime, now: datetime, plan: SquadPlan,
           chip: ChipDecision, all_projs: list[PlayerProjection], opponents: dict[int, str],
           budget: int, mode: str, model_version: str, data_note: str, team_name: str | None,
           extra_notes: list[str] | None = None, ctx=None) -> str:
    g0 = plan.gws[0]
    horizon = f"GW{plan.gws[0]}-{plan.gws[-1]}"
    cap_mult = 3 if chip.chip == "3xc" else 2
    xi_pts = sum(p.xp_by_gw[g0] for p in plan.xi) + (cap_mult - 1) * plan.captain.xp_by_gw[g0]
    if chip.chip == "bboost":
        xi_pts += sum(p.xp_by_gw[g0] for p in plan.bench)

    L = []
    L.append(f"FPL BOT DECISION CARD | {season} GW{gw} | {kind.upper()}")
    L.append("=" * 78)
    L.append(f"Generated:  {now.strftime('%Y-%m-%d %H:%M UTC')}  (model {model_version})")
    L.append(f"Deadline:   {deadline.strftime('%a %d %b %Y %H:%M UTC')}  (from the FPL API)")
    L.append(f"Mode:       {mode}")
    L.append(f"Data:       {data_note}")
    if team_name:
        L.append(f"Team name:  {team_name}")
    L.append("")
    L.append("SUMMARY")
    L.append(f"  Squad cost {plan.cost / 10:.1f}m of {budget / 10:.1f}m, bank {(budget - plan.cost) / 10:.1f}m")
    L.append(f"  Captain {plan.captain.name} ({plan.captain.team}), vice {plan.vice.name} ({plan.vice.team})")
    L.append(f"  Chip: {CHIP_NAMES[chip.chip]}")
    L.append(f"  Projected points GW{g0}: {xi_pts:.1f} (incl. captain{' and bench' if chip.chip == 'bboost' else ''})")
    L.append(f"  Planning horizon {horizon}, later weeks weighted less (x0.85 per week)")
    L.append("")
    L.append("HOW THE SQUAD WAS BUILT")
    L.extend(squad_story(plan, all_projs, budget))
    L.append("")
    head = f"  {'Pos':<4}{'Player':<21}{'Team':<5}{'£m':>5}  {'GW' + str(g0) + ' opp':<12}{'xP':>6}{'xP' + str(len(plan.gws)) + 'w':>7}{'mins':>6}  breakdown"
    L.append("STARTING XI")
    L.append(head)
    for p in plan.xi:
        tag = " (C)" if p is plan.captain else " (V)" if p is plan.vice else ""
        L.append(_row(p, g0, opponents.get(p.element, "-"), tag))
    L.append("")
    L.append("BENCH (substitution order; slot 12 is always the reserve goalkeeper)")
    L.append(head)
    for i, p in enumerate(plan.bench, start=12):
        L.append(_row(p, g0, opponents.get(p.element, "-"), f" [{i}]"))
    L.append("  Order rule: likeliest to play first, then expected points (rules file C2).")
    L.append("")

    L.append("CAPTAINCY")
    ranked = sorted(plan.xi, key=lambda p: p.xp_by_gw[g0], reverse=True)
    for p in ranked[:4]:
        mark = "captain" if p is plan.captain else "vice" if p is plan.vice else "alternative"
        L.append(f"  {p.name:<20}{p.xp_by_gw[g0]:>6.2f} xP, {p.minutes_next:.0f} expected mins  -> {mark}")
    L.append("  Rule: captain = highest xP in the XI; vice = next highest starter expected to play 60+ minutes.")
    L.append("")

    L.append("CHIPS")
    for line in chip.lines:
        L.append(f"  {line}")
    L.append("")

    L.append("CLUBS IN THE SQUAD")
    L.extend(club_lines(plan, ctx))
    L.append("")

    L.append("WHY EACH PLAYER")
    L.extend(player_reasons(plan, all_projs))

    L.append(f"BEST PLAYERS LEFT OUT (by weighted xP over {horizon})")
    in_squad = {p.element for p in plan.squad}
    for pos in ("GKP", "DEF", "MID", "FWD"):
        out = sorted((p for p in all_projs if p.position == pos and p.element not in in_squad),
                     key=lambda p: p.total, reverse=True)[:3]
        L.append(f"  {pos}: " + "; ".join(f"{p.name} {p.team} {p.price / 10:.1f}m {p.total:.1f}" for p in out))
    L.append("  These lost on price per point, the 3-per-club limit, or fit with the rest of the squad.")
    L.append("")

    L.append("ASSUMPTIONS AND CONFIDENCE")
    flagged = [p for p in plan.squad if p.notes]
    if flagged:
        for p in flagged:
            L.append(f"  {p.name}: {'; '.join(p.notes)}")
    else:
        L.append("  No squad player carries an injury, suspension or doubt flag.")
    thin = [p for p in plan.squad if p.minutes_next < 60]
    if thin:
        L.append("  Lower minutes certainty: " + ", ".join(f"{p.name} ({p.minutes_next:.0f})" for p in thin))
    L.append("  Model: xG-based team strength, recent minutes, per-90 rates shrunk toward position averages.")
    L.append("  Backtest 2025-26: beats recent form (captain 6.2 vs 4.1 pts/GW); FPL's own projection was")
    L.append("  better on the 10 gameweeks where it could be compared (reports/backtest-2025-26.txt).")
    for n in extra_notes or []:
        L.append(f"  {n}")
    L.append("")
    return "\n".join(L) + "\n"
