"""Plan and execute ablation runs, streaming results to results.jsonl.

results.jsonl starts with one meta record (everything ``report`` and
``resume`` need) followed by one record per finished run, keyed by
``variant|task|repeat``. Runs are ordered repeat -> task -> variant so a
stopped run leaves whole repeats behind.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import __version__
from .check import kill_all, run_check, run_command
from .harness import Piece, discover
from .report import load_results
from .runners.base import INFRA, TIMEOUT, Runner, RunResult
from .tasks import Task, TaskFile, load_tasks
from .variants import Variant, apply_variant, build_variants
from .worktree import RepoInfo, cleanup_stale, inspect_repo, worktree

META_VERSION = 1
MAX_RUN_COST_FACTOR = 5  # default per-run cap = 5x the estimate


class PlanError(RuntimeError):
    pass


def run_key(variant: str, task: str, repeat: int) -> str:
    return f"{variant}|{task}|{repeat}"


@dataclass
class Plan:
    info: RepoInfo
    tasks: list[Task]
    setup: str | None
    tasks_path: str
    pieces: list[Piece]
    variants: list[Variant]
    repeats: int

    @property
    def runs(self) -> list[tuple[Variant, Task, int]]:
        return [(v, t, r) for r in range(self.repeats) for t in self.tasks for v in self.variants]


def make_plan(tasks_path: str | Path, project: str | Path | None = None, *, repeats: int = 3,
              only: list[str] | None = None, bare: bool = True, commit: str | None = None,
              allow_dirty: bool = False) -> Plan:
    tf: TaskFile = load_tasks(tasks_path)
    info = inspect_repo(project or tf.project, commit)
    if info.harness_modified and not allow_dirty:
        raise PlanError("harness files have uncommitted changes: " + ", ".join(info.harness_modified)
                        + ". Commit them, or pass --allow-dirty to test the working-tree version.")
    with worktree(info, allow_dirty=allow_dirty) as wd:
        pieces = discover(wd)
    if not pieces:
        raise PlanError(f"no harness found in {info.project_dir} at {info.commit[:12]}")
    variants = build_variants(pieces, only=only, bare=bare)
    if only and not any(v.id.startswith("minus:") for v in variants):
        raise PlanError(f"--only {' '.join(only)} matched no pieces")
    return Plan(info=info, tasks=tf.tasks, setup=tf.setup, tasks_path=str(tf.path), pieces=pieces,
                variants=variants, repeats=repeats)


def meta_record(plan: Plan, runner: Runner, options: dict) -> dict:
    return {
        "type": "meta", "version": META_VERSION, "harness_ablate": __version__,
        "repo": plan.info.name, "repo_root": str(plan.info.root), "project_rel": plan.info.project_rel,
        "commit": plan.info.commit, "runner": runner.name, "model": runner.model,
        "tasks_path": plan.tasks_path, "tasks": [t.id for t in plan.tasks],
        "task_defs": [t.to_dict() for t in plan.tasks], "setup": plan.setup, "repeats": plan.repeats,
        "pieces": [p.to_dict() for p in plan.pieces], "variants": [v.to_dict() for v in plan.variants],
        "options": options, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def plan_from_meta(meta: dict, allow_dirty: bool = False) -> Plan:
    info = inspect_repo(Path(meta["repo_root"]) / meta["project_rel"], meta["commit"])
    plan = Plan(info=info, tasks=[Task(**t) for t in meta["task_defs"]], setup=meta.get("setup"),
                tasks_path=meta["tasks_path"], pieces=[Piece(**p) for p in meta["pieces"]],
                variants=[Variant(**v) for v in meta["variants"]], repeats=meta["repeats"])
    with worktree(info, allow_dirty=allow_dirty) as wd:
        now = {p.id: p.tokens for p in discover(wd)}
    then = {p.id: p.tokens for p in plan.pieces}
    if now != then:
        raise PlanError("the harness changed since this run started (untracked harness files differ); "
                        "start a fresh run instead of resuming")
    return plan


@dataclass
class Progress:
    total: int
    done: int = 0  # recorded this session
    skipped: int = 0  # already in results.jsonl
    spent: float = 0.0  # charged against --max-cost, including earlier sessions
    stopped_for_cost: bool = False
    aborted: bool = False
    records: list[dict] = field(default_factory=list)


class Engine:
    def __init__(self, plan: Plan, runner: Runner, results: str | Path, *, jobs: int = 2,
                 max_cost: float | None = 20.0, max_run_cost: float | None = None, allow_dirty: bool = False,
                 on_start: Callable[[str], None] | None = None,
                 on_record: Callable[[dict, Progress], None] | None = None):
        self.plan, self.runner, self.results = plan, runner, Path(results)
        self.jobs = max(1, jobs)
        self.max_cost = max_cost
        self.max_run_cost = max_run_cost if max_run_cost is not None else round(
            runner.estimate_cost_per_run() * MAX_RUN_COST_FACTOR, 2)
        self.allow_dirty = allow_dirty
        self.on_start, self.on_record = on_start, on_record
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reserved = 0.0

    # -- budget -------------------------------------------------------------
    def _claim(self, progress: Progress) -> float | None:
        """Reserve the per-run budget, or None if --max-cost can't cover another run."""
        if self.max_cost is None:
            return self.max_run_cost
        available = self.max_cost - progress.spent - self._reserved
        if available + 1e-9 < self.max_run_cost:
            progress.stopped_for_cost = True
            return None
        self._reserved += self.max_run_cost
        return self.max_run_cost

    # -- one run ------------------------------------------------------------
    def _execute(self, variant: Variant, task: Task, repeat: int, budget: float | None) -> dict:
        t0 = time.monotonic()
        with worktree(self.plan.info, allow_dirty=self.allow_dirty) as wd:
            apply_variant(variant, wd, self.plan.pieces)
            res: RunResult | None = None
            if self.plan.setup:
                setup = run_command(self.plan.setup, wd, timeout=task.timeout_s)
                if not setup.ok:
                    res = RunResult(error=f"setup failed: {setup.output[-300:]}", error_kind=INFRA)
            if res is None:
                res = self.runner.run(task, wd, task.timeout_s, task.max_turns, repeat=repeat, budget_usd=budget)
            check_output = ""
            if res.error_kind is None and not self._stop.is_set():
                chk = run_check(task.check, wd, timeout=max(60, task.timeout_s))
                res.passed, check_output = chk.ok, chk.output[-500:]
        charged = res.cost_usd
        if res.error_kind == TIMEOUT and budget:
            charged = max(charged, budget)  # spend unknown: assume the cap was hit
        return {"type": "run", "run_key": run_key(variant.id, task.id, repeat), "variant": variant.id,
                "task": task.id, "repeat": repeat, **res.to_dict(), "charged_usd": round(charged, 6),
                "check_output": check_output, "elapsed_s": round(time.monotonic() - t0, 2),
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def _append(self, record: dict) -> None:
        with self.results.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
            f.flush()
            os.fsync(f.fileno())

    # -- main loop ----------------------------------------------------------
    def run(self, done_keys: set[str] | None = None, prior_spent: float = 0.0) -> Progress:
        done_keys = done_keys or set()
        pending = [r for r in self.plan.runs if run_key(r[0].id, r[1].id, r[2]) not in done_keys]
        progress = Progress(total=len(self.plan.runs), skipped=len(self.plan.runs) - len(pending), spent=prior_spent)
        queue = list(reversed(pending))

        def worker():
            while not self._stop.is_set():
                with self._lock:
                    if not queue:
                        return
                    budget = self._claim(progress)
                    if budget is None:
                        return
                    variant, task, repeat = queue.pop()
                if self.on_start:
                    self.on_start(run_key(variant.id, task.id, repeat))
                try:
                    record = self._execute(variant, task, repeat, budget)
                except Exception as e:  # a bug or git failure: record it, keep going
                    record = {"type": "run", "run_key": run_key(variant.id, task.id, repeat), "variant": variant.id,
                              "task": task.id, "repeat": repeat, **RunResult(error=f"{type(e).__name__}: {e}",
                              error_kind=INFRA).to_dict(), "charged_usd": 0.0}
                with self._lock:
                    if self.max_cost is not None:
                        self._reserved -= budget
                    if self._stop.is_set():
                        return  # aborted mid-run: don't record a half-finished run
                    self._append(record)
                    progress.done += 1
                    progress.spent += record["charged_usd"]
                    progress.records.append(record)
                if self.on_record:
                    self.on_record(record, progress)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(self.jobs)]
        for t in threads:
            t.start()
        try:
            while any(t.is_alive() for t in threads):
                for t in threads:
                    t.join(timeout=0.2)
        except KeyboardInterrupt:
            self.abort()
            for t in threads:
                t.join(timeout=30)
            progress.aborted = True
        return progress

    def abort(self) -> None:
        self._stop.set()
        kill_all()


def start(plan: Plan, runner: Runner, results: str | Path, options: dict, **kw) -> Progress:
    results = Path(results)
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(json.dumps(meta_record(plan, runner, options)) + "\n", encoding="utf-8")
    cleanup_stale(plan.info.root)
    return Engine(plan, runner, results, allow_dirty=options.get("allow_dirty", False), **kw).run()


def resume(results: str | Path, runner: Runner, **kw) -> tuple[Plan, Progress]:
    meta, records = load_results(results)
    plan = plan_from_meta(meta, allow_dirty=meta["options"].get("allow_dirty", False))
    done = {r["run_key"] for r in records}
    spent = sum(r.get("charged_usd", r.get("cost_usd", 0.0)) for r in records)
    cleanup_stale(plan.info.root)
    engine = Engine(plan, runner, results, allow_dirty=meta["options"].get("allow_dirty", False), **kw)
    return plan, engine.run(done_keys=done, prior_spent=spent)
