import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from harness_ablate.harness import HARNESS_PATHS, discover
from harness_ablate.variants import BARE, BASELINE, apply_variant, build_variants
from harness_ablate.worktree import GitError, inspect_repo, worktree


def snapshot(project: Path) -> dict[str, str]:
    out = {}
    for p in sorted(project.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            out[str(p.relative_to(project))] = hashlib.sha1(p.read_bytes()).hexdigest()
    return out


def signatures(project: Path) -> set[tuple]:
    """Content-based identity of every piece (ids of hooks shift when one is removed)."""
    sigs = set()
    for p in discover(project):
        if p.kind == "hook":
            settings = json.loads((project / p.path).read_text())
            entry = settings["hooks"][p.detail["event"]][p.detail["index"]]
            sigs.add(("hook", p.detail["event"], json.dumps(entry, sort_keys=True)))
        elif p.kind == "skill":
            files = tuple(sorted((str(f.relative_to(project)), f.read_text()) for f in (project / p.path).rglob("*") if f.is_file()))
            sigs.add(("skill", p.path, files))
        else:
            sigs.add((p.kind, p.path, p.title, p.tokens))
    return sigs


def is_harness(rel: str) -> bool:
    return any(rel == h or rel.startswith(h + "/") for h in HARNESS_PATHS)


def test_each_variant_differs_from_baseline_by_exactly_one_piece(repo):
    info = inspect_repo(repo)
    assert info.project_rel == "proj"
    pieces = discover(repo)
    variants = build_variants(pieces)
    assert variants[0].id == BASELINE and variants[-1].id == BARE
    assert len(variants) == len(pieces) + 2

    with worktree(info) as base_dir:
        base_snap, base_sigs = snapshot(base_dir), signatures(base_dir)

    by_id = {p.id: p for p in pieces}
    for v in variants[1:-1]:
        with worktree(info) as wt:
            apply_variant(v, wt, pieces)
            snap, sigs = snapshot(wt), signatures(wt)
        removed = base_sigs - sigs
        assert len(removed) == 1, (v.id, removed)
        assert sigs <= base_sigs, v.id  # nothing added or rewritten
        # non-harness files are byte-identical
        assert {k: h for k, h in snap.items() if not is_harness(k)} == {k: h for k, h in base_snap.items() if not is_harness(k)}
        kind = by_id[v.removed[0]].kind
        assert next(iter(removed))[0] == kind


def test_section_removal_keeps_other_text_verbatim(repo):
    info = inspect_repo(repo)
    pieces = discover(repo)
    original = (repo / "CLAUDE.md").read_text()
    v = next(v for v in build_variants(pieces) if v.removed == ['claude_md:"## Style"'])
    with worktree(info) as wt:
        apply_variant(v, wt, pieces)
        text = (wt / "CLAUDE.md").read_text()
    assert "## Style" not in text and "### Naming" not in text
    assert text == original.replace("## Style\n\n- Type hints everywhere.\n\n### Naming\n\nsnake_case.\n\n", "")


def test_bare_removes_whole_harness_but_keeps_other_settings(repo):
    info = inspect_repo(repo)
    pieces = discover(repo)
    with worktree(info) as wt:
        apply_variant(build_variants(pieces)[-1], wt, pieces)
        assert discover(wt) == []
        assert json.loads((wt / ".claude" / "settings.json").read_text()) == {"permissions": {"allow": ["Bash(pytest *)"]}}
        assert (wt / "src" / "lib.py").exists()


def test_only_filter(repo):
    pieces = discover(repo)
    ids = [v.id for v in build_variants(pieces, only=["claude_md"], bare=False)]
    assert ids[0] == "baseline" and all("claude_md" in i for i in ids[1:]) and len(ids) == 5
    ids = [v.id for v in build_variants(pieces, only=["hook:Stop[0]"])]
    assert ids == ["baseline", "minus:hook:Stop[0]", "bare"]


def test_worktree_never_touches_user_tree_and_is_cleaned_up(repo):
    info = inspect_repo(repo)
    before = snapshot(repo)
    pieces = discover(repo)
    with worktree(info) as wt:
        apply_variant(build_variants(pieces)[-1], wt, pieces)
        path = wt
    assert snapshot(repo) == before
    assert not path.exists()
    listed = subprocess.run(["git", "worktree", "list"], cwd=info.root, capture_output=True, text=True).stdout
    assert str(path) not in listed and len(listed.strip().splitlines()) == 1


def test_untracked_harness_is_copied_and_dirty_is_detected(repo):
    (repo / ".claude" / "skills" / "new-skill").mkdir()
    (repo / ".claude" / "skills" / "new-skill" / "SKILL.md").write_text("---\nname: new\n---\n")
    (repo / "CLAUDE.md").write_text((repo / "CLAUDE.md").read_text() + "\n## Extra\nuncommitted\n")
    info = inspect_repo(repo)
    assert info.harness_untracked == ["proj/.claude/skills/new-skill/SKILL.md"]
    assert info.harness_modified == ["proj/CLAUDE.md"]
    with worktree(info) as wt:
        assert (wt / ".claude" / "skills" / "new-skill" / "SKILL.md").exists()
        assert "## Extra" not in (wt / "CLAUDE.md").read_text()
    with worktree(info, allow_dirty=True) as wt:
        assert "## Extra" in (wt / "CLAUDE.md").read_text()


def test_not_a_repo(tmp_path):
    with pytest.raises(GitError):
        inspect_repo(tmp_path)
