import json
import subprocess
from pathlib import Path

import pytest

CLAUDE_MD = """# Demo project

Small library used in tests.

## Testing

Run `python -m pytest -q` before finishing.

## Style

- Type hints everywhere.

### Naming

snake_case.

## Workflow

Never run the tests.
"""

SKILL = """---
name: run-tests
description: How to run this project's tests
---
Use `python -m pytest -q`.
"""

SETTINGS = {
    "permissions": {"allow": ["Bash(pytest *)"]},
    "hooks": {
        "PostToolUse": [
            {"matcher": "Edit", "hooks": [{"type": "command", "command": "echo edited >> .hook.log"}]},
            {"matcher": "Write", "hooks": [{"type": "command", "command": "true"}]},
        ],
        "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
    },
}


def sh(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, shell=isinstance(cmd, str))


def write_harness(project: Path) -> None:
    (project / "CLAUDE.md").write_text(CLAUDE_MD)
    (project / "AGENTS.md").write_text("Prefer small diffs.\n")
    skill = project / ".claude" / "skills" / "run-tests"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL)
    (skill / "notes.txt").write_text("extra file\n")
    (project / ".claude" / "settings.json").write_text(json.dumps(SETTINGS, indent=2))


@pytest.fixture
def repo(tmp_path):
    """A git repo whose project lives in a subdirectory (like examples/sample-repo)."""
    root = tmp_path / "repo"
    project = root / "proj"
    (project / "src").mkdir(parents=True)
    (project / "src" / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    (root / "README.md").write_text("root readme\n")
    write_harness(project)
    sh(["git", "init", "-q"], root)
    sh(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], root)
    sh(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], root)
    return project
