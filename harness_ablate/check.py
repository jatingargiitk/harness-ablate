"""Run shell commands (setup and checks) inside a worktree; exit 0 means pass."""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

TAIL_CHARS = 2000


@dataclass
class CommandResult:
    ok: bool
    exit_code: int | None  # None on timeout
    output: str  # tail of combined stdout/stderr
    timed_out: bool = False


def kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_command(cmd: str, cwd: str | Path, timeout: float | None = 300, env: dict | None = None) -> CommandResult:
    proc = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, text=True, errors="replace",
                            start_new_session=True, env=env)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(proc)
        out, _ = proc.communicate()
        return CommandResult(False, None, (out or "")[-TAIL_CHARS:], timed_out=True)
    return CommandResult(proc.returncode == 0, proc.returncode, (out or "")[-TAIL_CHARS:])


def run_check(check: str, cwd: str | Path, timeout: float = 300) -> CommandResult:
    return run_command(check, cwd, timeout)
