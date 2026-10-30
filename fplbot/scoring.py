"""The points table (rules file A9), normalised to per-position values.

Values are read from the live API's game_config.scoring when available; the
defaults are the 2026/27 baseline (rules file D6). Thresholds that are not in
the API (60 minutes, 3 saves, 2 goals conceded, defensive contribution counts)
come from the rules page.
"""
from __future__ import annotations

POSITIONS = ("GKP", "DEF", "MID", "FWD")
ELEMENT_TYPE_TO_POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

DEFAULT_SCORING = {
    "short_play": 1, "long_play": 2,
    "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
    "assists": 3,
    "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
    "saves": {"GKP": 1, "DEF": 0, "MID": 0, "FWD": 0},
    "penalties_saved": 5, "penalties_missed": -2,
    "yellow_cards": -1, "red_cards": -3, "own_goals": -2,
    "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
    "bonus": 1,
}

LONG_PLAY_MINUTES = 60
SAVES_PER_POINT = 3
GOALS_CONCEDED_PER_DEDUCTION = 2
# Defensive contribution count needed for the 2 points (DEF: CBIT, MID/FWD: CBIRT, GK: none).
DC_THRESHOLD = {"GKP": None, "DEF": 10, "MID": 12, "FWD": 12}


def normalise(scoring: dict | None) -> dict[str, dict[str, float]]:
    """Return {key: {GKP, DEF, MID, FWD: points}} from an API scoring block (or the defaults)."""
    src = dict(DEFAULT_SCORING)
    if scoring:
        src.update({k: v for k, v in scoring.items() if k in DEFAULT_SCORING})
    out = {}
    for key, val in src.items():
        out[key] = {p: float(val[p]) for p in POSITIONS} if isinstance(val, dict) else {p: float(val) for p in POSITIONS}
    return out
