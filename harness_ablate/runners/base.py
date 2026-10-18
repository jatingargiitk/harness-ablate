from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from ..tasks import Task

# error_kind values
TIMEOUT = "timeout"  # counts as a fail
INFRA = "infra"  # API/CLI failure; excluded from the pass rate


@dataclass
class RunResult:
    passed: bool = False  # filled in from the task's check after the agent finishes
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    turns: int = 0
    wall_s: float = 0.0
    error: str | None = None
    error_kind: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class Runner(Protocol):
    name: str
    model: str

    def run(self, task: Task, workdir: Path, timeout: float, max_turns: int | None,
            *, repeat: int = 0, budget_usd: float | None = None) -> RunResult: ...

    def estimate_cost_per_run(self) -> float: ...
