# harness-ablate report: harness-ablate

- **repo:** harness-ablate (`examples/sample-repo/`)
- **commit:** `fd890b206177`
- **model:** sonnet via claude
- **date:** 2026-10-18
- **tasks:** 5
- **repeats:** 1
- **total runs:** 50
- **total cost:** $2.38
- **user-level harness:** excluded (`--isolate-user`)

Baseline (full harness) passes **100% (5/5)** of runs. Noise band: ±20 pts; a piece needs a bigger swing than that to count.

| piece | tokens it costs | pass rate without it | delta | tokens saved/run | runs | verdict |
|---|---:|---:|---:|---:|---:|---|
| `claude_md:"## Conventions"` | 123 | 100% (5/5) | 0 pts | -10.1k (-18%) | 5 | **CUT** · LOW CONFIDENCE |
| `claude_md:"## Testing"` | 59 | 20% (1/5) | -80 pts | -308 (-1%) | 5 | **KEEP** · LOW CONFIDENCE |
| `claude_md:"## Commits"` | 31 | 60% (3/5) | -40 pts | -210 | 5 | **KEEP** · LOW CONFIDENCE |
| `claude_md:"## Style"` | 32 | 60% (3/5) | -40 pts | -192 | 5 | **KEEP** · LOW CONFIDENCE |
| `hook:PostToolUse[0]` | — | 60% (3/5) | -40 pts | -639 (-1%) | 5 | **KEEP** · LOW CONFIDENCE |
| `claude_md:"## Project"` | 39 | 80% (4/5) | -20 pts | 28 | 5 | NEUTRAL · LOW CONFIDENCE |
| `skill:run-tests` | 135 | 80% (4/5) | -20 pts | -130 | 5 | NEUTRAL · LOW CONFIDENCE |
| `claude_md:"## Layout"` | 32 | 100% (5/5) | 0 pts | 140 | 5 | NEUTRAL · LOW CONFIDENCE |
| *baseline (full harness)* | 451 | 100% (5/5) | — | — | 5 | |
| *bare (no harness)* | 0 | 100% (5/5) | 0 pts | -11.6k (-21%) | 5 | |

## What to do

1. **Cut `claude_md:"## Conventions"`.** No measurable effect on pass rate; removing it saves -10.1k tokens and $0.005 per run.
2. **Keep** `claude_md:"## Testing"` (-80 pts without it), `claude_md:"## Commits"` (-40 pts without it), `claude_md:"## Style"` (-40 pts without it), `hook:PostToolUse[0]` (-40 pts without it).
3. `claude_md:"## Project"` moved the pass rate -20 pts when removed, inside the ±20 pt noise band. More repeats would settle it.
4. `skill:run-tests` moved the pass rate -20 pts when removed, inside the ±20 pt noise band. More repeats would settle it.
5. No measurable effect, little cost (keep or cut, your call): `claude_md:"## Layout"`.
6. The whole harness isn't paying for itself on these tasks: with no harness at all the pass rate is 100% vs 100% with it.
7. Rows marked LOW CONFIDENCE have fewer than 3 complete repeats. Re-run with `--repeats 3` before deleting anything you care about.

## Per-task passes

| variant | `dates` | `export` | `slug` | `money` | `textstats` |
|---|---:|---:|---:|---:|---:|
| *baseline* | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `claude_md:"## Conventions"` | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `claude_md:"## Testing"` | 0/1 | 0/1 | 0/1 | 0/1 | 1/1 |
| `claude_md:"## Commits"` | 1/1 | 0/1 | 1/1 | 0/1 | 1/1 |
| `claude_md:"## Style"` | 0/1 | 1/1 | 1/1 | 0/1 | 1/1 |
| `hook:PostToolUse[0]` | 0/1 | 1/1 | 1/1 | 0/1 | 1/1 |
| `claude_md:"## Project"` | 1/1 | 1/1 | 1/1 | 0/1 | 1/1 |
| `skill:run-tests` | 1/1 | 1/1 | 1/1 | 1/1 | 0/1 |
| `claude_md:"## Layout"` | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| *bare* | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |

## Cost and speed per run

| variant | mean tokens | mean cost | mean turns | mean wall time |
|---|---:|---:|---:|---:|
| *baseline* | 56.1k | $0.048 | 4.0 | 11s |
| `claude_md:"## Conventions"` | 66.2k | $0.043 | 4.4 | 10s |
| `claude_md:"## Testing"` | 56.4k | $0.050 | 3.8 | 13s |
| `claude_md:"## Commits"` | 56.3k | $0.049 | 4.0 | 12s |
| `claude_md:"## Style"` | 56.3k | $0.049 | 4.0 | 12s |
| `hook:PostToolUse[0]` | 56.7k | $0.051 | 4.0 | 13s |
| `claude_md:"## Project"` | 56.1k | $0.049 | 4.0 | 12s |
| `skill:run-tests` | 56.2k | $0.048 | 4.0 | 12s |
| `claude_md:"## Layout"` | 56.0k | $0.048 | 3.6 | 12s |
| *bare* | 67.7k | $0.042 | 4.8 | 10s |

<sub>Each minus-one row removes exactly one piece from the baseline harness in a fresh git worktree. Pass rate excludes infra errors (API/CLI failures); timeouts count as fails. Tokens include cache reads and writes.</sub>
