"""Claude runner tests against a stub `claude` binary (no API calls)."""

import json
import stat
import tempfile
from pathlib import Path

import pytest

from harness_ablate.runners.base import INFRA, TIMEOUT
from harness_ablate.runners.claude import ClaudeRunner, cli_flags, parse_result, result_to_run
from harness_ablate.tasks import Task

HELP = """Usage: claude [options]
  -p, --print                 Print response and exit
  --output-format <format>    text, json, stream-json
  --model <model>             Model
  --dangerously-skip-permissions  Bypass all permission checks.
  --max-budget-usd <amount>   Maximum dollar amount
  --setting-sources <sources> Comma-separated list
  --strict-mcp-config         Only use MCP servers from --mcp-config
  --no-session-persistence    Disable session persistence
"""

RESULT = {"type": "result", "subtype": "success", "is_error": False, "result": "done", "num_turns": 7,
          "total_cost_usd": 0.1234, "api_error_status": None,
          "usage": {"input_tokens": 10, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 5000,
                    "output_tokens": 300}}


def stub(tmp_path, body: str) -> str:
    path = tmp_path / "bin" / "claude"
    path.parent.mkdir(parents=True, exist_ok=True)
    help_file = tmp_path / "help.txt"
    help_file.write_text(HELP)
    path.write_text(f"""#!/bin/sh
if [ "$1" = "--help" ]; then cat {help_file}; exit 0; fi
printf '%s\\n' "$@" > "$PWD/.argv"
{body}
""")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    cli_flags.cache_clear()
    return str(path)


@pytest.fixture
def workdir():
    parent = Path(tempfile.mkdtemp(prefix="harness-ablate-"))
    wd = parent / "proj"
    wd.mkdir()
    yield wd
    import shutil
    shutil.rmtree(parent)


def task(**kw):
    return Task(id="t1", prompt="fix the bug", check="true", **kw)


def test_command_uses_only_supported_flags(tmp_path, workdir):
    binary = stub(tmp_path, f"echo '{json.dumps(RESULT)}'")
    r = ClaudeRunner("sonnet", binary=binary, isolate_user=True)
    res = r.run(task(max_turns=5), workdir, timeout=30, max_turns=5, budget_usd=1.5)
    argv = (workdir / ".argv").read_text().splitlines()
    assert argv[:4] == ["-p", "fix the bug", "--output-format", "json"]
    assert "--max-turns" not in argv  # not in this CLI's --help
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--max-budget-usd") + 1] == "1.50"
    assert argv[argv.index("--setting-sources") + 1] == "project,local"
    assert "--strict-mcp-config" in argv and "--dangerously-skip-permissions" in argv
    assert res.error is None and res.tokens_in == 6010 and res.tokens_out == 300
    assert res.turns == 7 and res.cost_usd == 0.1234


def test_user_harness_loads_by_default(tmp_path, workdir):
    r = ClaudeRunner(binary=stub(tmp_path, "true"))
    cmd = r.command("x", None, None)
    assert "--setting-sources" not in cmd and "--model" not in cmd and "--max-budget-usd" not in cmd


def test_refuses_outside_temp_worktree(tmp_path):
    r = ClaudeRunner(binary=stub(tmp_path, "true"))
    with pytest.raises(RuntimeError, match="outside a temp worktree"):
        r.run(task(), tmp_path, timeout=5, max_turns=None)


def test_timeout_kills_process_group(tmp_path, workdir):
    marker = workdir / "child_alive"
    binary = stub(tmp_path, f"(sleep 3; touch {marker}) & sleep 30")
    res = ClaudeRunner(binary=binary).run(task(), workdir, timeout=1, max_turns=None)
    assert res.error_kind == TIMEOUT and res.wall_s < 5
    import time
    time.sleep(3)
    assert not marker.exists()  # background child was killed with the group


def test_garbage_output_is_infra_error(tmp_path, workdir):
    binary = stub(tmp_path, "echo 'Invalid API key' >&2; exit 1")
    res = ClaudeRunner(binary=binary).run(task(), workdir, timeout=10, max_turns=None)
    assert res.error_kind == INFRA and "Invalid API key" in res.error


def test_result_mapping():
    assert result_to_run({**RESULT, "api_error_status": 529, "is_error": True}, 1).error_kind == INFRA
    capped = result_to_run({**RESULT, "subtype": "error_max_budget_usd", "is_error": True}, 1)
    assert capped.error_kind is None and capped.error.startswith("error_max_budget_usd")
    assert parse_result("noise\n" + json.dumps(RESULT))["num_turns"] == 7
    assert parse_result(json.dumps([{"type": "system"}, RESULT]))["num_turns"] == 7
    assert parse_result("not json") is None


def test_cost_estimation():
    from harness_ablate.runners.claude import estimate_cost_per_run
    # Test model-specific estimates
    assert estimate_cost_per_run("sonnet") == 0.05
    assert estimate_cost_per_run("claude-sonnet-3.5") == 0.05
    assert estimate_cost_per_run("haiku") == 0.05
    assert estimate_cost_per_run("opus") == 1.00
    # Test default fallback for unknown models
    assert estimate_cost_per_run("unknown-model") == 0.10
    assert estimate_cost_per_run(None) == 0.10
    # Test override
    assert estimate_cost_per_run("sonnet", override=0.25) == 0.25
