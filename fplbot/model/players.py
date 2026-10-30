"""Per-player profiles: how much a player plays and what he produces per 90 minutes.

Recent matches count more. Every rate is shrunk toward the position average,
so a player with a few good minutes isn't projected like a regular.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..datastore import PlayerMatch
from ..scoring import DC_THRESHOLD

MINUTES_HALF_LIFE = 4.0      # team fixtures
RATE_HALF_LIFE = 15.0        # appearances
LAST_SEASON_WEIGHT = 0.6     # last season's matches count this much less, on top of decay
SHRINK_90S = 5.0             # rates act as if 5 extra 90s of position-average play were added
MIN_MATCHES_FOR_MINUTES = 3
# Players with little history are pulled toward a cautious squad-player default,
# as if they had this many extra team fixtures at these values. The pull fades
# to nothing once a player has MINUTES_PRIOR_FADE team fixtures.
MINUTES_PRIOR_MATCHES = 1.0
MINUTES_PRIOR_FADE = 5
MINUTES_PRIOR = {"p_play": 0.3, "p60": 0.2}
# Rates for little-known players shrink toward this share of the regulars' average.
RATE_PRIOR_SCALE = 0.8

RATE_KEYS = ("xg", "xa", "saves", "bonus", "yellow")


@dataclass
class Profile:
    code: int
    position: str
    p_play: float = 0.0          # chance of any minutes in a team fixture
    p60: float = 0.0             # chance of 60+ minutes
    mins_if_play: float = 0.0
    mins_if_60: float = 85.0
    rates: dict[str, float] = field(default_factory=dict)  # per 90
    dc_hit: float = 0.0          # chance of reaching the defensive-contribution threshold in a 60+ appearance
    n_matches: int = 0           # team fixtures seen
    nineties: float = 0.0        # weighted 90s played (data behind the rates)
    notes: list[str] = field(default_factory=list)


def _weighted(rows: list[PlayerMatch], half_life: float, current_season: str) -> list[tuple[float, PlayerMatch]]:
    """Newest first, with decay weights; last season's rows also get LAST_SEASON_WEIGHT."""
    out = []
    for i, r in enumerate(reversed(rows)):
        w = 0.5 ** (i / half_life)
        if r.season != current_season:
            w *= LAST_SEASON_WEIGHT
        out.append((w, r))
    return out


def position_priors(rows: list[PlayerMatch]) -> dict[str, dict[str, float]]:
    """League-average per-90 rates by position, over appearances of 60+ minutes."""
    acc: dict[str, dict[str, float]] = {}
    for r in rows:
        if r.minutes < 60:
            continue
        a = acc.setdefault(r.position, {k: 0.0 for k in RATE_KEYS} | {"mins": 0.0, "dc_n": 0.0, "dc_hit": 0.0})
        a["mins"] += r.minutes
        a["xg"] += r.xg or 0.0
        a["xa"] += r.xa or 0.0
        a["saves"] += r.saves
        a["bonus"] += r.bonus
        a["yellow"] += r.yellow
        thr = DC_THRESHOLD.get(r.position)
        if thr is not None and r.dc is not None:
            a["dc_n"] += 1
            a["dc_hit"] += 1 if r.dc >= thr else 0
    priors = {}
    for pos, a in acc.items():
        n90 = a["mins"] / 90 or 1
        priors[pos] = {k: a[k] / n90 for k in RATE_KEYS}
        priors[pos]["dc_hit"] = a["dc_hit"] / a["dc_n"] if a["dc_n"] else {"DEF": 0.25, "MID": 0.15, "FWD": 0.05}.get(pos, 0.0)
    return priors


def build_profile(code: int, position: str, rows: list[PlayerMatch], current_season: str,
                  priors: dict[str, dict[str, float]]) -> Profile:
    """`rows`: the player's team fixtures in time order (current and last season), oldest first."""
    prof = Profile(code=code, position=position)
    prior = priors.get(position, {k: 0.0 for k in RATE_KEYS} | {"dc_hit": 0.0})
    prof.n_matches = len(rows)

    # Minutes: mostly this season; fall back to last season when there's little this season.
    cur = [r for r in rows if r.season == current_season]
    mins_rows = cur if len(cur) >= MIN_MATCHES_FOR_MINUTES else rows
    if mins_rows:
        wr = _weighted(mins_rows[-15:], MINUTES_HALF_LIFE, current_season)
        wsum = sum(w for w, _ in wr)
        played = [(w, r) for w, r in wr if r.minutes > 0]
        full = [(w, r) for w, r in wr if r.minutes >= 60]
        k = MINUTES_PRIOR_MATCHES * max(0.0, 1 - len(mins_rows) / MINUTES_PRIOR_FADE)
        prof.p_play = (sum(w for w, _ in played) + k * MINUTES_PRIOR["p_play"]) / (wsum + k)
        prof.p60 = (sum(w for w, _ in full) + k * MINUTES_PRIOR["p60"]) / (wsum + k)
        if played:
            prof.mins_if_play = sum(w * r.minutes for w, r in played) / sum(w for w, _ in played)
        if full:
            prof.mins_if_60 = sum(w * r.minutes for w, r in full) / sum(w for w, _ in full)
    else:
        prof.notes.append("no match history: minutes unknown")

    # Rates per 90 from appearances, shrunk toward the position average.
    apps = [r for r in rows if r.minutes > 0]
    wa = _weighted(apps, RATE_HALF_LIFE, current_season)
    w90 = sum(w * r.minutes for w, r in wa) / 90
    prof.nineties = w90
    for k in RATE_KEYS:
        total = sum(w * (getattr(r, k) or 0.0) for w, r in wa)
        prof.rates[k] = (total + SHRINK_90S * RATE_PRIOR_SCALE * prior.get(k, 0.0)) / (w90 + SHRINK_90S)

    thr = DC_THRESHOLD.get(position)
    if thr is not None:
        dc_apps = [(w, r) for w, r in wa if r.minutes >= 60 and r.dc is not None]
        n = sum(w for w, _ in dc_apps)
        hits = sum(w for w, r in dc_apps if r.dc >= thr)
        k = 4.0
        prof.dc_hit = (hits + k * prior.get("dc_hit", 0.0)) / (n + k)
    return prof
