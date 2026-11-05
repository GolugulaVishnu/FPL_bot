"""Squad and lineup rules (rules file A1, A2), read from the live API with the 2026/27 baseline as fallback."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..scoring import ELEMENT_TYPE_TO_POS


@dataclass(frozen=True)
class SquadRules:
    budget: int                      # tenths of £1m
    club_limit: int
    squad_size: int
    starters: int
    squad_count: dict[str, int]      # GKP 2, DEF 5, MID 5, FWD 3
    xi_min: dict[str, int]
    xi_max: dict[str, int]
    transfer_cap: int = 20           # max transfers in a gameweek without Wildcard/Free Hit
    max_free_transfers: int = 5      # 1 + max_extra_free_transfers


DEFAULT = SquadRules(1000, 3, 15, 11, {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3},
                     {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}, {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3})


def from_bootstrap(bootstrap: dict) -> SquadRules:
    gs = bootstrap.get("game_settings") or {}
    ets = bootstrap.get("element_types") or []
    if not ets:
        return DEFAULT
    pos = {et["id"]: ELEMENT_TYPE_TO_POS[et["id"]] for et in ets}
    return SquadRules(
        budget=gs.get("squad_total_spend", DEFAULT.budget),
        club_limit=gs.get("squad_team_limit", DEFAULT.club_limit),
        squad_size=gs.get("squad_squadsize", DEFAULT.squad_size),
        starters=gs.get("squad_squadplay", DEFAULT.starters),
        squad_count={pos[e["id"]]: e["squad_select"] for e in ets},
        xi_min={pos[e["id"]]: e["squad_min_play"] for e in ets},
        xi_max={pos[e["id"]]: e["squad_max_play"] for e in ets},
        transfer_cap=gs.get("transfers_cap", DEFAULT.transfer_cap),
        max_free_transfers=1 + gs.get("max_extra_free_transfers", DEFAULT.max_free_transfers - 1),
    )


def validate(rules: SquadRules, squad: list[dict], xi: list[int], bench: list[int],
             captain: int, vice: int, budget: int | None = None) -> list[str]:
    """Return rule breaches (empty when valid). `squad` items need element, position, team, price."""
    errors = []
    by_id = {p["element"]: p for p in squad}
    if len(squad) != rules.squad_size or len(by_id) != len(squad):
        errors.append(f"squad must be {rules.squad_size} different players, got {len(by_id)}")
    pos = Counter(p["position"] for p in squad)
    for k, n in rules.squad_count.items():
        if pos.get(k, 0) != n:
            errors.append(f"squad needs {n} {k}, has {pos.get(k, 0)}")
    for team, n in Counter(p["team"] for p in squad).items():
        if n > rules.club_limit:
            errors.append(f"{n} players from {team} (max {rules.club_limit})")
    cost = sum(p["price"] for p in squad)
    limit = rules.budget if budget is None else budget
    if cost > limit:
        errors.append(f"squad costs {cost / 10:.1f}m, budget {limit / 10:.1f}m")
    if len(xi) != rules.starters or len(set(xi)) != len(xi) or any(e not in by_id for e in xi):
        errors.append(f"starting XI must be {rules.starters} squad players")
    else:
        xpos = Counter(by_id[e]["position"] for e in xi)
        for k in rules.xi_min:
            if not rules.xi_min[k] <= xpos.get(k, 0) <= rules.xi_max[k]:
                errors.append(f"XI has {xpos.get(k, 0)} {k} (allowed {rules.xi_min[k]}-{rules.xi_max[k]})")
    if sorted(xi + bench) != sorted(by_id):
        errors.append("XI plus bench must be the whole squad")
    elif by_id[bench[0]]["position"] != "GKP":
        errors.append("first bench slot (12) must be the reserve goalkeeper")
    if captain not in xi or vice not in xi or captain == vice:
        errors.append("captain and vice-captain must be two different starters")
    return errors
