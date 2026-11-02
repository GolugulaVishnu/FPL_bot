"""Command line: fplbot setup | capture | tick | pause | resume | status | schedule."""
from __future__ import annotations

import argparse
from pathlib import Path
import getpass
import sys

from . import config as config_mod
from . import gitops, installer, logs, paths, secret_store
from .fpl_api import FplBlocked, FplError, FplPublicClient
from .notify import Ntfy


def _ask(prompt: str, default: str) -> str:
    v = input(f"{prompt} [{default}]: ").strip()
    return v or default


def _ask_secret_twice(label: str) -> str:
    while True:
        a = getpass.getpass(f"{label} (typing is hidden): ")
        if not a:
            print("  Nothing entered, try again.")
            continue
        b = getpass.getpass(f"{label} again: ")
        if a == b:
            return a
        print("  They didn't match, try again.")


def cmd_setup(args) -> int:
    cfg = config_mod.load()
    print("FPL bot setup. Nothing you type here is saved to the repo.\n")

    default_role = cfg.role if paths.config_path().exists() else ("backup" if sys.platform == "darwin" else "primary")
    cfg.role = _ask("Role of this machine: primary (Windows) or backup (Mac)", default_role)
    if cfg.role not in config_mod.ROLES:
        print("Role must be 'primary' or 'backup'.")
        return 2
    cfg.fpl_email = _ask("FPL account email", cfg.fpl_email)

    # 1. FPL password -> OS keychain
    if secret_store.has_fpl_password(cfg.fpl_email) and not args.reset:
        print("FPL password: already saved on this machine (use --reset to change it).")
    else:
        secret_store.set_fpl_password(cfg.fpl_email, _ask_secret_twice("FPL password"))
        print("FPL password: saved to the OS keychain.")

    # 2. GitHub token -> OS keychain, then check it can reach the repo
    if secret_store.has_github_token() and not args.reset:
        print("GitHub token: already saved on this machine.")
    else:
        secret_store.set_github_token(_ask_secret_twice("GitHub token"))
        print("GitHub token: saved to the OS keychain.")
    try:
        gitops.check_access(paths.REPO_ROOT, secret_store.github_token())
        print("GitHub token: can reach the repo.")
    except gitops.GitError as e:
        print(f"GitHub token: could not reach the repo ({e}). Check the token's repo access and expiry.")

    # 3. ntfy topics: generated on the primary, copied to the backup
    if not cfg.topics_set():
        if cfg.role == "primary":
            config_mod.generate_topics(cfg)
        else:
            print("\nPaste the three topic names that setup printed on the Windows machine:")
            cfg.topic_alerts = input("  alerts topic: ").strip()
            cfg.topic_control = input("  control topic: ").strip()
            cfg.topic_heartbeat = input("  heartbeat topic: ").strip()
    config_mod.save(cfg)

    ntfy = Ntfy(cfg.ntfy_server)
    sent = ntfy.send(cfg.topic_alerts, f"Setup finished on the {cfg.role} machine.", title="FPL bot test")
    print("\nntfy: in the ntfy app, tap + and subscribe to these two topics (keep the names private):")
    print(f"  alerts:  {cfg.topic_alerts}")
    print(f"  control: {cfg.topic_control}   (send 'pause' or 'resume' here)")
    print(f"  heartbeat (bot use only, no need to subscribe): {cfg.topic_heartbeat}")
    print("  Test notification sent." if sent else "  Could not send a test notification; check the internet connection.")

    if args.enable_schedule:
        print("\n" + installer.install(run_when_logged_off=args.run_when_logged_off))
    else:
        print("\nScheduler not enabled yet. It gets enabled for the dry run with: fplbot schedule install")
    return 0


