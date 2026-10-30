"""One scheduled run: the OS starts this every 15 minutes (system-flow.md, section 2)."""
from __future__ import annotations

import logging
import socket
from datetime import datetime, timezone
from typing import Callable

from . import control, paths
from .config import Config
from .fpl_api import FplBlocked, FplError, FplPublicClient
from .notify import Ntfy
from .schedule import UK, due_jobs, latest_checked_event, next_event, parse_events
from .store import Store

log = logging.getLogger("fplbot.tick")

TAKEOVER_ALERT_EVERY_S = 3600


def _not_built(job: str) -> Callable[..., str]:
    def handler(ctx: dict) -> str:
        return f"{job}: not built yet, skipped"
    return handler


def _daily(ctx: dict) -> str:
    client: FplPublicClient = ctx["client"]
    client.bootstrap(max_age=0)
    client.fixtures(max_age=0)
    return "daily: FPL data refreshed"


# Jobs are filled in as each stage of the bot is built.
HANDLERS: dict[str, Callable[[dict], str]] = {
    "daily": _daily,
    "plan": _not_built("plan"),
    "final": _not_built("final"),
    "post_gw": _not_built("post_gw"),
    "rules_check": _not_built("rules_check"),
}

# Which state key marks each job done, and what value to store.
_DONE = {
    "daily": ("daily_done_date", lambda now, ev, chk: now.date().isoformat()),
    "plan": ("plan_done_event", lambda now, ev, chk: ev.id),
    "final": ("final_done_event", lambda now, ev, chk: ev.id),
    "post_gw": ("post_gw_done_event", lambda now, ev, chk: chk.id),
    "rules_check": ("rules_check_done_date", lambda now, ev, chk: now.astimezone(UK).date().isoformat()),
}


def run(cfg: Config, now: datetime | None = None, ntfy: Ntfy | None = None,
        client: FplPublicClient | None = None, store: Store | None = None) -> str:
    """Run one tick. Returns a short status string (also logged)."""
    now = now or datetime.now(timezone.utc)
    machine = f"{cfg.role}:{socket.gethostname()}"
    ntfy = ntfy or Ntfy(cfg.ntfy_server)
    store = store or Store(paths.db_path())
    client = client or FplPublicClient(paths.cache_dir())

    try:
        with control.RunLock(paths.data_dir() / "tick.lock"):
            return _run_locked(cfg, now, machine, ntfy, client, store)
    except control.LockBusy:
        return "skipped: another run in progress"


def _run_locked(cfg, now, machine, ntfy, client, store) -> str:
    state = store.get_state()

    # 1. Heartbeat (primary) or failover check (backup).
    if cfg.role == "primary":
        ntfy.send(cfg.topic_heartbeat, f"alive {now.isoformat(timespec='minutes')}", priority="min")
    else:
        try:
            beats = ntfy.poll(cfg.topic_heartbeat, since=control.HEARTBEAT_WINDOW)
        except Exception:
            beats = None
        if not control.backup_should_run(beats):
            return "standby: primary is alive (or heartbeat unreadable)"
        last_alert = state.get("takeover_alert_ts", 0)
        if now.timestamp() - last_alert > TAKEOVER_ALERT_EVERY_S:
            ntfy.send(cfg.topic_alerts, "No heartbeat from the Windows machine for 30 min. The Mac is taking over.",
                      title="FPL bot: backup taking over", priority="high", tags=["warning"])
            store.set_state("takeover_alert_ts", now.timestamp())

    # 2. Kill switch: apply pause/resume messages, then honour the flag.
    try:
        msgs = ntfy.poll(cfg.topic_control, since="12h")
        newest = control.apply_control_messages(msgs, paths.pause_flag(), state.get("control_last_id"))
        if newest != state.get("control_last_id"):
            store.set_state("control_last_id", newest)
    except Exception as e:
        log.warning("could not read control topic: %s", type(e).__name__)
    if control.is_paused(paths.pause_flag()):
        if not state.get("pause_alerted"):
            ntfy.send(cfg.topic_alerts, "Paused. Send 'resume' to the control topic, or run: fplbot resume",
                      title="FPL bot paused", tags=["pause_button"])
            store.set_state("pause_alerted", True)
        store.log_run(machine, "tick", "paused")
        return "paused"
    if state.get("pause_alerted"):
        store.set_state("pause_alerted", False)

    # 3. Deadlines from the live API (cached up to 6h), then due jobs.
    try:
        events = parse_events(client.bootstrap())
    except FplBlocked as e:
        _alert_once(ntfy, cfg, store, state, "blocked", f"{e}. The bot will not work around this. Check the machine's network.")
        store.log_run(machine, "tick", "blocked", str(e))
        return "error: blocked by FPL"
    except FplError as e:
        store.log_run(machine, "tick", "error", str(e))
        return f"error: {e}"

    if state.get("alerted_blocked"):
        store.set_state("alerted_blocked", False)

    jobs = due_jobs(now, events, state)
    if not jobs:
        return "nothing due"

    ev = next_event(events, now)
    chk = latest_checked_event(events)
    ctx = {"cfg": cfg, "now": now, "client": client, "store": store, "ntfy": ntfy, "event": ev}
    results = []
    for job in jobs:
        try:
            detail = HANDLERS[job](ctx)
            key, value = _DONE[job]
            store.set_state(key, value(now, ev, chk))
            store.log_run(machine, job, "ok", detail)
            results.append(detail)
        except Exception as e:  # each job fails on its own; retries come from the next tick
            log.exception("job %s failed", job)
            store.log_run(machine, job, "error", f"{type(e).__name__}: {e}")
            results.append(f"{job}: error")
    return "; ".join(results)


def _alert_once(ntfy, cfg, store, state, key, message) -> None:
    flag = f"alerted_{key}"
    if not state.get(flag):
        ntfy.send(cfg.topic_alerts, message, title="FPL bot needs you", priority="high", tags=["rotating_light"])
        store.set_state(flag, True)
