import csv
import json

from conftest import write_harness
from helpers import meta_for, simulate, tasks

from harness_ablate.report import load_results, render_markdown, write_csv, write_report
from harness_ablate.runners.fake import FakeRunner
from harness_ablate.scoring import CUT, HARMFUL, KEEP, NEUTRAL, NO_DATA, noise_band, score, variant_stats
from harness_ablate.variants import Variant

WORKFLOW = 'claude_md:"## Workflow"'
STYLE = 'claude_md:"## Style"'
TESTING = 'claude_md:"## Testing"'


def project(tmp_path, extra=""):
    p = tmp_path / "proj"
    p.mkdir(parents=True)
    write_harness(p)
    if extra:
        (p / "CLAUDE.md").write_text((p / "CLAUDE.md").read_text() + extra)
    return p


def by_piece(scores):
    return {s.piece: s for s in scores.pieces}


def test_bad_section_is_harmful_and_useful_one_is_keep(tmp_path):
    # Baseline: 0.5 + 0.5 (style) - 1.0 (workflow) = 0 -> every task fails.
    runner = FakeRunner(base_rate=0.5, rules=[(r"never run the tests", -1.0), (r"type hints", 0.5)])
    meta, records = simulate(project(tmp_path), runner, tmp_path / "w")
    scores = score(meta, records)
    rows = by_piece(scores)
    assert scores.baseline.pass_rate == 0.0
    assert rows[WORKFLOW].verdict == HARMFUL and rows[WORKFLOW].pass_rate == 1.0
    assert rows[WORKFLOW].delta == 1.0
    assert scores.pieces[0].piece == WORKFLOW  # HARMFUL sorts first
    assert rows[STYLE].verdict == NEUTRAL  # can't drop below 0%
    assert not rows[WORKFLOW].low_confidence

    # With the bad section gone, style is load-bearing.
    runner = FakeRunner(base_rate=0.0, rules=[(r"type hints", 1.0)])
    meta, records = simulate(project(tmp_path / "b"), runner, tmp_path / "w2")
    rows = by_piece(score(meta, records))
    assert rows[STYLE].verdict == KEEP and rows[STYLE].delta == -1.0
    assert rows[TESTING].verdict == NEUTRAL
    assert rows["hook:Stop[0]"].verdict == NEUTRAL
    assert rows["skill:run-tests"].piece_tokens > 0 and rows["hook:Stop[0]"].piece_tokens == 0


def test_big_useless_section_is_cut(tmp_path):
    filler = "\n## History\n\n" + ("This project was started long ago. " * 600) + "\n"
    runner = FakeRunner(base_rate=1.0, rules=[])
    meta, records = simulate(project(tmp_path, filler), runner, tmp_path / "w", repeats=1)
    scores = score(meta, records)
    rows = by_piece(scores)
    hist = rows['claude_md:"## History"']
    assert hist.verdict == CUT and hist.delta == 0 and hist.tokens_saved > 0
    assert rows[TESTING].verdict == NEUTRAL
    assert all(s.low_confidence for s in scores.pieces)  # 1 repeat
    assert scores.bare.pass_rate == 1.0 and scores.bare.tokens < scores.baseline.tokens


def rec(variant, task, repeat, passed, **kw):
    base = {"type": "run", "run_key": f"{variant}|{task}|{repeat}", "variant": variant, "task": task,
            "repeat": repeat, "passed": passed, "tokens_in": 1000, "tokens_out": 100, "cost_usd": 0.01,
            "turns": 3, "wall_s": 5.0, "error": None, "error_kind": None}
    base.update(kw)
    return base


def table(variant, rows):
    """rows: one string per repeat, e.g. '11010' -> pass/fail per task."""
    return [rec(variant, f"t{i + 1}", r, c == "1") for r, s in enumerate(rows) for i, c in enumerate(s)]


def synthetic_meta(pieces=("p1",), repeats=3, n_tasks=5):
    from harness_ablate.harness import Piece
    ps = [Piece(id=p, kind="claude_md", path="CLAUDE.md", title=p, tokens=100) for p in pieces]
    vs = [Variant("baseline")] + [Variant(f"minus:{p}", [p]) for p in pieces]
    return meta_for(ps, vs, tasks(n_tasks), repeats)


