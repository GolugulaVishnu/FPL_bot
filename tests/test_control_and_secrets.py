import base64
import os
import time

import pytest

from fplbot import control, gitops, logs


def test_control_messages_pause_then_resume(tmp_path):
    flag = tmp_path / "PAUSED"
    msgs = [{"id": "a", "message": "pause"}]
    last = control.apply_control_messages(msgs, flag, None)
    assert flag.exists() and last == "a"
    # the same message seen again is not re-applied
    flag.unlink()
    assert control.apply_control_messages(msgs, flag, "a") == "a"
    assert not flag.exists()
    flag.write_text("x")
    control.apply_control_messages(msgs + [{"id": "b", "message": " Resume "}], flag, "a")
    assert not flag.exists()


def test_run_lock_blocks_overlap_and_clears_stale(tmp_path):
    lock = tmp_path / "tick.lock"
    with control.RunLock(lock):
        with pytest.raises(control.LockBusy):
            with control.RunLock(lock):
                pass
    assert not lock.exists()
    lock.write_text("123")
    old = time.time() - control.STALE_LOCK_SECONDS - 5
    os.utime(lock, (old, old))
    with control.RunLock(lock):
        pass


def test_backup_takes_over_only_on_confirmed_silence():
    assert control.backup_should_run([]) is True
    assert control.backup_should_run([{"message": "alive"}]) is False
    assert control.backup_should_run(None) is False


def test_git_auth_env_keeps_token_out_of_plain_values():
    env = gitops.auth_env("ghp_secret123")
    assert all("ghp_secret123" not in v for v in env.values())
    header = env["GIT_CONFIG_VALUE_0"].split()[-1]
    assert base64.b64decode(header).decode() == "x-access-token:ghp_secret123"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_log_scrub_removes_registered_secrets():
    logs.register_secret("hunter2-password")
    assert logs.scrub("login with hunter2-password failed") == "login with [REDACTED] failed"