def cmd_capture(args) -> int:
    from .capture import capture
    client = FplPublicClient(paths.cache_dir())
    try:
        files = capture(client, paths.REPO_ROOT)
    except FplBlocked as e:
        print(f"{e}. FPL is refusing this network; the bot will not work around it.")
        return 1
    except FplError as e:
        print(f"Capture failed: {e}")
        return 1
    for f in files:
        print(f"saved {f.relative_to(paths.REPO_ROOT)}")
    if args.push:
        try:
            pushed = gitops.commit_and_push(paths.REPO_ROOT, files, "Add FPL data snapshot",
                                            secret_store.github_token())
            print("Committed and pushed." if pushed else "No new data to commit; repo is up to date.")
        except (gitops.GitError, secret_store.MissingSecret) as e:
            print(f"Saved locally but not pushed: {e}")
            return 1
    return 0


def cmd_tick(args) -> int:
    from . import tick
    cfg = config_mod.load()
    if not cfg.topics_set():
        print("Not set up yet. Run: fplbot setup")
        return 2
    result = tick.run(cfg)
    logs.setup().info("tick: %s", result)
    return 0


def cmd_pause(args) -> int:
    paths.pause_flag().write_text("paused from the command line\n", encoding="utf-8")
    print("Paused on this machine. Send 'pause' to the control topic to pause both machines.")
    return 0


def cmd_resume(args) -> int:
    paths.pause_flag().unlink(missing_ok=True)
    print("Resumed on this machine. If you paused through ntfy, also send 'resume' to the control topic.")
    return 0


def cmd_status(args) -> int:
    from .store import Store
    cfg = config_mod.load()
    print(f"role:          {cfg.role}")
    print(f"FPL email:     {cfg.fpl_email}")
    print(f"FPL password:  {'saved' if secret_store.has_fpl_password(cfg.fpl_email) else 'MISSING'}")
    print(f"GitHub token:  {'saved' if secret_store.has_github_token() else 'MISSING'}")
    print(f"ntfy topics:   {'set' if cfg.topics_set() else 'MISSING'}")
    print(f"paused:        {'yes' if paths.pause_flag().exists() else 'no'}")
    print(f"data folder:   {paths.data_dir()}")
    store = Store(paths.db_path())
    runs = store.recent_runs(10)
    if runs:
        print("recent runs:")
        for ts, machine, job, status, detail in runs:
            print(f"  {ts}  {machine:<24} {job:<12} {status:<8} {detail or ''}")
    return 0


def cmd_schedule(args) -> int:
    if args.action == "install":
        print(installer.install(run_when_logged_off=args.run_when_logged_off))
    else:
        print(installer.uninstall())
    return 0


def _latest_sample():
    root = paths.REPO_ROOT / "samples"
    dirs = sorted(d for d in root.glob("*") if (d / "bootstrap-static.json").exists()) if root.exists() else []
    return dirs[-1] if dirs else None


def _current_data(args):
    """Bootstrap, fixtures and live data: from a samples/ folder if asked, else the FPL API (cached)."""
    from .data import fetch_current
    from .sources.current import load_snapshot_dir
    if getattr(args, "snapshot", None):
        folder = Path(args.snapshot) if args.snapshot != "latest" else _latest_sample()
        if folder is None:
            raise SystemExit("No snapshot in samples/. Run: fplbot capture --push")
        return load_snapshot_dir(folder)
    return fetch_current(FplPublicClient(paths.cache_dir()))


def cmd_data(args) -> int:
    from .data import load_current, load_history
    from .datastore import DataStore
    ds = DataStore(paths.db_path())
    if args.what in ("history", "all"):
        for season, n in load_history(ds, paths.cache_dir(), args.seasons).items():
            print(f"{season}: {n} match rows loaded")
    if args.what in ("current", "all"):
        try:
            boot, fx, lives = _current_data(args)
        except (FplBlocked, FplError) as e:
            print(f"Could not read FPL data: {e}")
            return 1
        season, n = load_current(ds, boot, fx, lives)
        print(f"{season}: {n} match rows loaded ({len(lives)} finished gameweeks)")
    return 0