def test_noise_band_uses_baseline_spread_with_floor():
    meta = synthetic_meta()
    base = variant_stats("baseline", None, table("baseline", ["11100", "11111", "11000"]), meta["tasks"])
    assert base.repeat_rates == [0.6, 1.0, 0.4]
    assert abs(noise_band(base, 5) - 0.6) < 1e-9
    steady = variant_stats("baseline", None, table("baseline", ["11100"] * 3), meta["tasks"])
    assert noise_band(steady, 5) == 0.2  # floor = 1/num_tasks
    assert noise_band(steady, 20) == 0.05


def test_deltas_inside_band_are_not_signals():
    meta = synthetic_meta(pieces=("p1", "p2"))
    records = table("baseline", ["11100", "11111", "11000"])  # mean 0.667, band 0.6
    records += table("minus:p1", ["11111", "11111", "11111"])  # +0.333: inside band
    records += table("minus:p2", ["00000", "00000", "00000"])  # -0.667: outside band
    rows = by_piece(score(meta, records))
    assert rows["p1"].verdict == NEUTRAL
    assert rows["p2"].verdict == KEEP


def test_exactly_band_is_not_a_signal_and_one_task_flip_never_counts():
    meta = synthetic_meta()
    records = table("baseline", ["11100"] * 3) + table("minus:p1", ["11110"] * 3)  # +0.2 == band
    assert by_piece(score(meta, records))["p1"].verdict == NEUTRAL


def test_infra_errors_excluded_timeouts_fail_and_low_confidence():
    meta = synthetic_meta()
    records = table("baseline", ["11111", "11111", "11111"])
    records += table("minus:p1", ["11111", "11111"])
    records.append(rec("minus:p1", "t1", 2, False, error_kind="infra", error="API 529"))
    records.append(rec("minus:p1", "t2", 2, False, error_kind="timeout", error="timed out"))
    s = by_piece(score(meta, records))["p1"]
    assert s.infra_errors == 1 and s.timeouts == 1
    assert s.valid == 11 and s.passes == 10
    assert s.repeats == 2 and s.low_confidence  # repeat 2 is incomplete
    assert s.verdict == NEUTRAL  # 10/11 vs 15/15 is within the 0.2 band


def test_missing_variant_is_no_data():
    meta = synthetic_meta(pieces=("p1", "p2"))
    records = table("baseline", ["11111"] * 3) + table("minus:p1", ["11111"] * 3)
    rows = by_piece(score(meta, records))
    assert rows["p2"].verdict == NO_DATA


def test_report_lists_every_piece_and_verdict(tmp_path):
    runner = FakeRunner(base_rate=0.5, rules=[(r"never run the tests", -1.0), (r"type hints", 0.5)])
    meta, records = simulate(project(tmp_path), runner, tmp_path / "w", repeats=1)
    results = tmp_path / "results.jsonl"
    with results.open("w") as f:
        for r in [meta] + records:
            f.write(json.dumps(r) + "\n")
        f.write('{"type": "run", "run_ke')  # torn last line from a kill
    md, out_csv = tmp_path / "report.md", tmp_path / "results.csv"
    scores = write_report(results, md, out_csv)
    text = md.read_text()
    for p in meta["pieces"]:
        assert f"`{p['id']}`" in text
    for s in scores.pieces:
        line = next(l for l in text.splitlines() if l.startswith(f"| `{s.piece}` |"))
        assert s.verdict in line and "LOW CONFIDENCE" in line
    assert "**HARMFUL**" in text and "Remove or rewrite `claude_md:\"## Workflow\"`" in text
    assert "*bare (no harness)*" in text and "## Per-task passes" in text
    assert text.index("HARMFUL") < text.index("NEUTRAL")
    rows = list(csv.DictReader(out_csv.open()))
    assert len(rows) == len(meta["variants"]) and rows[0]["variant"] == "baseline"
    assert {r["verdict"] for r in rows[1:-1]} >= {HARMFUL, NEUTRAL}


def test_load_results_keeps_last_record_per_run(tmp_path):
    meta = synthetic_meta()
    path = tmp_path / "r.jsonl"
    lines = [meta, rec("baseline", "t1", 0, False), rec("baseline", "t1", 0, True)]
    path.write_text("".join(json.dumps(l) + "\n" for l in lines))
    _, records = load_results(path)
    assert len(records) == 1 and records[0]["passed"] is True
