# harness-ablate report: harness-ablate

- **repo:** harness-ablate (`examples/sample-repo/`)
- **commit:** `44b08ec12c5c`
- **model:** sonnet via claude
- **date:** 2026-10-18
- **tasks:** 5
- **repeats:** 1
- **total runs:** 50
- **total cost:** $2.46
- **user-level harness:** excluded (`--isolate-user`)

Baseline (full harness) passes **0% (0/5)** of runs. Noise band: ±20 pts; a piece needs a bigger swing than that to count.

| piece | tokens it costs | pass rate without it | delta | tokens saved/run | runs | verdict |
|---|---:|---:|---:|---:|---:|---|
| `claude_md:"## Conventions"` | 147 | 100% (5/5) | +100 pts | -2.0k (-3%) | 5 | **HARMFUL** · LOW CONFIDENCE |
| `skill:run-tests` | 135 | 40% (2/5) | +40 pts | -7.5k (-13%) | 5 | **HARMFUL** · LOW CONFIDENCE |
| `claude_md:"## Style"` | 32 | 20% (1/5) | +20 pts | -7.4k (-13%) | 5 | NEUTRAL · LOW CONFIDENCE |
| `claude_md:"## Commits"` | 31 | 0% (0/5) | 0 pts | -11 | 5 | NEUTRAL · LOW CONFIDENCE |
| `claude_md:"## Layout"` | 32 | 0% (0/5) | 0 pts | -7.0k (-12%) | 5 | NEUTRAL · LOW CONFIDENCE |
| `claude_md:"## Project"` | 39 | 0% (0/5) | 0 pts | -7.2k (-13%) | 5 | NEUTRAL · LOW CONFIDENCE |
| `claude_md:"## Testing"` | 59 | 0% (0/5) | 0 pts | 417 (+1%) | 5 | NEUTRAL · LOW CONFIDENCE |
| `hook:PostToolUse[0]` | — | 0% (0/5) | 0 pts | -48 | 5 | NEUTRAL · LOW CONFIDENCE |
| *baseline (full harness)* | 475 | 0% (0/5) | — | — | 5 | |
| *bare (no harness)* | 0 | 100% (5/5) | +100 pts | -11.1k (-19%) | 5 | |

## What to do

1. **Remove or rewrite `claude_md:"## Conventions"`.** Without it the pass rate goes from 0% to 100% (+100 pts). Low confidence: confirm with more repeats first.
2. **Remove or rewrite `skill:run-tests`.** Without it the pass rate goes from 0% to 40% (+40 pts). Low confidence: confirm with more repeats first.
3. `claude_md:"## Style"` moved the pass rate +20 pts when removed, inside the ±20 pt noise band. More repeats would settle it.
4. No measurable effect, little cost (keep or cut, your call): `claude_md:"## Commits"`, `claude_md:"## Layout"`, `claude_md:"## Project"`, `claude_md:"## Testing"`, `hook:PostToolUse[0]`.
5. The whole harness isn't paying for itself on these tasks: with no harness at all the pass rate is 100% vs 0% with it.
6. Rows marked LOW CONFIDENCE have fewer than 3 complete repeats. Re-run with `--repeats 3` before deleting anything you care about.

## Per-task passes

| variant | `dates` | `export` | `slug` | `money` | `textstats` |
|---|---:|---:|---:|---:|---:|
| *baseline* | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 |
| `claude_md:"## Conventions"` | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `skill:run-tests` | 1/1 | 0/1 | 0/1 | 0/1 | 1/1 |
| `claude_md:"## Style"` | 1/1 | 0/1 | 0/1 | 0/1 | 0/1 |
| `claude_md:"## Commits"` | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 |
| `claude_md:"## Layout"` | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 |
| `claude_md:"## Project"` | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 |
| `claude_md:"## Testing"` | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 |
| `hook:PostToolUse[0]` | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 |
| *bare* | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |

## Cost and speed per run

| variant | mean tokens | mean cost | mean turns | mean wall time |
|---|---:|---:|---:|---:|
| *baseline* | 56.8k | $0.051 | 4.0 | 13s |
| `claude_md:"## Conventions"` | 58.7k | $0.041 | 4.0 | 9s |
| `skill:run-tests` | 64.3k | $0.052 | 4.4 | 14s |
| `claude_md:"## Style"` | 64.2k | $0.052 | 4.4 | 13s |
| `claude_md:"## Commits"` | 56.8k | $0.052 | 4.0 | 13s |
| `claude_md:"## Layout"` | 63.7k | $0.051 | 3.4 | 14s |
| `claude_md:"## Project"` | 64.0k | $0.052 | 3.8 | 14s |
| `claude_md:"## Testing"` | 56.4k | $0.049 | 3.8 | 12s |
| `hook:PostToolUse[0]` | 56.8k | $0.051 | 4.0 | 13s |
| *bare* | 67.8k | $0.042 | 4.8 | 10s |

<sub>Each minus-one row removes exactly one piece from the baseline harness in a fresh git worktree. Pass rate excludes infra errors (API/CLI failures); timeouts count as fails. Tokens include cache reads and writes.</sub>
