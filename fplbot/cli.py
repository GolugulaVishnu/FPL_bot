"""Command line: fplbot setup | capture | tick | pause | resume | status | schedule."""
from __future__ import annotations

import argparse
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

    args = p.parse_args(argv)
    logs.setup()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
