"""Register the 15-minute run with Task Scheduler (Windows) or launchd (macOS)."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from . import paths

WINDOWS_TASK = r"FPLBot\Tick"
MAC_LABEL = "com.fplbot.tick"
INTERVAL_MIN = 15


def _python_for_task() -> str:
    exe = Path(sys.executable)
    if sys.platform == "win32":
        quiet = exe.with_name("pythonw.exe")  # no console window every 15 minutes
        if quiet.exists():
            return str(quiet)
    return str(exe)


def windows_create_args(run_when_logged_off: bool, user: str | None = None) -> list[str]:
    args = ["schtasks", "/Create", "/TN", WINDOWS_TASK, "/SC", "MINUTE", "/MO", str(INTERVAL_MIN),
            "/TR", f'"{_python_for_task()}" -m fplbot tick', "/F"]
    if run_when_logged_off:
        # schtasks asks for the Windows account password itself; the bot never sees it.
        args += ["/RU", user or os.environ.get("USERNAME", ""), "/RP", "*"]
    return args


def mac_plist() -> dict:
    logs = paths.log_dir()
    return {
        "Label": MAC_LABEL,
        "ProgramArguments": [_python_for_task(), "-m", "fplbot", "tick"],
        "WorkingDirectory": str(paths.REPO_ROOT),
        "StartInterval": INTERVAL_MIN * 60,
        "RunAtLoad": False,
        "StandardOutPath": str(logs / "launchd.out.log"),
        "StandardErrorPath": str(logs / "launchd.err.log"),
    }


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def install(run_when_logged_off: bool = False) -> str:
    if sys.platform == "win32":
        subprocess.run(windows_create_args(run_when_logged_off), check=True)
        return f"Task Scheduler task {WINDOWS_TASK} runs every {INTERVAL_MIN} minutes."
    if sys.platform == "darwin":
        p = _mac_plist_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            plistlib.dump(mac_plist(), f)
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, str(p)], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(p)], check=True)
        return f"launchd job {MAC_LABEL} runs every {INTERVAL_MIN} minutes."
    raise RuntimeError("Scheduling is only set up for Windows and macOS.")


def uninstall() -> str:
    if sys.platform == "win32":
        subprocess.run(["schtasks", "/Delete", "/TN", WINDOWS_TASK, "/F"], check=False)
        return "Task Scheduler task removed."
    if sys.platform == "darwin":
        p = _mac_plist_path()
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(p)], capture_output=True)
        p.unlink(missing_ok=True)
        return "launchd job removed."
    raise RuntimeError("Scheduling is only set up for Windows and macOS.")
