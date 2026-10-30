"""Turn FPL's status, chance-of-playing and news text into a playing probability per gameweek.

Rules file B6: status a (available), d (doubtful 25/50/75), i (injured),
s (suspended), u (unavailable: left or loaned out), n (not eligible).
FPL news usually says "Expected back 08 Nov" or "Suspended until 08 Nov".
"""
from __future__ import annotations

import re
from datetime import date, datetime

_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun",
                                       "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_RETURN = re.compile(r"(?:expected back|until)\s+(\d{1,2})\s+([A-Za-z]{3})", re.IGNORECASE)


def return_date(news: str | None, today: date) -> date | None:
    """Parse 'Expected back 08 Nov' / 'until 08 Nov' into a date on or after today."""
    if not news:
        return None
    m = _RETURN.search(news)
    if not m:
        return None
    month = _MONTHS.get(m.group(2).lower())
    if not month:
        return None
    day = int(m.group(1))
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= today or (today - d).days < 30:
            return d
    return None


def factor(status: str | None, chance_next: int | None, news: str | None,
           gw_start: datetime, gws_ahead: int, now: datetime) -> tuple[float, str | None]:
    """Multiplier on a player's normal playing chance for one gameweek, plus a reason if not 1.

    `gws_ahead`: 0 for the next gameweek, 1 for the one after, and so on.
    """
    status = (status or "a").lower()
    if status == "a":
        return 1.0, None
    if status == "u":
        return 0.0, "unavailable (left club or on loan)"
    if status == "n":
        return (0.0, "not eligible this gameweek") if gws_ahead == 0 else (1.0, None)

    back = return_date(news, now.date())
    if back is not None:
        if gw_start.date() >= back:
            return 1.0, None
        return 0.0, f"out until {back.isoformat()}"

    if status == "d":
        c = (chance_next if chance_next is not None else 50) / 100
        return min(1.0, c + 0.25 * gws_ahead), f"doubtful ({int(c * 100)}%)"
    if status == "s":
        return (0.0, "suspended") if gws_ahead == 0 else (1.0, None)
    if status == "i":
        c = (chance_next or 0) / 100
        ramp = [c, max(c, 0.25), max(c, 0.5), max(c, 0.75)]
        f = ramp[gws_ahead] if gws_ahead < len(ramp) else 1.0
        return f, f"injured, no return date ({int(f * 100)}% chance assumed)"
    return 1.0, None
