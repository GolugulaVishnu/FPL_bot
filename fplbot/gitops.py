"""Commit and push files (decision cards, samples) to the private repo.

The GitHub token is passed to git through environment variables for the one
command that needs it, never on the command line, in the remote URL, in
git config files, or in logs.
"""
from __future__ import annotations

import base64
import logging
import os
import subprocess
from pathlib import Path

from .logs import scrub

log = logging.getLogger("fplbot.git")


class GitError(RuntimeError):
    pass


def auth_env(token: str) -> dict[str, str]:
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
    }


def _git(repo: Path, *args: str, token: str | None = None) -> str:
    env = dict(os.environ)
    if token:
        env.update(auth_env(token))
    p = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise GitError(f"git {args[0]} failed: {scrub(p.stderr.strip())[:500]}")
    return p.stdout


def check_access(repo: Path, token: str) -> None:
    _git(repo, "ls-remote", "--heads", "origin", token=token)


def commit_and_push(repo: Path, files: list[Path], message: str, token: str | None) -> bool:
    """Commit `files`, bring in any new commits from GitHub, and push. Returns whether a commit was made.

    Commits left unpushed by an earlier failure are pushed too. If the push still
    fails, the commit stays local and GitError is raised; the next successful push
    carries it (system-flow.md, section 9).
    """
    rel = [str(Path(f).resolve().relative_to(repo.resolve())) for f in files]
    _git(repo, "add", "--", *rel)
    committed = bool(_git(repo, "diff", "--cached", "--name-only").strip())
    if committed:
        _git(repo, "commit", "-m", message)
    push(repo, token)
    return committed


def current_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()


def push(repo: Path, token: str | None) -> None:
    """Merge the remote branch (never rebase or force) and push the current branch."""
    branch = current_branch(repo)
    try:
        _git(repo, "pull", "--no-rebase", "--no-edit", "origin", branch, token=token)
    except GitError:
        # A conflicting merge must not leave the working copy half-merged.
        subprocess.run(["git", "merge", "--abort"], cwd=repo, capture_output=True)
        raise
    _git(repo, "push", "origin", f"HEAD:{branch}", token=token)
