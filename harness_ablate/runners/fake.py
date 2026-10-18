"""A deterministic stand-in for a coding agent, for tests and offline dry runs.

It reads the harness present in the worktree, turns it into a pass
probability via regex rules, and passes a task when a hash of
(seed, task, repeat) falls under that probability. The same (task, repeat)
uses the same random draw in every variant, so differences between variants
come only from the harness. On a pass it writes ``.fake_pass`` so a check
like ``test -f .fake_pass`` exercises the real check path.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from ..harness import MEMORY_FILES, SKILLS_DIR, hook_pieces, tokens_of
from ..tasks import Task
from .base import INFRA, TIMEOUT, RunResult

DEFAULT_RULES: list[tuple[str, float]] = [
    (r"(never|don't|do not) run (the )?(tests|pytest)", -0.6),
    (r"pytest", 0.15),
]
BASE_TOKENS_IN = 3000
TOKENS_OUT = 800
TURNS = 6
PRICE_IN, PRICE_OUT = 3e-6, 15e-6
PASS_MARKER = ".fake_pass"


def draw(seed: str, task_id: str, repeat: int) -> float:
    h = hashlib.sha256(f"{seed}|{task_id}|{repeat}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def harness_text(workdir: Path) -> str:
    parts = [(workdir / rel).read_text(encoding="utf-8", errors="replace")
             for rel in MEMORY_FILES if (workdir / rel).is_file()]
    skills = workdir / SKILLS_DIR
    if skills.is_dir():
        parts += [p.read_text(encoding="utf-8", errors="replace") for p in sorted(skills.glob("*/SKILL.md"))]
    return "\n".join(parts)


class FakeRunner:
    name = "fake"

    def __init__(self, model: str = "fake", base_rate: float = 0.6, rules: list[tuple[str, float]] | None = None,
                 seed: str = "0", infra_errors: set[tuple[str, int]] | None = None,
                 timeouts: set[tuple[str, int]] | None = None, task_bias: dict[str, float] | None = None,
                 delay_s: float = 0.0):
        self.model = model
        self.delay_s = delay_s
        self.base_rate = base_rate
        self.rules = [(re.compile(p, re.I), d) for p, d in (DEFAULT_RULES if rules is None else rules)]
        self.seed = seed
        self.infra_errors = infra_errors or set()
        self.timeouts = timeouts or set()
        self.task_bias = task_bias or {}
        self.calls: list[tuple[str, int, Path]] = []

    def probability(self, text: str, task_id: str) -> float:
        p = self.base_rate + self.task_bias.get(task_id, 0.0)
        p += sum(d for rx, d in self.rules if rx.search(text))
        return min(1.0, max(0.0, p))

    def run(self, task: Task, workdir: Path, timeout: float, max_turns: int | None,
            *, repeat: int = 0, budget_usd: float | None = None) -> RunResult:
        workdir = Path(workdir)
        self.calls.append((task.id, repeat, workdir))
        if self.delay_s:
            time.sleep(self.delay_s)
        text = harness_text(workdir)
        n_hooks = len(hook_pieces(workdir))
        tokens_in = (BASE_TOKENS_IN + tokens_of(text)) * TURNS
        cost = tokens_in * PRICE_IN + TOKENS_OUT * PRICE_OUT
        res = RunResult(tokens_in=tokens_in, tokens_out=TOKENS_OUT, cost_usd=round(cost, 6),
                        turns=TURNS, wall_s=round(1.0 + 0.2 * n_hooks, 3))
        key = (task.id, repeat)
        if key in self.infra_errors:
            return RunResult(error="simulated API error", error_kind=INFRA)
        if key in self.timeouts:
            res.error, res.error_kind, res.wall_s = f"timed out after {timeout:.0f}s", TIMEOUT, float(timeout)
            return res
        (workdir / PASS_MARKER).unlink(missing_ok=True)
        if draw(self.seed, task.id, repeat) < self.probability(text, task.id):
            (workdir / PASS_MARKER).write_text("ok\n")
        return res

    def estimate_cost_per_run(self) -> float:
        return round((BASE_TOKENS_IN * TURNS) * PRICE_IN + TOKENS_OUT * PRICE_OUT, 4)
