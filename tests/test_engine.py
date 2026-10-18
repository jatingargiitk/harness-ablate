import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter

import pytest
from conftest import sh
from typer.testing import CliRunner

from harness_ablate.cli import app
from harness_ablate.engine import Engine, PlanError, make_plan, resume, start
from harness_ablate.report import load_results
from harness_ablate.runners.fake import FakeRunner
from harness_ablate.tasks import TaskError, load_tasks

TASKS = """setup: "true"
tasks:
""" + "".join(f"""  - id: t{i}
    prompt: fix bug {i}
    check: test -f .fake_pass
    timeout_s: 60
""" for i in range(1, 4))


def commit_all(root):
    sh(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], root)
    sh(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "tasks"], root)


@pytest.fixture
def tasks_file(repo):
    path = repo / "tasks.yaml"
    path.write_text(TASKS)
    commit_all(repo.parent)
    return path


OPTS = {"isolate_user": True, "allow_dirty": False}


def test_plan_counts_and_dirty_refusal(tasks_file, repo):
    plan = make_plan(tasks_file, repeats=2)
    assert plan.info.project_rel == "proj"
    assert len(plan.variants) == len(plan.pieces) + 2
    assert len(plan.runs) == len(plan.variants) * 3 * 2
    assert [r[2] for r in plan.runs[: len(plan.variants) * 3]] == [0] * (len(plan.variants) * 3)  # repeat-major
    assert [v.id for v in make_plan(tasks_file, only=['claude_md:"## Style"'], bare=False).variants] == \
        ["baseline", 'minus:claude_md:"## Style"']
    with pytest.raises(PlanError, match="matched no pieces"):
        make_plan(tasks_file, only=["nope"])
    (repo / "CLAUDE.md").write_text("changed\n")
    with pytest.raises(PlanError, match="uncommitted"):
        make_plan(tasks_file)
    assert len(make_plan(tasks_file, allow_dirty=True).pieces) < len(plan.pieces)


class AbortAfter(FakeRunner):
    def __init__(self, n, **kw):
        super().__init__(**kw)
        self.n, self.engine = n, None

    def run(self, task, workdir, timeout, max_turns, **kw):
        res = super().run(task, workdir, timeout, max_turns, **kw)
        if len(self.calls) >= self.n:
            self.engine.abort()
        return res


def test_abort_then_resume_does_not_redo_completed_runs(tasks_file, tmp_path):
    plan = make_plan(tasks_file, repeats=2)
    out = tmp_path / "results.jsonl"
    runner = AbortAfter(7)
    from harness_ablate.engine import meta_record
    out.write_text(json.dumps(meta_record(plan, runner, OPTS)) + "\n")
    engine = Engine(plan, runner, out, jobs=1, max_cost=None)
    runner.engine = engine
    prog = engine.run()
    _, first = load_results(out)
    assert prog.done == 6 == len(first)  # the 7th was in flight when aborted: not recorded

    second = FakeRunner()
    _, prog2 = resume(out, second, jobs=2, max_cost=None)
    _, records = load_results(out)
    keys = Counter(json.loads(l)["run_key"] for l in out.read_text().splitlines()[1:])
    assert len(records) == len(plan.runs) and max(keys.values()) == 1
    done_first = {(r["task"], r["repeat"], r["variant"]) for r in first}
    assert len(second.calls) == len(plan.runs) - 6
    assert prog2.skipped == 6
    assert not any((r["task"], r["repeat"], r["variant"]) in done_first
                   for r in prog2.records)


def test_max_cost_is_a_hard_stop(tasks_file, tmp_path):
    plan = make_plan(tasks_file, repeats=3)
    out = tmp_path / "r.jsonl"
    prog = start(plan, FakeRunner(), out, OPTS, jobs=2, max_cost=1.0, max_run_cost=0.15)
    assert prog.stopped_for_cost and 0 < prog.done < len(plan.runs)
    assert prog.spent <= 1.0
    # resuming with a higher cap finishes the rest
    _, prog2 = resume(out, FakeRunner(), jobs=2, max_cost=None)
    assert prog.done + prog2.done == len(plan.runs)


