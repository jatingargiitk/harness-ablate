"""results.jsonl -> report.md + results.csv."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .scoring import CUT, HARMFUL, KEEP, NEUTRAL, NO_DATA, Scores, VariantStats, score


class ResultsError(ValueError):
    pass


def load_results(path: str | Path) -> tuple[dict, list[dict]]:
    """Return (meta, run records). Later records for the same run_key win; a torn last line is ignored."""
    path = Path(path)
    meta, runs = None, {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                continue  # killed mid-write
            raise ResultsError(f"{path}:{i + 1}: not valid JSON") from None
        if rec.get("type") == "meta":
            meta = rec
        elif rec.get("type") == "run":
            runs[rec["run_key"]] = rec
    if meta is None:
        raise ResultsError(f"{path}: no meta record; was it written by harness-ablate run?")
    return meta, list(runs.values())


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def pts(x: float | None) -> str:
    if x is None:
        return "—"
    v = round(x * 100)
    return f"{v:+d} pts" if v else "0 pts"


def num(x: float | None) -> str:
    if x is None:
        return "—"
    a = abs(x)
    s = f"{a / 1000:.1f}k" if a >= 1000 else f"{a:.0f}"
    return ("-" if x < 0 else "") + s


def money(x: float | None) -> str:
    if x is None:
        return "—"
    return f"-${abs(x):.3f}" if x < 0 else f"${x:.3f}"


def piece_cost(s: VariantStats) -> str:
    return "—" if not s.piece_tokens else f"{s.piece_tokens:,}"


def pass_cell(s: VariantStats) -> str:
    return "—" if s.pass_rate is None else f"{pct(s.pass_rate)} ({s.passes}/{s.valid})"


def saved_cell(s: VariantStats, base: VariantStats) -> str:
    if s.tokens_saved is None:
        return "—"
    p = round(s.tokens_saved / base.tokens * 100) if base.tokens else 0
    return f"{num(s.tokens_saved)}" + (f" ({p:+d}%)" if p else "")


def verdict_cell(s: VariantStats) -> str:
    v = f"**{s.verdict}**" if s.verdict in (HARMFUL, CUT, KEEP) else s.verdict
    return v + (" · LOW CONFIDENCE" if s.low_confidence and s.verdict != NO_DATA else "")


def runs_cell(s: VariantStats) -> str:
    extra = []
    if s.infra_errors:
        extra.append(f"{s.infra_errors} infra err")
    if s.timeouts:
        extra.append(f"{s.timeouts} timeout")
    return f"{s.valid}" + (f" ({', '.join(extra)})" if extra else "")


def code(piece: str) -> str:
    return f"`{piece}`"


def todo(scores: Scores) -> list[str]:
    base = scores.baseline
    items = []
    unsure = " Low confidence: confirm with more repeats first."
    for s in scores.pieces:
        if s.verdict == HARMFUL:
            items.append(f"**Remove or rewrite {code(s.piece)}.** Without it the pass rate goes from "
                         f"{pct(base.pass_rate)} to {pct(s.pass_rate)} ({pts(s.delta)})."
                         + (unsure if s.low_confidence else ""))
    cuts = [s for s in scores.pieces if s.verdict == CUT]
    for s in cuts:
        saves = []
        if (s.tokens_saved or 0) > 0:
            saves.append(f"{num(s.tokens_saved)} tokens")
        if (s.cost_saved or 0) > 0:
            saves.append(money(s.cost_saved))
        items.append(f"**Cut {code(s.piece)}.** No measurable effect on pass rate; removing it saves "
                     f"{' and '.join(saves)} per run." + (unsure if s.low_confidence else ""))
    keeps = [s for s in scores.pieces if s.verdict == KEEP]
    if keeps:
        items.append("**Keep** " + ", ".join(f"{code(s.piece)} ({pts(s.delta)} without it)" for s in keeps) + ".")
    neutral = [s for s in scores.pieces if s.verdict == NEUTRAL]
    unsure = [s for s in neutral if abs(s.delta or 0) >= scores.band / 2]
    flat = [s for s in neutral if s not in unsure]
    for s in unsure:
        items.append(f"{code(s.piece)} moved the pass rate {pts(s.delta)} when removed, inside the "
                     f"±{scores.band * 100:.0f} pt noise band. More repeats would settle it.")
    if flat:
        items.append("No measurable effect, little cost (keep or cut, your call): "
                     + ", ".join(code(s.piece) for s in flat) + ".")
    if scores.bare and scores.bare.delta is not None and scores.bare.delta >= 0:
        items.append(f"The whole harness isn't paying for itself on these tasks: with no harness at all the "
                     f"pass rate is {pct(scores.bare.pass_rate)} vs {pct(base.pass_rate)} with it.")
    if any(s.low_confidence for s in scores.pieces) or base.low_confidence:
        items.append("Rows marked LOW CONFIDENCE have fewer than 3 complete repeats. Re-run with "
                     "`--repeats 3` before deleting anything you care about.")
    no_data = [s for s in scores.pieces if s.verdict == NO_DATA]
    if no_data:
        items.append("No completed runs for " + ", ".join(code(s.piece) for s in no_data)
                     + " (stopped by --max-cost?). `harness-ablate resume` finishes them.")
    return items


def render_markdown(meta: dict, scores: Scores) -> str:
    base = scores.baseline
    tasks = meta["tasks"]
    out = [f"# harness-ablate report: {meta['repo']}", ""]
    head = [
        ("repo", f"{meta['repo']}" + (f" (`{meta['project_rel']}/`)" if meta.get("project_rel") else "")),
        ("commit", f"`{meta['commit'][:12]}`"),
        ("model", f"{meta['model']} via {meta['runner']}"),
        ("date", meta["started_at"][:10]),
        ("tasks", str(len(tasks))),
        ("repeats", str(meta["repeats"])),
        ("total runs", str(scores.total_runs)),
        ("total cost", f"${scores.total_cost:.2f}"),
    ]
    out += [f"- **{k}:** {v}" for k, v in head]
    if meta.get("options", {}).get("isolate_user"):
        out.append("- **user-level harness:** excluded (`--isolate-user`)")
    else:
        out.append("- **user-level harness:** loaded in every run, not ablated")
    out += ["", f"Baseline (full harness) passes **{pass_cell(base)}** of runs. "
            f"Noise band: ±{scores.band * 100:.0f} pts; a piece needs a bigger swing than that to count.", ""]
    out += ["| piece | tokens it costs | pass rate without it | delta | tokens saved/run | runs | verdict |",
            "|---|---:|---:|---:|---:|---:|---|"]
    for s in scores.pieces:
        out.append(f"| {code(s.piece)} | {piece_cost(s)} | {pass_cell(s)} | {pts(s.delta)} | "
                   f"{saved_cell(s, base)} | {runs_cell(s)} | {verdict_cell(s)} |")
    out.append(f"| *baseline (full harness)* | {sum(p['tokens'] for p in meta['pieces']):,} | "
               f"{pass_cell(base)} | — | — | {runs_cell(base)} | |")
    if scores.bare:
        b = scores.bare
        out.append(f"| *bare (no harness)* | 0 | {pass_cell(b)} | {pts(b.delta)} | {saved_cell(b, base)} | "
                   f"{runs_cell(b)} | |")
    out += ["", "## What to do", ""]
    out += [f"{i}. {item}" for i, item in enumerate(todo(scores), 1)] or ["Nothing stands out."]
    out += ["", "## Per-task passes", "", "| variant | " + " | ".join(f"`{t}`" for t in tasks) + " |",
            "|---|" + "---:|" * len(tasks)]
    rows = [("baseline", base)] + [(s.piece, s) for s in scores.pieces] + ([("bare", scores.bare)] if scores.bare else [])
    for label, s in rows:
        cells = [f"{p}/{n}" if n else "—" for p, n in (s.per_task.get(t, (0, 0)) for t in tasks)]
        out.append(f"| {code(label) if label not in ('baseline', 'bare') else '*' + label + '*'} | " + " | ".join(cells) + " |")
    out += ["", "## Cost and speed per run", "", "| variant | mean tokens | mean cost | mean turns | mean wall time |",
            "|---|---:|---:|---:|---:|"]
    for label, s in rows:
        name = code(label) if label not in ("baseline", "bare") else f"*{label}*"
        out.append(f"| {name} | {num(s.tokens)} | ${s.cost:.3f} | {s.turns:.1f} | {s.wall_s:.0f}s |")
    out += ["", "<sub>Each minus-one row removes exactly one piece from the baseline harness in a fresh git worktree. "
            "Pass rate excludes infra errors (API/CLI failures); timeouts count as fails. "
            "Tokens include cache reads and writes.</sub>", ""]
    return "\n".join(out)


CSV_FIELDS = ["variant", "piece", "verdict", "low_confidence", "runs", "valid", "infra_errors", "timeouts",
              "repeats", "pass_rate", "delta", "piece_tokens", "mean_tokens", "tokens_saved", "mean_cost_usd",
              "cost_saved_usd", "mean_wall_s", "mean_turns"]


def write_csv(scores: Scores, path: str | Path) -> None:
    rows = [scores.baseline] + scores.pieces + ([scores.bare] if scores.bare else [])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)
        for s in rows:
            w.writerow([s.variant, s.piece or "", s.verdict or "", s.low_confidence, s.runs, s.valid,
                        s.infra_errors, s.timeouts, s.repeats,
                        "" if s.pass_rate is None else round(s.pass_rate, 4),
                        "" if s.delta is None else round(s.delta, 4), s.piece_tokens or "",
                        round(s.tokens, 1), "" if s.tokens_saved is None else round(s.tokens_saved, 1),
                        round(s.cost, 6), "" if s.cost_saved is None else round(s.cost_saved, 6),
                        round(s.wall_s, 2), round(s.turns, 2)])


def write_report(results: str | Path, out_md: str | Path, out_csv: str | Path | None = None) -> Scores:
    meta, records = load_results(results)
    scores = score(meta, records)
    Path(out_md).write_text(render_markdown(meta, scores), encoding="utf-8")
    if out_csv:
        write_csv(scores, out_csv)
    return scores