def cmd_backtest(args) -> int:
    from .datastore import DataStore
    from .model import backtest
    from .model.project import previous_season
    ds = DataStore(paths.db_path())
    if args.season not in ds.seasons():
        print(f"No data for {args.season}. Run: fplbot data history")
        return 1
    prior = previous_season(args.season)
    res = backtest.run(ds, args.season, prior if prior in ds.seasons() else None, args.start, args.end)
    text = backtest.report(res)
    print(text)
    if args.save:
        out = paths.REPO_ROOT / "reports" / f"backtest-{args.season}.txt"
        out.parent.mkdir(exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"\nSaved {out.relative_to(paths.REPO_ROOT)}")
    return 0


def cmd_project(args) -> int:
    from datetime import datetime, timezone
    from .datastore import DataStore
    from .model.project import format_table, project_upcoming
    ds = DataStore(paths.db_path())
    try:
        boot, fx, _lives = _current_data(args)
    except (FplBlocked, FplError) as e:
        print(f"Could not read FPL data: {e}")
        return 1
    now = datetime.fromisoformat(args.at).replace(tzinfo=timezone.utc) if args.at else datetime.now(timezone.utc)
    gws, projs = project_upcoming(ds, boot, fx, now, args.horizon)
    if not gws:
        print("No upcoming gameweeks.")
        return 0
    print(format_table(gws, projs, args.top, args.position))
    return 0


TEAM_NAME = "xP Machine"


def _git_version() -> str:
    import subprocess
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=paths.REPO_ROOT, capture_output=True, text=True)
    return r.stdout.strip() or "unknown"


