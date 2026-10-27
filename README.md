# harness-ablate

Find out which parts of your CLAUDE.md, skills and hooks still help on today's model. Some of them make it worse.

<!-- example:start -->
From [the sample repo](examples/sample-repo) (Sonnet, 5 tasks × 3 repeats, 150 runs, $7.44;
[full report](examples/sample-report/report.md)):

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

The "Conventions" section is a stale rule to migrate every function to Result dicts. With it, the agent
fixes the bug and then breaks the return type, every time. Nothing else in this harness matters until it's gone.
<!-- example:end -->

## Quickstart

```bash
pipx install harness-ablate                          # or: pip install harness-ablate
harness-ablate scan                                   # what's in your harness, and what it costs in tokens
harness-ablate run tasks.yaml --repeats 1 --only claude_md   # cheap first pass
```

`run` prints the plan and a cost estimate and asks before spending anything. When it finishes you get
`harness-ablate-results/report.md`, `results.csv` and `results.jsonl`.

You need [Claude Code](https://docs.claude.com/en/docs/claude-code) installed and logged in, Python 3.10+, and
a git repo. You also need a `tasks.yaml` that describes a few real tasks and how to check them:

```yaml
setup: pip install -e .          # optional: runs in every fresh worktree before the agent starts
timeout_s: 600                   # optional default for every task
tasks:
  - id: fix-dates
    prompt: "tests/test_dates.py is failing. Find and fix the bug."
    check: git diff --quiet HEAD -- tests && python -m pytest -q tests/test_dates.py
  - id: csv-quoting
    prompt: "Exporting a name with a comma breaks the CSV. Fix it."
    check: python -m pytest -q tests/test_export.py
    timeout_s: 300               # optional per task
    max_turns: 30                # optional; passed only if your claude CLI has --max-turns
```

A check is any shell command run in the worktree after the agent finishes. Exit code 0 means pass. Good tasks
are ones your harness is supposed to help with: past bugs, chores you hand to the agent, things it got wrong
before you added a rule. Five is enough to start. Guard against the agent "fixing" tests, as above.

## How it works

1. **Split the harness into pieces.** Each `##` section of `CLAUDE.md`, `.claude/CLAUDE.md` and `AGENTS.md` is
   a piece (deeper headings stay with their parent, and `#` inside code blocks is ignored). So is each skill in
   `.claude/skills/` and each hook entry in `.claude/settings.json`. `harness-ablate scan` lists them.
2. **Build variants.** The *baseline* has the full harness. Each *minus-one* variant removes exactly one
   piece. *Bare* removes all of them.
3. **Run every variant on every task, several times.** Each run gets its own git worktree at a pinned commit,
   in your system temp dir, deleted afterwards. Your working tree is never touched. Claude Code runs headless
   (`claude -p ... --output-format json`), then the task's check decides pass or fail.
4. **Score.** For each piece, compare the pass rate without it to the baseline:

| verdict | meaning |
|---|---|
| **HARMFUL** | pass rate goes *up* by more than the noise band when the piece is removed |
| **KEEP** | pass rate goes *down* by more than the noise band |
| **CUT** | no change beyond the noise band, and removing it saves at least 10% of tokens or cost |
| NEUTRAL | no measurable effect either way |

The noise band is the spread of the baseline's pass rate across repeats, and never less than one task's worth
(1 / number of tasks). One task flipping is never a signal. Rows with fewer than 3 complete repeats are marked
LOW CONFIDENCE. The [1-repeat sample report](examples/sample-report-1-repeat/report.md) shows why that matters:
it caught the bad section but also flagged a useful skill as harmful, because two lucky passes against a 0%
baseline looked like a signal. With 3 repeats that went away.

Runs are ordered repeat by repeat, so stopping early still leaves whole repeats to score. Infra errors (API
errors, CLI crashes) are excluded from pass rates and counted separately. Timeouts count as fails.

## Cost

Every run is one headless Claude Code session, and the total is
`(pieces + 2) variants × tasks × repeats` runs. The sample repo has 8 pieces and 5 tasks: 50 runs per repeat.
On Sonnet each of its runs cost about $0.05; real repos with bigger contexts cost more.

- `plan` shows the run count and a rough estimate without calling any API. `run` shows it again and asks
  before starting (`--yes` skips the prompt).
- `--max-cost` (default $20) is a hard stop: no new run starts unless the remaining budget covers it.
- Every run is capped with Claude Code's `--max-budget-usd`, by default 5× the per-run estimate
  (`--max-run-cost`). Each run gets the same cap, so late runs aren't starved.
- **Start small:** `--repeats 1 --only claude_md` ablates just your CLAUDE.md sections, once. If something
  looks HARMFUL or CUT, confirm it with `--repeats 3` (and `--only` that piece) before deleting it.
- `harness-ablate resume results.jsonl` finishes an interrupted or capped run without redoing completed runs.
  Pass a higher `--max-cost` to let it continue past the original cap.

## Safety

- **Worktrees only.** Every run happens in a fresh `git worktree` at the pinned commit, in your system temp
  dir, removed when the run finishes. Worktrees left by a killed process are cleaned up on the next run or
  resume.
- **Permission checks are skipped, but only inside the temp worktree.** Unattended runs need
  `--dangerously-skip-permissions`. The runner refuses to start Claude Code anywhere else. The agent can still
  run any command your user can, and reach the network, so point this at repos and tasks you trust.
- **Uncommitted harness edits are refused** unless you pass `--allow-dirty`, so you know which harness you
  measured. Untracked harness files (say, a new skill you haven't committed) are copied into every worktree.
  Other uncommitted changes are not included; runs use the commit.
- **Your user-level harness still loads.** `~/.claude/CLAUDE.md`, user skills, user hooks and MCP servers
  load in every run and are not ablated in v0.1. They add the same noise to every variant, and their hooks fire
  in every run. `--isolate-user` excludes them (it passes `--setting-sources project,local` and
  `--strict-mcp-config`). `scan` and `plan` warn you about what will load.

## Commands

| command | what it does |
|---|---|
| `harness-ablate scan [-C dir] [--json]` | list harness pieces, token cost and location |
| `harness-ablate plan tasks.yaml` | variants, run count, cost estimate; no API calls |
| `harness-ablate run tasks.yaml` | run everything and write the report |
| `harness-ablate resume results.jsonl` | finish an interrupted run |
| `harness-ablate report results.jsonl -o report.md [--csv out.csv]` | rebuild the report |

Useful `run` options: `--repeats 3`, `--jobs 2`, `--max-cost 20`, `--model sonnet`, `--only claude_md`
(repeatable; matches a piece id, kind or id prefix), `--no-bare`, `--isolate-user`, `--allow-dirty`,
`--commit <sha>`, `-C <project dir>` (default: the directory containing `tasks.yaml`, which may be a
subdirectory of the git repo), `-o <results.jsonl>`. `--runner fake` uses a deterministic stand-in agent for
trying the pipeline offline.

## Try it on the sample repo

[`examples/sample-repo`](examples/sample-repo) is a tiny Python package with five bugs, five failing test
files, and a harness of six CLAUDE.md sections, one skill and one hook. One section, "Conventions", is
deliberately bad: a stale mandate to migrate every touched function to Result dicts and to never run the tests
locally. It is realistic harness rot, and it quietly breaks every task.

```bash
git clone https://github.com/jatingargiitk/harness-ablate && cd harness-ablate
pip install -e .
harness-ablate scan -C examples/sample-repo
harness-ablate run examples/sample-repo/tasks.yaml --repeats 1 --model sonnet --isolate-user --yes
```

## Roadmap

- Codex and Cursor runners
- Auto-generated tasks from git history (revert a past fix, ask the agent to redo it)
- Pairwise ablation, for pieces that only matter together
- Ablating the user-level harness
- A public leaderboard of common harness patterns and whether they still help

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q      # no API calls; uses the fake runner and a stub claude binary
```

## License

MIT
