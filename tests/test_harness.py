import json

from harness_ablate.harness import discover, split_sections, tokens_of

NESTED = """# Project title

Intro paragraph.

## Setup

Install things.

### Python

Use 3.12.

## Testing

Run `pytest`.

```bash
# this is a comment, not a heading
## neither is this
pytest -q
```

## Style
Keep it short.
"""


def test_nested_headings_stay_with_parent():
    secs = split_sections(NESTED)
    assert [s.title for s in secs] == ["(preamble)", "## Setup", "## Testing", "## Style"]
    assert "### Python" in secs[1].text and "Use 3.12." in secs[1].text
    assert "".join(s.text for s in secs) == NESTED


def test_hashes_inside_code_blocks_are_not_headings():
    secs = split_sections(NESTED)
    testing = secs[2].text
    assert "# this is a comment" in testing and "## neither is this" in testing
    assert len(secs) == 4


def test_tilde_fences_and_longer_fences():
    text = "## A\n~~~\n## not a heading\n~~~\n## B\n````\n```\n## still code\n````\nend\n"
    assert [s.title for s in split_sections(text)] == ["## A", "## B"]


def test_no_headings_is_one_piece():
    secs = split_sections("Just some instructions.\nNo headings here.\n")
    assert [s.title for s in secs] == ["(whole file)"]
    assert split_sections("   \n") == []


def test_multiple_h1_split_at_h1():
    secs = split_sections("# One\na\n# Two\nb\n")
    assert [s.title for s in secs] == ["# One", "# Two"]


def test_discover_ids_and_tokens(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# T\n\n## Testing\nrun tests\n\n## Testing\nagain\n")
    (tmp_path / "AGENTS.md").write_text("Be careful.\n")
    skill = tmp_path / ".claude" / "skills" / "pdf"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: pdf\ndescription: Work with PDFs\n---\nbody\n")
    (tmp_path / ".claude" / "skills" / "empty-dir").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
        "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "echo hi"}]},
                        {"hooks": [{"type": "command", "command": "true"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
    }}))
    ids = [p.id for p in discover(tmp_path)]
    assert ids == [
        'claude_md:"(preamble)"', 'claude_md:"## Testing"', 'claude_md:"## Testing"#2',
        'agents_md:"(whole file)"', "skill:pdf",
        "hook:PostToolUse[0]", "hook:PostToolUse[1]", "hook:Stop[0]",
    ]
    by_id = {p.id: p for p in discover(tmp_path)}
    assert by_id["skill:pdf"].detail["description"] == "Work with PDFs"
    assert by_id['claude_md:"## Testing"'].tokens == tokens_of("## Testing\nrun tests\n\n")
    assert by_id["hook:PostToolUse[0]"].detail["commands"] == ["echo hi"]
