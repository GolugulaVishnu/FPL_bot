"""The owner's team as it stands: squad, bank, free transfers, chips used and selling prices.

Read from FPL's public team pages (no sign-in needed). Purchase prices are not
public, so the bot keeps its own record of what it paid in `team/purchases.json`
(started from the prices recorded when the team was created, 30 Oct 2026).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .fpl_api import FplPublicClient

PURCHASES_FILE = Path("team") / "purchases.json"
# Prices paid when the team was created (recordings/fpl-session-20261030-204153.json, entry-create).
INITIAL_PURCHASES = {1: 62, 385: 50, 115: 53, 4: 79, 566: 50, 60: 55, 112: 49, 427: 79, 68: 64, 542: 57,
                     183: 49, 15: 67, 411: 158, 346: 61, 249: 56}
CHIP_HALVES = ((1, 19), (20, 38))


def selling_price(bought: int, now: int) -> int:
    """Rules file A6/B2: a fall is passed on in full; a rise is halved, rounded down (tenths of £1m)."""
    return now if now <= bought else bought + (now - bought) // 2


@dataclass
class TeamState:
    entry: int
    last_gw: int
    picks: list[dict]                 # element, position, is_captain, is_vice_captain
    bank: int
    free_transfers: int
    chips_used: list[tuple[str, int]]  # (chip name, gameweek)
    purchases: dict[int, int]
    notes: list[str] = field(default_factory=list)

    def selling_prices(self, now_cost: dict[int, int]) -> dict[int, int]:
        out = {}
        for p in self.picks:
            e = p["element"]
            now = now_cost[e]
            if e not in self.purchases:
                self.notes.append(f"purchase price of player {e} unknown; assumed today's price")
            out[e] = selling_price(self.purchases.get(e, now), now)
        return out

    def chips_available(self, chips: list[dict], gw: int) -> set[str]:
        """Chips whose window includes `gw` and that were not already played in that half of the season."""
        out = set()
        for c in chips:
            lo, hi = c.get("start_event", 1), c.get("stop_event", 38)
            if not lo <= gw <= hi:
                continue
            if any(name == c["name"] and lo <= ev <= hi for name, ev in self.chips_used):
                continue
            out.add(c["name"])
        return out


def free_transfers(history: list[dict], chips_used: list[tuple[str, int]], max_ft: int = 5) -> int:
    """Free transfers for the gameweek after the last one in `history` (rules file A5, B3).

    The team's first gameweek has unlimited transfers, so it ends with 1 free transfer.
    After that: unused ones carry over (max `max_ft`), each transfer uses one, and a
    Wildcard or Free Hit week keeps the count unchanged.
    """
    rows = sorted(history, key=lambda r: r["event"])
    if not rows:
        return 0
    ft = 1
    chip_weeks = {ev for name, ev in chips_used if name in ("wildcard", "freehit")}
    for r in rows[1:]:
        if r["event"] in chip_weeks:
            continue
        ft = min(max_ft, max(0, ft - r.get("event_transfers", 0)) + 1)
    return ft


def load_purchases(repo: Path) -> dict[int, int]:
    f = repo / PURCHASES_FILE
    if f.exists():
        return {int(k): v for k, v in json.loads(f.read_text(encoding="utf-8")).items()}
    return dict(INITIAL_PURCHASES)


def save_purchases(repo: Path, purchases: dict[int, int]) -> Path:
    f = repo / PURCHASES_FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({str(k): v for k, v in sorted(purchases.items())}, indent=1) + "\n", encoding="utf-8")
    return f


def fetch(client: FplPublicClient, entry: int, repo: Path, max_ft: int = 5) -> TeamState | None:
    """The team after its latest gameweek, or None if it has not played one yet."""
    hist = client.get(f"entry/{entry}/history/", max_age=1800)
    rows = hist.get("current", [])
    if not rows:
        return None
    last = max(r["event"] for r in rows)
    picks = client.get(f"entry/{entry}/event/{last}/picks/", max_age=1800)
    chips_used = [(c["name"], c["event"]) for c in hist.get("chips", [])]
    bank = (picks.get("entry_history") or {}).get("bank", rows[-1].get("bank", 0))
    return TeamState(entry=entry, last_gw=last, picks=picks.get("picks", []), bank=bank,
                     free_transfers=free_transfers(rows, chips_used, max_ft), chips_used=chips_used,
                     purchases=load_purchases(repo))
