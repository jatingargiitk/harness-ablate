"""harness-ablate command-line interface."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .harness import discover, user_level_harness

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Find out which parts of your CLAUDE.md, skills and hooks still help on today's model.",
)
console = Console()
err = Console(stderr=True)


def fail(msg: str) -> None:
    err.print(f"[bold red]error:[/] {msg}")
    raise typer.Exit(1)


def warn_user_harness(isolated: bool = False) -> None:
    found = user_level_harness()
    if not found:
        return
    if isolated:
        err.print("[dim]User-level harness excluded from runs (--isolate-user): " + ", ".join(found) + "[/]")
    else:
        err.print(
            "[yellow]warning:[/] your user-level harness loads in every run and is not ablated in v0.1: "
            + ", ".join(found)
            + ". Pass --isolate-user to exclude it."
        )


@app.callback(invoke_without_command=True)
def _main(version: bool = typer.Option(False, "--version", help="Show version and exit.")) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def scan(
    project: Path = typer.Option(Path("."), "--project", "-C", help="Project directory (where CLAUDE.md lives)."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of a table."),
) -> None:
    """List every harness piece: id, rough token cost, and where it lives."""
    if not project.is_dir():
        fail(f"not a directory: {project}")
    pieces = discover(project)
    if as_json:
        typer.echo(json.dumps([p.to_dict() for p in pieces], indent=2))
        return
    if not pieces:
        console.print("No harness found (no CLAUDE.md, AGENTS.md, .claude/skills or hooks in .claude/settings.json).")
        return
    table = Table(title=f"Harness in {project.resolve()}", title_justify="left", header_style="bold")
    table.add_column("piece")
    table.add_column("tokens", justify="right")
    table.add_column("where")
    for p in pieces:
        where = p.path + (f":{p.detail['lines'][0]}-{p.detail['lines'][1]}" if "lines" in p.detail else "")
        if p.kind == "hook" and p.detail.get("commands"):
            where += "  " + "; ".join(p.detail["commands"])[:60]
        table.add_row(p.id, f"{p.tokens:,}" if p.tokens else "—", where)
    console.print(table)
    total = sum(p.tokens for p in pieces)
    console.print(f"{len(pieces)} pieces, ~{total:,} tokens of project harness")
    warn_user_harness()


RUNNERS = ["claude", "fake"]


def make_runner(name: str, model: str | None, isolate_user: bool, cost_per_run: float | None):
    if name == "fake":
        from .runners.fake import FakeRunner
        r = FakeRunner(model=model or "fake", delay_s=float(os.environ.get("HARNESS_ABLATE_FAKE_DELAY", "0")))
        if cost_per_run is not None:
            r.estimate_cost_per_run = lambda: cost_per_run  # type: ignore[method-assign]
        return r
    if name == "claude":
        from .runners.claude import ClaudeNotFound, ClaudeRunner
        try:
            return ClaudeRunner(model, isolate_user=isolate_user, cost_per_run=cost_per_run)
        except ClaudeNotFound as e:
            fail(f"{e}. Install Claude Code (https://docs.claude.com/en/docs/claude-code) or use --runner fake.")
    fail(f"unknown runner {name!r}; choose from {', '.join(RUNNERS)}")


def build_plan(tasks_file: Path, project: Path | None, repeats: int, only: list[str] | None, bare: bool,
               commit: str | None, allow_dirty: bool):
    from .engine import PlanError, make_plan
    from .tasks import TaskError
    from .worktree import GitError
    if repeats < 1:
        fail("--repeats must be at least 1")
    try:
        return make_plan(tasks_file, project, repeats=repeats, only=only or None, bare=bare, commit=commit,
                         allow_dirty=allow_dirty)
    except (PlanError, TaskError, GitError) as e:
        fail(str(e))


def show_plan(plan, runner, jobs: int, max_cost: float | None, max_run_cost: float | None) -> float:
    est = runner.estimate_cost_per_run()
    n = len(plan.runs)
    info = plan.info
    where = f"{info.name}" + (f"/{info.project_rel}" if info.project_rel else "")
    console.print(f"[bold]{where}[/] @ {info.commit[:12]} · runner [bold]{runner.name}[/] · model [bold]{runner.model}[/]")
    table = Table(header_style="bold", title_justify="left")
    table.add_column("variant")
    table.add_column("removes", justify="right")
    by_id = {p.id: p for p in plan.pieces}
    for v in plan.variants:
        tokens = sum(by_id[p].tokens for p in v.removed)
        table.add_row(v.label, f"{len(v.removed)} piece{'s' if len(v.removed) != 1 else ''}, ~{tokens:,} tok" if v.removed else "—")
    console.print(table)
    console.print(f"{len(plan.variants)} variants × {len(plan.tasks)} tasks × {plan.repeats} repeats = "
                  f"[bold]{n} runs[/], {jobs} at a time")
    cap = f"; --max-cost ${max_cost:.2f} stops it early" if max_cost is not None else ""
    console.print(f"Estimated cost: [bold]~${n * est:.2f}[/] (~${est:.2f}/run, a rough guess{cap})")
    if max_run_cost is not None:
        console.print(f"Each run is capped at ${max_run_cost:.2f}.")
    if info.harness_untracked:
        console.print(f"[dim]Untracked harness files copied into every worktree: {', '.join(info.harness_untracked)}[/]")
    if info.other_dirty:
        err.print("[yellow]note:[/] uncommitted non-harness changes are not included; runs use commit "
                  f"{info.commit[:12]}.")
    return n * est


@app.command()
def plan(
    tasks_file: Path = typer.Argument(..., help="tasks.yaml"),
    project: Optional[Path] = typer.Option(None, "--project", "-C", help="Project dir (default: the tasks file's directory)."),
    repeats: int = typer.Option(3, "--repeats", "-r"),
    jobs: int = typer.Option(2, "--jobs", "-j"),
    max_cost: Optional[float] = typer.Option(20.0, "--max-cost"),
    model: Optional[str] = typer.Option(None, "--model"),
    only: Optional[list[str]] = typer.Option(None, "--only", help="Only ablate pieces matching this id, kind or id prefix (repeatable)."),
    no_bare: bool = typer.Option(False, "--no-bare", help="Skip the no-harness variant."),
    runner_name: str = typer.Option("claude", "--runner"),
    cost_per_run: Optional[float] = typer.Option(None, "--cost-per-run", help="Override the per-run $ estimate."),
    commit: Optional[str] = typer.Option(None, "--commit", help="Commit to test (default HEAD)."),
    allow_dirty: bool = typer.Option(False, "--allow-dirty"),
    isolate_user: bool = typer.Option(False, "--isolate-user"),
) -> None:
    """Show the variants, run count and cost estimate. Makes no API calls."""
    p = build_plan(tasks_file, project, repeats, only, not no_bare, commit, allow_dirty)
    if runner_name == "claude":  # estimate only; doesn't need the CLI installed
        from types import SimpleNamespace

        from .runners.claude import estimate_cost_per_run
        runner = SimpleNamespace(name="claude", model=model or "default",
                                 estimate_cost_per_run=lambda: estimate_cost_per_run(model, cost_per_run))
    else:
        runner = make_runner(runner_name, model, isolate_user, cost_per_run)
    show_plan(p, runner, jobs, max_cost, None)
    warn_user_harness(isolate_user)


def progress_ui(total: int, already: int):
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
    bar = Progress(TextColumn("[bold]{task.description}"), BarColumn(), MofNCompleteColumn(),
                   TextColumn("{task.fields[status]}"), TimeElapsedColumn(), console=console)
    tid = bar.add_task("runs", total=total, completed=already, status="")
    marks = {True: "[green]pass[/]", False: "[red]fail[/]"}

    def on_record(rec: dict, prog) -> None:
        tag = f"[yellow]{rec['error_kind']}[/]" if rec.get("error_kind") else marks[bool(rec["passed"])]
        bar.console.print(f"  {tag:<18} {rec['variant']}  {rec['task']}  r{rec['repeat']}  "
                          f"[dim]{rec['turns']} turns · ${rec['cost_usd']:.3f} · {rec['wall_s']:.0f}s[/]")
        bar.update(tid, advance=1, status=f"${prog.spent:.2f} spent")

    return bar, on_record


def finish(results: Path, prog) -> None:
    from .report import write_report
    out_dir = results.parent
    scores = write_report(results, out_dir / "report.md", out_dir / "results.csv")
    if prog.aborted:
        err.print(f"[yellow]Interrupted.[/] Completed runs are saved; continue with: harness-ablate resume {results}")
    elif prog.stopped_for_cost:
        err.print(f"[yellow]Stopped at --max-cost[/] (${prog.spent:.2f} charged). Continue with: "
                  f"harness-ablate resume {results} --max-cost <higher>")
    console.print(f"Wrote {out_dir / 'report.md'}, {out_dir / 'results.csv'}, {results}")
    for s in scores.pieces:
        if s.verdict in ("HARMFUL", "CUT", "KEEP"):
            colour = {"HARMFUL": "red", "CUT": "yellow", "KEEP": "green"}[s.verdict]
            console.print(f"  [{colour}]{s.verdict:<8}[/] {s.piece}  ({'+' if (s.delta or 0) >= 0 else ''}{(s.delta or 0) * 100:.0f} pts)")


def confirm_or_exit(yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty():
        fail("not a terminal; pass --yes to confirm the cost")
    if not typer.confirm("Run it?", default=False):
        raise typer.Exit(1)


@app.command()
def run(
    tasks_file: Path = typer.Argument(..., help="tasks.yaml"),
    project: Optional[Path] = typer.Option(None, "--project", "-C", help="Project dir (default: the tasks file's directory)."),
    repeats: int = typer.Option(3, "--repeats", "-r"),
    jobs: int = typer.Option(2, "--jobs", "-j"),
    max_cost: Optional[float] = typer.Option(20.0, "--max-cost", help="Hard stop: no new runs once this much is spent."),
    max_run_cost: Optional[float] = typer.Option(None, "--max-run-cost", help="Per-run cap (default 5x the estimate)."),
    model: Optional[str] = typer.Option(None, "--model"),
    only: Optional[list[str]] = typer.Option(None, "--only", help="Only ablate pieces matching this id, kind or id prefix (repeatable)."),
    no_bare: bool = typer.Option(False, "--no-bare", help="Skip the no-harness variant."),
    runner_name: str = typer.Option("claude", "--runner"),
    cost_per_run: Optional[float] = typer.Option(None, "--cost-per-run", help="Override the per-run $ estimate."),
    commit: Optional[str] = typer.Option(None, "--commit", help="Commit to test (default HEAD)."),
    allow_dirty: bool = typer.Option(False, "--allow-dirty", help="Test uncommitted harness edits."),
    isolate_user: bool = typer.Option(False, "--isolate-user", help="Don't load ~/.claude settings, CLAUDE.md, hooks or MCP."),
    out: Path = typer.Option(Path("harness-ablate-results/results.jsonl"), "--out", "-o"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing results file."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cost confirmation."),
) -> None:
    """Run every variant on every task in throwaway worktrees and write the report."""
    from .engine import start
    if out.exists() and not force:
        fail(f"{out} exists. Use `harness-ablate resume {out}` to continue it, or --force to start over.")
    p = build_plan(tasks_file, project, repeats, only, not no_bare, commit, allow_dirty)
    runner = make_runner(runner_name, model, isolate_user, cost_per_run)
    max_run_cost = max_run_cost if max_run_cost is not None else round(runner.estimate_cost_per_run() * 5, 2)
    if max_cost is not None and max_run_cost > max_cost:
        fail(f"--max-cost ${max_cost:.2f} is below the per-run cap ${max_run_cost:.2f}; nothing would run")
    show_plan(p, runner, jobs, max_cost, max_run_cost)
    warn_user_harness(isolate_user)
    confirm_or_exit(yes)
    options = {"jobs": jobs, "max_cost": max_cost, "max_run_cost": max_run_cost, "isolate_user": isolate_user,
               "allow_dirty": allow_dirty, "cost_per_run": cost_per_run, "only": only or [], "bare": not no_bare}
    if runner_name == "claude":
        from .runners.claude import cli_version
        options["claude_version"] = cli_version(runner.binary)
    bar, on_record = progress_ui(len(p.runs), 0)
    with bar:
        prog = start(p, runner, out, options, jobs=jobs, max_cost=max_cost, max_run_cost=max_run_cost,
                     on_record=on_record)
    finish(out, prog)


@app.command()
def resume(
    results: Path = typer.Argument(..., help="results.jsonl from an earlier run"),
    jobs: Optional[int] = typer.Option(None, "--jobs", "-j"),
    max_cost: Optional[float] = typer.Option(None, "--max-cost", help="Total cap including earlier spend (default: the original)."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Finish an interrupted run, skipping runs already recorded."""
    from .engine import PlanError, resume as do_resume
    from .report import ResultsError, load_results
    try:
        meta, records = load_results(results)
    except (ResultsError, FileNotFoundError) as e:
        fail(str(e))
    o = meta["options"]
    runner = make_runner(meta["runner"], meta["model"] if meta["model"] != "default" else None,
                         o.get("isolate_user", False), o.get("cost_per_run"))
    jobs = jobs or o.get("jobs", 2)
    max_cost = max_cost if max_cost is not None else o.get("max_cost")
    done = {r["run_key"] for r in records}
    total = len(meta["variants"]) * len(meta["tasks"]) * meta["repeats"]
    left = total - len(done)
    spent = sum(r.get("charged_usd", r.get("cost_usd", 0.0)) for r in records)
    console.print(f"{len(done)}/{total} runs recorded (${spent:.2f} charged); {left} left, "
                  f"~${left * runner.estimate_cost_per_run():.2f} more.")
    if left == 0:
        from .engine import Progress
        finish(results, Progress(total=total, spent=spent))
        return
    warn_user_harness(o.get("isolate_user", False))
    confirm_or_exit(yes)
    bar, on_record = progress_ui(total, len(done))
    try:
        with bar:
            _, prog = do_resume(results, runner, jobs=jobs, max_cost=max_cost, max_run_cost=o.get("max_run_cost"),
                                on_record=on_record)
    except PlanError as e:
        fail(str(e))
    finish(results, prog)


@app.command()
def report(
    results: Path = typer.Argument(..., help="results.jsonl"),
    out: Path = typer.Option(Path("report.md"), "--out", "-o"),
    csv_out: Optional[Path] = typer.Option(None, "--csv", help="Also write a CSV here."),
) -> None:
    """Rebuild report.md (and optionally a CSV) from results.jsonl."""
    from .report import ResultsError, write_report
    try:
        write_report(results, out, csv_out)
    except (ResultsError, FileNotFoundError) as e:
        fail(str(e))
    console.print(f"Wrote {out}" + (f" and {csv_out}" if csv_out else ""))


if __name__ == "__main__":
    app()
