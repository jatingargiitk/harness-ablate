import shutil
from datetime import datetime, timezone
from pathlib import Path

from harness_ablate.check import run_check
from harness_ablate.harness import discover
from harness_ablate.tasks import Task
from harness_ablate.variants import apply_variant, build_variants

TASK_IDS = ["t1", "t2", "t3", "t4", "t5"]


def tasks(n=5):
    return [Task(id=f"t{i}", prompt="fix it", check="test -f .fake_pass") for i in range(1, n + 1)]


def meta_for(pieces, variants, task_list, repeats, runner="fake"):
    return {"type": "meta", "version": 1, "repo": "demo", "project_rel": "", "commit": "0" * 40,
            "model": "fake", "runner": runner, "tasks_path": "tasks.yaml", "tasks": [t.id for t in task_list],
            "repeats": repeats, "pieces": [p.to_dict() for p in pieces],
            "variants": [v.to_dict() for v in variants], "options": {"isolate_user": True},
            "started_at": datetime.now(timezone.utc).isoformat()}


def simulate(project: Path, runner, tmp: Path, repeats=3, task_list=None):
    """Run every variant x task x repeat with ``runner`` in throwaway copies. Returns (meta, records)."""
    task_list = task_list or tasks()
    pieces = discover(project)
    variants = build_variants(pieces)
    records = []
    for repeat in range(repeats):
        for t in task_list:
            for v in variants:
                wd = tmp / f"{v.id.replace(':', '_').replace('/', '_')}-{t.id}-{repeat}"
                shutil.copytree(project, wd)
                apply_variant(v, wd, pieces)
                res = runner.run(t, wd, t.timeout_s, None, repeat=repeat)
                if res.error_kind is None:
                    res.passed = run_check(t.check, wd).ok
                records.append({"type": "run", "run_key": f"{v.id}|{t.id}|{repeat}", "variant": v.id,
                                "task": t.id, "repeat": repeat, **res.to_dict()})
                shutil.rmtree(wd)
    return meta_for(pieces, variants, task_list, repeats), records
