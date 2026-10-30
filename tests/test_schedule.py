from datetime import datetime, timezone

import pytest

from fplbot.schedule import due_jobs, parse_events

from .conftest import make_bootstrap

EVENTS = parse_events(make_bootstrap([
    (8, "2026-10-23T17:30:00Z", True, True),
    (9, "2026-10-31T11:00:00Z", False, False),
    (10, "2026-11-06T18:30:00Z", False, False),
]))
DONE_TODAY = {"post_gw_done_event": 8}


def utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_daily_runs_once_after_0030_utc():
    assert "daily" not in due_jobs(utc("2026-10-29T00:10"), EVENTS, DONE_TODAY)
    assert "daily" in due_jobs(utc("2026-10-29T00:31"), EVENTS, DONE_TODAY)
    assert "daily" not in due_jobs(utc("2026-10-29T08:00"), EVENTS, {**DONE_TODAY, "daily_done_date": "2026-10-29"})


def test_plan_window_is_24h_to_2h_before_deadline():
    st = {**DONE_TODAY, "daily_done_date": "2026-10-30"}
    assert "plan" not in due_jobs(utc("2026-10-30T10:59"), EVENTS, st)
    assert due_jobs(utc("2026-10-30T11:00"), EVENTS, st) == ["plan"]
    assert "plan" not in due_jobs(utc("2026-10-30T12:00"), EVENTS, {**st, "plan_done_event": 9})


def test_final_window_is_2h_to_90min_before_deadline():
    st = {**DONE_TODAY, "daily_done_date": "2026-10-31", "plan_done_event": 9}
    assert due_jobs(utc("2026-10-31T08:59"), EVENTS, st) == []
    assert due_jobs(utc("2026-10-31T09:00"), EVENTS, st) == ["final"]
    assert due_jobs(utc("2026-10-31T09:30"), EVENTS, st) == ["final"]
    assert due_jobs(utc("2026-10-31T09:31"), EVENTS, st) == []
    assert due_jobs(utc("2026-10-31T09:15"), EVENTS, {**st, "final_done_event": 9}) == []


def test_post_gw_once_per_checked_event():
    st = {"daily_done_date": "2026-10-29"}
    assert due_jobs(utc("2026-10-29T12:00"), EVENTS, st) == ["post_gw"]
    assert due_jobs(utc("2026-10-29T12:00"), EVENTS, {**st, "post_gw_done_event": 8}) == []


def test_rules_check_tuesday_0900_uk_in_both_gmt_and_bst():
    st = {**DONE_TODAY, "daily_done_date": "2026-11-03"}
    # 3 Nov 2026 is a Tuesday in GMT: 09:00 UK = 09:00 UTC
    assert "rules_check" not in due_jobs(utc("2026-11-03T08:59"), EVENTS, st)
    assert "rules_check" in due_jobs(utc("2026-11-03T09:00"), EVENTS, st)
    # 20 Oct 2026 is a Tuesday in BST: 09:00 UK = 08:00 UTC
    st2 = {**DONE_TODAY, "daily_done_date": "2026-10-20"}
    assert "rules_check" in due_jobs(utc("2026-10-20T08:00"), EVENTS, st2)
    assert "rules_check" not in due_jobs(utc("2026-10-20T10:00"), EVENTS, {**st2, "rules_check_done_date": "2026-10-20"})


def test_naive_time_rejected():
    with pytest.raises(ValueError):
        due_jobs(datetime(2026, 10, 29), EVENTS, {})
