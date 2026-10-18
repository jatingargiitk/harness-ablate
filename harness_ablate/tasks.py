"""tasks.yaml loading.

    setup: pip install -e .          # optional, runs in every worktree first
    timeout_s: 600                   # optional defaults for every task
    tasks:
      - id: fix-dates
        prompt: "tests/test_dates.py fails. Fix the bug."
        check: python -m pytest -q tests/test_dates.py
        timeout_s: 300               # optional
        max_turns: 30                # optional, only used if the CLI supports it
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

DEFAULT_TIMEOUT_S = 600
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class TaskError(ValueError):
    pass


@dataclass
class Task:
    id: str
    prompt: str
    check: str
    timeout_s: int = DEFAULT_TIMEOUT_S
    max_turns: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TaskFile:
    path: Path
    tasks: list[Task]
    setup: str | None = None
    project: Path = field(default=Path("."))  # default project dir: the file's directory


def load_tasks(path: str | Path) -> TaskFile:
    path = Path(path).resolve()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TaskError(f"{path} not found") from None
    except yaml.YAMLError as e:
        raise TaskError(f"{path}: invalid YAML: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list) or not data["tasks"]:
        raise TaskError(f"{path}: expected a mapping with a non-empty 'tasks:' list")
    default_timeout = int(data.get("timeout_s", DEFAULT_TIMEOUT_S))
    default_turns = data.get("max_turns")
    tasks, seen = [], set()
    for i, raw in enumerate(data["tasks"]):
        if not isinstance(raw, dict):
            raise TaskError(f"{path}: task #{i + 1} is not a mapping")
        missing = [k for k in ("id", "prompt", "check") if not raw.get(k)]
        if missing:
            raise TaskError(f"{path}: task #{i + 1} is missing {', '.join(missing)}")
        tid = str(raw["id"])
        if not ID_RE.match(tid):
            raise TaskError(f"{path}: task id {tid!r} may only contain letters, digits, _ . -")
        if tid in seen:
            raise TaskError(f"{path}: duplicate task id {tid!r}")
        seen.add(tid)
        unknown = set(raw) - {"id", "prompt", "check", "timeout_s", "max_turns"}
        if unknown:
            raise TaskError(f"{path}: task {tid!r} has unknown keys: {', '.join(sorted(unknown))}")
        turns = raw.get("max_turns", default_turns)
        tasks.append(Task(id=tid, prompt=str(raw["prompt"]), check=str(raw["check"]),
                          timeout_s=int(raw.get("timeout_s", default_timeout)),
                          max_turns=int(turns) if turns is not None else None))
    setup = data.get("setup")
    return TaskFile(path=path, tasks=tasks, setup=str(setup) if setup else None, project=path.parent)
