"""Turn run records into per-variant stats and verdicts.

Noise band: the spread (max - min) of the baseline's pass rate across
repeats, floored at 1/num_tasks (one task flipping is never a signal).
For each minus-one variant, delta = pass rate without the piece - baseline:

    delta >  band              HARMFUL  (removing it helps)
    delta < -band              KEEP     (removing it hurts)
    |delta| <= band, and it saves >= 10% tokens or cost     CUT
    otherwise                  NEUTRAL

Infra errors (API/CLI failures) are excluded from pass rates; timeouts are
fails. Fewer than 3 completed repeats marks a row LOW CONFIDENCE.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean

from .runners.base import INFRA, TIMEOUT
from .variants import BARE, BASELINE

HARMFUL, KEEP, CUT, NEUTRAL, NO_DATA = "HARMFUL", "KEEP", "CUT", "NEUTRAL", "NO DATA"
VERDICT_ORDER = {HARMFUL: 0, CUT: 1, KEEP: 2, NEUTRAL: 3, NO_DATA: 4}
SAVINGS_THRESHOLD = 0.10
MIN_REPEATS = 3
EPS = 1e-9  # 0.8 - 0.6 > 0.2 in floating point


@dataclass
class VariantStats:
    variant: str
    piece: str | None  # piece id for minus-one variants
    runs: int = 0  # recorded runs (including infra errors)
    valid: int = 0  # runs counted in the pass rate
    passes: int = 0
    infra_errors: int = 0
    timeouts: int = 0
    repeats: int = 0  # repeats with every task validly recorded
    pass_rate: float | None = None
    repeat_rates: list[float] = field(default_factory=list)
    tokens: float = 0.0  # mean tokens_in + tokens_out per valid run
    cost: float = 0.0
    wall_s: float = 0.0
    turns: float = 0.0
    per_task: dict[str, tuple[int, int]] = field(default_factory=dict)  # task -> (passes, valid)
    # filled for minus-one variants
    piece_tokens: int | None = None
    delta: float | None = None
    tokens_saved: float | None = None
    cost_saved: float | None = None
    verdict: str | None = None
    low_confidence: bool = False


@dataclass
class Scores:
    baseline: VariantStats
    bare: VariantStats | None
    pieces: list[VariantStats]  # sorted: HARMFUL first
    band: float
    num_tasks: int
    total_runs: int
    total_cost: float


def variant_stats(variant: str, piece: str | None, records: list[dict], tasks: list[str]) -> VariantStats:
    s = VariantStats(variant=variant, piece=piece)
    valid = []
    by_repeat: dict[int, dict[str, bool]] = defaultdict(dict)
    per_task: dict[str, list[bool]] = defaultdict(list)
    for r in records:
        s.runs += 1
        if r.get("error_kind") == INFRA:
            s.infra_errors += 1
            continue
        if r.get("error_kind") == TIMEOUT:
            s.timeouts += 1
        valid.append(r)
        by_repeat[r["repeat"]][r["task"]] = bool(r["passed"])
        per_task[r["task"]].append(bool(r["passed"]))
    s.valid = len(valid)
    s.passes = sum(bool(r["passed"]) for r in valid)
    if valid:
        s.pass_rate = s.passes / s.valid
        s.tokens = mean(r["tokens_in"] + r["tokens_out"] for r in valid)
        s.cost = mean(r["cost_usd"] for r in valid)
        s.wall_s = mean(r["wall_s"] for r in valid)
        s.turns = mean(r["turns"] for r in valid)
    complete = [res for _, res in sorted(by_repeat.items()) if all(t in res for t in tasks)]
    s.repeats = len(complete)
    s.repeat_rates = [sum(res[t] for t in tasks) / len(tasks) for res in complete]
    s.per_task = {t: (sum(per_task[t]), len(per_task[t])) for t in tasks}
    return s


def noise_band(baseline: VariantStats, num_tasks: int) -> float:
    spread = max(baseline.repeat_rates) - min(baseline.repeat_rates) if baseline.repeat_rates else 0.0
    return max(spread, 1.0 / num_tasks)


def verdict(delta: float, band: float, tokens_frac: float, cost_frac: float) -> str:
    band += EPS
    if delta > band:
        return HARMFUL
    if delta < -band:
        return KEEP
    if tokens_frac >= SAVINGS_THRESHOLD or cost_frac >= SAVINGS_THRESHOLD:
        return CUT
    return NEUTRAL


def score(meta: dict, records: list[dict]) -> Scores:
    tasks = list(meta["tasks"])
    piece_tokens = {p["id"]: p["tokens"] for p in meta["pieces"]}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        grouped[r["variant"]].append(r)
    base = variant_stats(BASELINE, None, grouped.get(BASELINE, []), tasks)
    base.low_confidence = base.repeats < MIN_REPEATS
    band = noise_band(base, len(tasks))
    bare, rows = None, []
    for v in meta["variants"]:
        vid = v["id"]
        if vid == BASELINE:
            continue
        piece = v["removed"][0] if vid != BARE else None
        s = variant_stats(vid, piece, grouped.get(vid, []), tasks)
        s.low_confidence = min(s.repeats, base.repeats) < MIN_REPEATS
        if s.pass_rate is not None and base.pass_rate is not None:
            s.delta = s.pass_rate - base.pass_rate
            s.tokens_saved = base.tokens - s.tokens
            s.cost_saved = base.cost - s.cost
        if vid == BARE:
            bare = s
            continue
        s.piece_tokens = piece_tokens.get(piece)
        if s.delta is None:
            s.verdict = NO_DATA
        else:
            tok_frac = s.tokens_saved / base.tokens if base.tokens else 0.0
            cost_frac = s.cost_saved / base.cost if base.cost else 0.0
            s.verdict = verdict(s.delta, band, tok_frac, cost_frac)
        rows.append(s)
    rows.sort(key=lambda s: (VERDICT_ORDER[s.verdict], -abs(s.delta or 0.0), s.piece or ""))
    total_cost = sum(r.get("cost_usd", 0.0) for r in records)
    return Scores(baseline=base, bare=bare, pieces=rows, band=band, num_tasks=len(tasks),
                  total_runs=len(records), total_cost=total_cost)