def cmd_pick(args) -> int:
    """Build this gameweek's team and decision card. Submission to FPL is not automated yet."""
    from datetime import datetime, timezone
    from .data import load_current
    from .datastore import DataStore
    from .model.project import project_with_context
    from .plan import card, chips, rules as squad_rules, squad
    from .sources.current import season_label

    now = datetime.fromisoformat(args.at).replace(tzinfo=timezone.utc) if args.at else datetime.now(timezone.utc)
    try:
        boot, fx, lives = _current_data(args)
    except (FplBlocked, FplError) as e:
        print(f"Could not read FPL data: {e}")
        return 1
    ds = DataStore(paths.db_path())
    load_current(ds, boot, fx, lives)
    gws, projs, ctx = project_with_context(ds, boot, fx, now, args.horizon)
    if not gws:
        print("No upcoming gameweek.")
        return 1
    g0 = gws[0]
    rules = squad_rules.from_bootstrap(boot)
    team_of = {e["id"]: e["team"] for e in boot["elements"]}
    plan = squad.pick_squad(projs, gws, rules, team_of)

    squad_dicts = [dict(element=p.element, position=p.position, team=team_of[p.element], price=p.price) for p in plan.squad]
    errors = squad_rules.validate(rules, squad_dicts, [p.element for p in plan.xi], [p.element for p in plan.bench],
                                  plan.captain.element, plan.vice.element)
    if errors:
        print("The picked team breaks the rules, so no card was written:\n  " + "\n  ".join(errors))
        return 1

    available = {c["name"] for c in boot.get("chips", []) if c.get("start_event", 0) <= g0 <= c.get("stop_event", 38)}
    decision = chips.decide(plan, available, first_gameweek=True)

    short = {t["id"]: t["short_name"] for t in boot["teams"]}
    opponents: dict[int, str] = {}
    for f in fx:
        if f.get("event") != g0:
            continue
        for p in plan.squad:
            t = team_of[p.element]
            if t in (f["team_h"], f["team_a"]):
                o = f"{short[f['team_a']]} (H)" if t == f["team_h"] else f"{short[f['team_h']]} (A)"
                opponents[p.element] = (opponents[p.element] + ", " + o) if p.element in opponents else o

    deadline = next(datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")) for e in boot["events"] if e["id"] == g0)
    season = season_label(boot)
    notes = [
        "",
        "HOW THIS GAMEWEEK GETS ENTERED",
        "  The bot cannot log in and submit yet, so enter this team on the FPL site by hand:",
        f"  1. Pick Team: add the 15 players above (budget {rules.budget / 10:.1f}m).",
        f"  2. Team name: {TEAM_NAME}. Favourite club: none.",
        "  3. Starting XI and bench order exactly as above; set captain (C) and vice (V).",
        f"  4. Chip: {card.CHIP_NAMES[decision.chip]}" + (" (activate it on the Pick Team page before saving)." if decision.chip else "."),
        f"  5. Save before {deadline.strftime('%a %d %b %H:%M UTC')}.",
    ]
    text = card.render(season=season, gw=g0, kind=args.kind, deadline=deadline, now=now, plan=plan, chip=decision,
                       all_projs=projs, opponents=opponents, budget=rules.budget,
                       mode="Initial squad: the team has no players yet, so all 15 are picked freely "
                            "(unlimited transfers before the team's first deadline).",
                       model_version=_git_version(),
                       data_note=(f"snapshot {args.snapshot}" if args.snapshot else f"FPL API, read {now.strftime('%Y-%m-%d %H:%M UTC')}")
                                 + f"; {len(lives)} finished gameweeks loaded",
                       team_name=TEAM_NAME, extra_notes=notes, ctx=ctx)
    out = card.card_path(paths.REPO_ROOT, season, g0, args.kind)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Saved {out.relative_to(paths.REPO_ROOT)}")
    if args.push:
        try:
            gitops.commit_and_push(paths.REPO_ROOT, [out], f"Decision card {season} GW{g0} ({args.kind})",
                                   secret_store.github_token())
            print("Committed and pushed.")
        except (gitops.GitError, secret_store.MissingSecret) as e:
            print(f"Saved locally but not pushed: {e}")
            return 1
    return 0


def cmd_record(args) -> int:
    """Open a browser, let the owner log in and save the team, and record the site's requests without secrets."""
    try:
        from .record import recorder
    except ImportError:
        print('The browser recorder is not installed. Run:  pip install -e ".[record]"  then  python -m playwright install chromium')
        return 2
    cfg = config_mod.load()
    secrets = [cfg.fpl_email]
    for getter in (lambda: secret_store.fpl_password(cfg.fpl_email), secret_store.github_token):
        try:
            secrets.append(getter())
        except secret_store.MissingSecret:
            pass
    print("A browser window will open on the FPL site. In it:")
    print("  1. Log in with the FPL account.")
    print("  2. Enter the team exactly as the latest decision card says, and save it.")
    print("  3. Wait a few seconds after saving, then close the browser window.")
    print("Nothing from the browser (cookies, tokens) is kept. Only a cleaned record of the site's requests is saved.\n")
    try:
        rec = recorder.run()
    except Exception as e:
        print(f"The browser could not start: {e}\nIf Chromium is missing, run:  python -m playwright install chromium")
        return 1
    try:
        out = recorder.save(rec, paths.REPO_ROOT / "recordings", secrets)
    except recorder.LeakError as e:
        print(f"{e}. Nothing was written; send the message above to Claude.")
        return 1
    print(f"Saved {out.relative_to(paths.REPO_ROOT)} ({len(rec.entries)} requests).")
    if args.push:
        try:
            gitops.commit_and_push(paths.REPO_ROOT, [out], "Add cleaned FPL session recording",
                                   secret_store.github_token())
            print("Committed and pushed.")
        except (gitops.GitError, secret_store.MissingSecret) as e:
            print(f"Saved locally but not pushed: {e}")
            return 1
    return 0


def cmd_login(args) -> int:
    """Sign in through a browser on this machine, read the team (no changes), optionally find the save token's source."""
    import json as _json
    from datetime import datetime, timezone
    try:
        from .fpl_session import FplBrowser, HumanCheck, SessionError
    except ImportError:
        print('The browser part is not installed. Run:  pip install -e ".[record]"  then  python -m playwright install chromium')
        return 2
    cfg = config_mod.load()
    try:
        password = secret_store.fpl_password(cfg.fpl_email)
    except secret_store.MissingSecret as e:
        print(e)
        return 2
    try:
        boot = FplPublicClient(paths.cache_dir()).bootstrap()
        names = {e["id"]: e["web_name"] for e in boot["elements"]}
    except (FplBlocked, FplError):
        names = {}
    if args.manual:
        print("Opening the FPL site in a browser window. Sign in yourself there (the bot waits up to 10 minutes).")
        print("The bot records the sign-in page's layout (field types and button labels, never what you type).")
    else:
        print("Opening the FPL site in a browser window and signing in. Nothing on the team is changed.")
    b = None
    try:
        with FplBrowser(headless=args.headless) as b:
            if args.manual:
                entry = b.login_manually()
            else:
                entry = b.login(cfg.fpl_email, password, wait_for_human=0 if args.headless else 300)
            _save_login_layout(b, args, [password, cfg.fpl_email])
            cfg.extra["entry"] = entry
            config_mod.save(cfg)
            team = b.my_team(entry)
            t = team.get("transfers", {})
            print(f"\nSigned in. Team ID {entry}.")
            print(f"  Bank {t.get('bank', 0) / 10:.1f}m, team value {t.get('value', 0) / 10:.1f}m, "
                  f"free transfers {t.get('limit') if t.get('limit') is not None else 'unlimited'}, "
                  f"made this week {t.get('made', 0)}")
            for p in team.get("picks", []):
                tag = " (C)" if p.get("is_captain") else " (V)" if p.get("is_vice_captain") else ""
                print(f"  {p.get('position'):>2}. {names.get(p['element'], p['element'])}{tag}"
                      f"  sell {p.get('selling_price', 0) / 10:.1f}m")
            chips = [f"{c.get('name')}: {c.get('status_for_entry')}" for c in team.get("chips", [])]
            print("  Chips: " + (", ".join(chips) or "none listed"))
            if args.probe:
                print("\nIn the browser window: open Pick Team, change the vice-captain and Save, then change it back and Save.")
                input("Press Enter here when both saves are done... ")
                probe = b.probe_csrf_source()
                out = paths.REPO_ROOT / "recordings" / f"save-token-probe-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
                text = _json.dumps(probe, indent=1)
                from .record.sanitize import leak_check
                problems = leak_check(text, [password, cfg.fpl_email])
                if problems:
                    print("Probe result not saved: " + "; ".join(problems))
                    return 1
                out.parent.mkdir(exist_ok=True)
                out.write_text(text + "\n", encoding="utf-8")
                print(f"Save token seen: {probe['save_token_seen']}. Found in: {', '.join(probe['where']) or 'not found in storage'}")
                print(f"Saved {out.relative_to(paths.REPO_ROOT)} (names only, no values)")
                if args.push:
                    gitops.commit_and_push(paths.REPO_ROOT, [out], "Add save-token probe (names only)",
                                           secret_store.github_token())
                    print("Committed and pushed.")
    except HumanCheck as e:
        Ntfy(cfg.ntfy_server).send(cfg.topic_alerts, str(e), title="FPL bot needs you", priority="high", tags=["rotating_light"])
        print(e)
        return 1
    except SessionError as e:
        print(f"Sign-in failed: {e}")
        if b is not None:
            _save_login_layout(b, args, [password, cfg.fpl_email])
        return 1
    return 0


def _save_login_layout(b, args, secrets: list[str]) -> None:
    """Save the sign-in page layouts seen (no values) so the automatic sign-in can be fixed or confirmed."""
    import json as _json
    from datetime import datetime, timezone
    from .record.sanitize import leak_check, scrub
    if not b.login_layout:
        return
    text = _json.dumps({"login_pages": scrub(b.login_layout)}, indent=1, ensure_ascii=False)
    problems = leak_check(text, secrets)
    if problems:
        print("Sign-in page layout not saved: " + "; ".join(problems))
        return
    out = paths.REPO_ROOT / "recordings" / f"login-layout-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"Saved {out.relative_to(paths.REPO_ROOT)} (sign-in page layout, no values)")
    if args.push:
        try:
            gitops.commit_and_push(paths.REPO_ROOT, [out], "Add sign-in page layout (no values)", secret_store.github_token())
        except (gitops.GitError, secret_store.MissingSecret) as e:
            print(f"Layout saved locally but not pushed: {e}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fplbot")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="save secrets to the keychain, create ntfy topics")
    s.add_argument("--reset", action="store_true", help="re-enter the FPL password and GitHub token")
    s.add_argument("--enable-schedule", action="store_true", help="also register the 15-minute run")
    s.add_argument("--run-when-logged-off", action="store_true", help="Windows: run even when nobody is logged in")
    s.set_defaults(func=cmd_setup)

    c = sub.add_parser("capture", help="save a snapshot of live FPL data to samples/")
    c.add_argument("--push", action="store_true", help="commit and push the snapshot")
    c.set_defaults(func=cmd_capture)

    sub.add_parser("tick", help="one scheduled run (the OS calls this)").set_defaults(func=cmd_tick)
    sub.add_parser("pause", help="pause the bot on this machine").set_defaults(func=cmd_pause)
    sub.add_parser("resume", help="resume the bot on this machine").set_defaults(func=cmd_resume)
    sub.add_parser("status", help="show setup state and recent runs").set_defaults(func=cmd_status)

    sc = sub.add_parser("schedule", help="register or remove the 15-minute run")
    sc.add_argument("action", choices=["install", "remove"])
    sc.add_argument("--run-when-logged-off", action="store_true")
    sc.set_defaults(func=cmd_schedule)

    d = sub.add_parser("data", help="load past seasons and/or the current season into the data store")
    d.add_argument("what", choices=["history", "current", "all"])
    d.add_argument("--seasons", nargs="+", default=["2024-25", "2025-26"], help="past seasons to load")
    d.add_argument("--snapshot", help="load the current season from a samples/ folder ('latest' for the newest)")
    d.set_defaults(func=cmd_data)

    b = sub.add_parser("backtest", help="replay a past season week by week and score the model")
    b.add_argument("--season", default="2025-26")
    b.add_argument("--start", type=int, default=2)
    b.add_argument("--end", type=int, default=38)
    b.add_argument("--save", action="store_true", help="write the report to reports/")
    b.set_defaults(func=cmd_backtest)

    pr = sub.add_parser("project", help="show expected points for the next gameweeks")
    pr.add_argument("--horizon", type=int, default=6)
    pr.add_argument("--top", type=int, default=30)
    pr.add_argument("--position", choices=["GKP", "DEF", "MID", "FWD"])
    pr.add_argument("--snapshot", help="use a samples/ folder instead of the live API ('latest' for the newest)")
    pr.add_argument("--at", help="pretend it is this UTC time, e.g. 2026-10-30T12:00 (testing)")
    pr.set_defaults(func=cmd_project)

    pk = sub.add_parser("pick", help="pick this gameweek's team and write its decision card")
    pk.add_argument("--kind", choices=["draft", "final"], default="final")
    pk.add_argument("--horizon", type=int, default=6)
    pk.add_argument("--push", action="store_true", help="commit and push the decision card")
    pk.add_argument("--snapshot", help="use a samples/ folder instead of the live API ('latest' for the newest)")
    pk.add_argument("--at", help="pretend it is this UTC time (testing)")
    pk.set_defaults(func=cmd_pick)

    rc = sub.add_parser("record", help="log in and save the team in a browser while the bot records how the site does it")
    rc.add_argument("--push", action="store_true", help="commit and push the cleaned recording")
    rc.set_defaults(func=cmd_record)

    lg = sub.add_parser("login", help="sign in through a browser and read the team (changes nothing)")
    lg.add_argument("--probe", action="store_true", help="also find where the site keeps its save token (you save twice)")
    lg.add_argument("--push", action="store_true", help="commit and push the probe result")
    lg.add_argument("--headless", action="store_true", help="no visible window (scheduled runs)")
    lg.add_argument("--manual", action="store_true", help="sign in yourself in the window; the bot just watches")
    lg.set_defaults(func=cmd_login)

    args = p.parse_args(argv)
    logs.setup()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
