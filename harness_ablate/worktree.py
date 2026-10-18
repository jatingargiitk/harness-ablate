"""Disposable git worktrees at a pinned commit.

Every run happens in its own worktree under the system temp dir (outside the
repo, so no parent-directory CLAUDE.md leaks in) and is removed afterwards.
The user's working tree is never written to.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .harness import HARNESS_PATHS

_git_lock = threading.Lock()  # git worktree add/remove take repo-wide locks


class GitError(RuntimeError):
    pass


def git(args: list[str], cwd: str | Path) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


@dataclass
class RepoInfo:
    root: Path  # git toplevel
    project_rel: str  # project dir relative to root ("" for the root itself)
    commit: str
    name: str
    harness_modified: list[str] = field(default_factory=list)  # tracked, uncommitted changes
    harness_untracked: list[str] = field(default_factory=list)  # copied into every worktree
    other_dirty: bool = False

    @property
    def project_dir(self) -> Path:
        return self.root / self.project_rel if self.project_rel else self.root


def inspect_repo(project: str | Path, commit: str | None = None) -> RepoInfo:
    project = Path(project).resolve()
    try:
        root = Path(git(["rev-parse", "--show-toplevel"], project)).resolve()
    except (GitError, FileNotFoundError) as e:
        raise GitError(f"{project} is not inside a git repository") from e
    rel = os.path.relpath(project, root)
    rel = "" if rel == "." else rel
    sha = git(["rev-parse", commit or "HEAD"], root)
    pathspecs = [str(Path(rel) / p) if rel else p for p in HARNESS_PATHS]
    modified, untracked = [], []
    for code, path in _status(root, ["--untracked-files=all", "--", *pathspecs]):
        (untracked if code == "??" else modified).append(path)
    other_dirty = any(path not in modified for _, path in _status(root, ["--untracked-files=no"]))
    return RepoInfo(root=root, project_rel=rel, commit=sha, name=root.name,
                    harness_modified=modified, harness_untracked=untracked, other_dirty=other_dirty)


def _status(root: Path, args: list[str]) -> list[tuple[str, str]]:
    r = subprocess.run(["git", "status", "--porcelain", "-z", *args], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise GitError(f"git status failed: {r.stderr.strip()}")
    out, fields = [], r.stdout.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        code = entry[:2]
        out.append((code, entry[3:]))
        if code[0] in "RC":  # renames carry the source path as an extra field
            i += 1
    return out


def _copy_into(info: RepoInfo, wt_root: Path, paths: list[str]) -> None:
    for rel in paths:
        src, dst = info.root / rel, wt_root / rel
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


@contextmanager
def worktree(info: RepoInfo, *, allow_dirty: bool = False, keep: bool = False,
             base_dir: str | Path | None = None) -> Iterator[Path]:
    """Yield the project directory inside a fresh worktree; delete it afterwards."""
    parent = Path(tempfile.mkdtemp(prefix="harness-ablate-", dir=base_dir))
    wt = parent / info.name
    with _git_lock:
        git(["worktree", "add", "--detach", "--quiet", str(wt), info.commit], info.root)
    try:
        copy = list(info.harness_untracked) + (list(info.harness_modified) if allow_dirty else [])
        _copy_into(info, wt, copy)
        yield wt / info.project_rel if info.project_rel else wt
    finally:
        if not keep:
            remove_worktree(info.root, wt)
            shutil.rmtree(parent, ignore_errors=True)


def remove_worktree(root: Path, wt: Path) -> None:
    with _git_lock:
        try:
            git(["worktree", "remove", "--force", str(wt)], root)
        except GitError:
            shutil.rmtree(wt, ignore_errors=True)
            subprocess.run(["git", "worktree", "prune"], cwd=root, capture_output=True)
