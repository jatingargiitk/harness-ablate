# harness-ablate report: harness-ablate

- **repo:** harness-ablate (`examples/sample-repo/`)
- **commit:** `f87dc6dd6c57`
- **model:** sonnet via claude
- **date:** 2026-10-18
- **tasks:** 5
- **repeats:** 3
- **total runs:** 150
- **total cost:** $7.44
- **user-level harness:** excluded (`--isolate-user`)

Baseline (full harness) passes **0% (0/15)** of runs. Noise band: ±20 pts; a piece needs a bigger swing than that to count.

| piece | tokens it costs | pass rate without it | delta | tokens saved/run | runs | verdict |
|---|---:|---:|---:|---:|---:|---|
| `claude_md:"## Conventions"` | 147 | 100% (15/15) | +100 pts | -4.6k (-8%) | 15 | **HARMFUL** |
| `skill:run-tests` | 135 | 7% (1/15) | +7 pts | 2.7k (+5%) | 15 | NEUTRAL |
| `claude_md:"## Commits"` | 31 | 0% (0/15) | 0 pts | -2.5k (-4%) | 15 | NEUTRAL |
| `claude_md:"## Layout"` | 32 | 0% (0/15) | 0 pts | -2.9k (-5%) | 15 | NEUTRAL |
| `claude_md:"## Project"` | 39 | 0% (0/15) | 0 pts | -6.1k (-10%) | 15 | NEUTRAL |
| `claude_md:"## Style"` | 32 | 0% (0/15) | 0 pts | 155 | 15 | NEUTRAL |
| `claude_md:"## Testing"` | 59 | 0% (0/15) | 0 pts | -4.5k (-8%) | 15 | NEUTRAL |
| `hook:PostToolUse[0]` | — | 0% (0/15) | 0 pts | 2.5k (+4%) | 15 | NEUTRAL |
| *baseline (full harness)* | 475 | 0% (0/15) | — | — | 15 | |
| *bare (no harness)* | 0 | 100% (15/15) | +100 pts | -11.3k (-19%) | 15 | |

## What to do

1. **Remove or rewrite `claude_md:"## Conventions"`.** Without it the pass rate goes from 0% to 100% (+100 pts).
2. With the baseline this low, the HARMFUL piece hides what everything else does: nothing can lower a pass rate that's already near zero. Fix it, then re-run to judge the rest.
3. No measurable effect, little cost (keep or cut, your call): `skill:run-tests`, `claude_md:"## Commits"`, `claude_md:"## Layout"`, `claude_md:"## Project"`, `claude_md:"## Style"`, `claude_md:"## Testing"`, `hook:PostToolUse[0]`.
4. The whole harness isn't paying for itself on these tasks: with no harness at all the pass rate is 100% vs 0% with it.

## Per-task passes

| variant | `dates` | `export` | `slug` | `money` | `textstats` |
|---|---:|---:|---:|---:|---:|
| *baseline* | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| `claude_md:"## Conventions"` | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| `skill:run-tests` | 1/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| `claude_md:"## Commits"` | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| `claude_md:"## Layout"` | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| `claude_md:"## Project"` | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| `claude_md:"## Style"` | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| `claude_md:"## Testing"` | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| `hook:PostToolUse[0]` | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| *bare* | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |

## Cost and speed per run

| variant | mean tokens | mean cost | mean turns | mean wall time |
|---|---:|---:|---:|---:|
| *baseline* | 59.4k | $0.052 | 4.1 | 13s |
| `claude_md:"## Conventions"` | 64.1k | $0.043 | 4.7 | 9s |
| `skill:run-tests` | 56.7k | $0.050 | 4.0 | 13s |
| `claude_md:"## Commits"` | 61.9k | $0.052 | 4.3 | 14s |
| `claude_md:"## Layout"` | 62.3k | $0.049 | 3.4 | 13s |
| `claude_md:"## Project"` | 65.6k | $0.053 | 4.3 | 14s |
| `claude_md:"## Style"` | 59.3k | $0.051 | 4.1 | 13s |
| `claude_md:"## Testing"` | 64.0k | $0.051 | 4.3 | 13s |
| `hook:PostToolUse[0]` | 56.9k | $0.052 | 3.9 | 13s |
| *bare* | 70.7k | $0.042 | 4.9 | 10s |

<sub>Each minus-one row removes exactly one piece from the baseline harness in a fresh git worktree. Pass rate excludes infra errors (API/CLI failures); timeouts count as fails. Tokens include cache reads and writes.</sub>
