"""harness-ablate command-line interface."""

from __future__ import annotations

import json
from pathlib import Path

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


if __name__ == "__main__":
    app()
