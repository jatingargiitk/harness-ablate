"""Claude Code runner: ``claude -p <prompt> --output-format json`` in the worktree.

Only flags that the installed CLI lists in ``claude --help`` are passed
(e.g. ``--max-turns`` is used only if it exists). Permission checks are
skipped so runs are unattended, which is why the runner refuses to start
anywhere but inside a harness-ablate temp worktree.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path

from ..check import kill_group
from ..tasks import Task
from .base import INFRA, TIMEOUT, RunResult

# Rough $ per task run, used only for the up-front estimate (override with --cost-per-run).
COST_PER_RUN = {"haiku": 0.05, "sonnet": 0.30, "opus": 1.00}
DEFAULT_COST_PER_RUN = 0.50
WORKTREE_PREFIX = "harness-ablate-"


class ClaudeNotFound(RuntimeError):
    pass


@lru_cache(maxsize=None)
def cli_flags(binary: str = "claude") -> frozenset[str]:
    try:
        out = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=30).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise ClaudeNotFound(f"could not run `{binary} --help`: {e}") from None
    return frozenset(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", out))


def cli_version(binary: str = "claude") -> str:
    try:
        return subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def inside_temp_worktree(workdir: Path) -> bool:
    tmp = Path(tempfile.gettempdir()).resolve()
    workdir = Path(workdir).resolve()
    return any(p.name.startswith(WORKTREE_PREFIX) and p.parent == tmp for p in workdir.parents)


def parse_result(stdout: str) -> dict | None:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return data
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):  # some versions emit an array of messages
        data = next((m for m in reversed(data) if isinstance(m, dict) and m.get("type") == "result"), None)
    return data if isinstance(data, dict) else None


def result_to_run(data: dict, wall_s: float) -> RunResult:
    usage = data.get("usage") or {}
    tokens_in = sum(int(usage.get(k) or 0) for k in
                    ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    res = RunResult(tokens_in=tokens_in, tokens_out=int(usage.get("output_tokens") or 0),
                    cost_usd=float(data.get("total_cost_usd") or 0.0), turns=int(data.get("num_turns") or 0),
                    wall_s=round(wall_s, 2))
    subtype = data.get("subtype") or ""
    if data.get("api_error_status"):
        res.error, res.error_kind = f"API error {data['api_error_status']}: {str(data.get('result'))[:300]}", INFRA
    elif data.get("is_error") or subtype != "success":
        # max turns / max budget / the model gave up: an agent outcome, judged by the check like any other
        res.error = f"{subtype or 'error'}: {str(data.get('result') or data.get('terminal_reason') or '')[:300]}"
    return res


class ClaudeRunner:
    name = "claude"

    def __init__(self, model: str | None = None, *, isolate_user: bool = False, binary: str = "claude",
                 cost_per_run: float | None = None, extra_args: list[str] | None = None,
                 require_temp_worktree: bool = True):
        self.binary = shutil.which(binary) or binary
        self.model = model or "default"
        self._model_flag = model
        self.isolate_user = isolate_user
        self.extra_args = list(extra_args or [])
        self.require_temp_worktree = require_temp_worktree
        self._cost_per_run = cost_per_run
        self.flags = cli_flags(self.binary)

    def supports(self, flag: str) -> bool:
        return flag in self.flags

    def command(self, prompt: str, max_turns: int | None, budget_usd: float | None) -> list[str]:
        cmd = [self.binary, "-p", prompt, "--output-format", "json"]
        if self._model_flag:
            cmd += ["--model", self._model_flag]
        if self.supports("--dangerously-skip-permissions"):
            cmd.append("--dangerously-skip-permissions")
        elif self.supports("--permission-mode"):
            cmd += ["--permission-mode", "bypassPermissions"]
        if self.supports("--no-session-persistence"):
            cmd.append("--no-session-persistence")
        if max_turns and self.supports("--max-turns"):
            cmd += ["--max-turns", str(max_turns)]
        if budget_usd is not None and budget_usd > 0 and self.supports("--max-budget-usd"):
            cmd += ["--max-budget-usd", f"{budget_usd:.2f}"]
        if self.isolate_user:
            if self.supports("--setting-sources"):
                cmd += ["--setting-sources", "project,local"]
            if self.supports("--strict-mcp-config"):
                cmd.append("--strict-mcp-config")
        return cmd + self.extra_args

    def run(self, task: Task, workdir: Path, timeout: float, max_turns: int | None,
            *, repeat: int = 0, budget_usd: float | None = None) -> RunResult:
        workdir = Path(workdir)
        if self.require_temp_worktree and not inside_temp_worktree(workdir):
            raise RuntimeError(f"refusing to run claude with permission checks off outside a temp worktree: {workdir}")
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        start = time.monotonic()
        try:
            proc = subprocess.Popen(self.command(task.prompt, max_turns, budget_usd), cwd=workdir, env=env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, errors="replace", start_new_session=True)
        except OSError as e:
            return RunResult(error=f"could not start claude: {e}", error_kind=INFRA)
        try:
            out, errout = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_group(proc)
            proc.communicate()
            # Spend is unknown; the engine charges the per-run budget against --max-cost.
            return RunResult(error=f"timed out after {timeout:.0f}s", error_kind=TIMEOUT,
                             wall_s=round(time.monotonic() - start, 2))
        wall = time.monotonic() - start
        data = parse_result(out)
        if data is None:
            msg = (errout or out or "").strip()[-500:] or f"exit code {proc.returncode}"
            return RunResult(error=f"no JSON result from claude: {msg}", error_kind=INFRA, wall_s=round(wall, 2))
        return result_to_run(data, wall)

    def estimate_cost_per_run(self) -> float:
        if self._cost_per_run is not None:
            return self._cost_per_run
        m = (self.model or "").lower()
        return next((v for k, v in COST_PER_RUN.items() if k in m), DEFAULT_COST_PER_RUN)