def test_setup_failure_is_infra_and_timeouts_charge_the_cap(tasks_file, tmp_path):
    plan = make_plan(tasks_file, repeats=1, only=["hook:Stop"])
    plan.setup = "exit 3"
    prog = start(plan, FakeRunner(), tmp_path / "a.jsonl", OPTS, jobs=1, max_cost=None)
    assert all(r["error_kind"] == "infra" and "setup failed" in r["error"] for r in prog.records)
    plan.setup = None
    runner = FakeRunner(timeouts={("t1", 0)})
    prog = start(plan, runner, tmp_path / "b.jsonl", OPTS, jobs=1, max_cost=50, max_run_cost=0.5)
    timed = [r for r in prog.records if r["error_kind"] == "timeout"]
    assert len(timed) == len(plan.variants) and all(r["charged_usd"] == 0.5 and not r["passed"] for r in timed)


def test_tasks_validation(tmp_path):
    p = tmp_path / "tasks.yaml"
    p.write_text("tasks:\n  - id: a\n    prompt: x\n")
    with pytest.raises(TaskError, match="missing check"):
        load_tasks(p)
    p.write_text("tasks:\n  - {id: a, prompt: x, check: y}\n  - {id: a, prompt: x, check: y}\n")
    with pytest.raises(TaskError, match="duplicate"):
        load_tasks(p)
    p.write_text("timeout_s: 90\nmax_turns: 9\ntasks:\n  - {id: a, prompt: x, check: y, timeout_s: 5}\n  - {id: b, prompt: x, check: y}\n")
    tf = load_tasks(p)
    assert [(t.timeout_s, t.max_turns) for t in tf.tasks] == [(5, 9), (90, 9)]
    p.write_text("tasks: []\n")
    with pytest.raises(TaskError):
        load_tasks(p)


def test_cli_plan_and_run_with_fake_runner(tasks_file, tmp_path):
    cli = CliRunner()
    res = cli.invoke(app, ["plan", str(tasks_file), "--repeats", "1", "--model", "sonnet"])
    assert res.exit_code == 0, res.output
    assert "runs" in res.output and "$" in res.output
    out = tmp_path / "res" / "results.jsonl"
    res = cli.invoke(app, ["run", str(tasks_file), "--runner", "fake", "--repeats", "1", "-o", str(out)])
    assert res.exit_code == 1 and "--yes" in res.output  # non-interactive without --yes
    res = cli.invoke(app, ["run", str(tasks_file), "--runner", "fake", "--repeats", "1", "-o", str(out), "--yes"])
    assert res.exit_code == 0, res.output
    assert (out.parent / "report.md").exists() and (out.parent / "results.csv").exists()
    assert 'HARMFUL' in res.output and '## Workflow' in res.output  # "Never run the tests."
    res = cli.invoke(app, ["run", str(tasks_file), "--runner", "fake", "-o", str(out), "--yes"])
    assert res.exit_code == 1 and "resume" in res.output
    res = cli.invoke(app, ["report", str(out), "-o", str(tmp_path / "r.md")])
    assert res.exit_code == 0 and "HARMFUL" in (tmp_path / "r.md").read_text()


def test_kill_midway_then_resume_for_real(tasks_file, tmp_path):
    """SIGKILL the CLI mid-run, then resume: completed runs are not redone."""
    out = tmp_path / "results.jsonl"
    exe = [sys.executable, "-m", "harness_ablate.cli"]
    env = {**os.environ, "HARNESS_ABLATE_FAKE_DELAY": "0.15"}
    proc = subprocess.Popen(exe + ["run", str(tasks_file), "--runner", "fake", "--repeats", "2", "-j", "2",
                                   "-o", str(out), "--yes"], env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + 60
    while time.time() < deadline:
        if out.exists() and len(out.read_text().splitlines()) >= 9:
            break
        time.sleep(0.05)
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()
    before = [json.loads(l)["run_key"] for l in out.read_text().splitlines()[1:] if l.endswith("}")]
    meta, _ = load_results(out)
    total = len(meta["variants"]) * len(meta["tasks"]) * 2
    assert 8 <= len(before) < total
    res = subprocess.run(exe + ["resume", str(out), "--yes"], env={**os.environ}, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    keys = [json.loads(l)["run_key"] for l in out.read_text().splitlines()[1:] if l.strip().endswith("}")]
    assert len(set(keys)) == total and len(keys) == total  # nothing redone, nothing missing
    assert keys[: len(before)] == before
    listed = subprocess.run(["git", "worktree", "list"], cwd=tasks_file.parent.parent, capture_output=True, text=True).stdout
    assert len(listed.strip().splitlines()) == 1  # killed run's worktrees were pruned on resume
