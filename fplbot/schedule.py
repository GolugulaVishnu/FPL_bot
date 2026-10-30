"""Which jobs are due right now. Pure functions, driven by the live FPL deadlines.

Timings come from docs/system-flow.md:
- daily refresh: once a day after the 00:00 UTC price update
- weekly plan: from deadline minus 24h
- final run: from deadline minus 2h until deadline minus 90 min
- post-gameweek review: once the gameweek is finished and data-checked
- rules-change check: Tuesdays from 09:00 UK time
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")

DAILY_AFTER = timedelta(minutes=30)        # leave room after the 00:00 UTC price update
PLAN_FROM = timedelta(hours=24)
FINAL_FROM = timedelta(hours=2)
FINAL_UNTIL = timedelta(minutes=90)
RULES_CHECK_WEEKDAY = 1                    # Tuesday
RULES_CHECK_HOUR_UK = 9

JOB_ORDER = ("rules_check", "daily", "post_gw", "plan", "final")


@dataclass(frozen=True)
class Event:
    id: int
    deadline: datetime
    finished: bool
    data_checked: bool


def parse_events(bootstrap: dict) -> list[Event]:
    events = []
    for e in bootstrap.get("events", []):
        events.append(Event(
            id=int(e["id"]),
            deadline=datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")),
            finished=bool(e.get("finished")),
            data_checked=bool(e.get("data_checked")),
        ))
    return sorted(events, key=lambda e: e.deadline)


def next_event(events: list[Event], now: datetime) -> Event | None:
    return next((e for e in events if e.deadline > now), None)


def latest_checked_event(events: list[Event]) -> Event | None:
    done = [e for e in events if e.finished and e.data_checked]
    return done[-1] if done else None


def due_jobs(now: datetime, events: list[Event], state: dict) -> list[str]:
    """Return the jobs to run now, in run order.

    `state` holds what has already been done:
      daily_done_date (YYYY-MM-DD, UTC), plan_done_event, final_done_event,
      post_gw_done_event, rules_check_done_date (YYYY-MM-DD, UK).
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    due: set[str] = set()

    today = now.date().isoformat()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if state.get("daily_done_date") != today and now >= midnight + DAILY_AFTER:
        due.add("daily")

    ev = next_event(events, now)
    if ev is not None:
        if ev.deadline - PLAN_FROM <= now < ev.deadline - FINAL_FROM and state.get("plan_done_event") != ev.id:
            due.add("plan")
        if ev.deadline - FINAL_FROM <= now <= ev.deadline - FINAL_UNTIL and state.get("final_done_event") != ev.id:
            due.add("final")

    checked = latest_checked_event(events)
    if checked is not None and state.get("post_gw_done_event") != checked.id:
        due.add("post_gw")

    uk_now = now.astimezone(UK)
    if (uk_now.weekday() == RULES_CHECK_WEEKDAY and uk_now.hour >= RULES_CHECK_HOUR_UK
            and state.get("rules_check_done_date") != uk_now.date().isoformat()):
        due.add("rules_check")

    return [j for j in JOB_ORDER if j in due]
