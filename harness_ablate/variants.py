"""Variants: baseline, minus-one per piece, and bare.

A variant is applied inside a worktree by deleting exactly the removed
piece(s): one markdown section, one skill directory, or one hook entry.
Nothing else is touched, so baseline and a minus-one variant differ by
exactly one piece.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .harness import MEMORY_FILES, SETTINGS_FILE, SKILLS_DIR, Piece, section_ids, split_sections

BASELINE = "baseline"
BARE = "bare"


@dataclass
class Variant:
    id: str
    removed: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.id == BASELINE:
            return "baseline (full harness)"
        if self.id == BARE:
            return "bare (no harness)"
        return self.removed[0]

    def to_dict(self) -> dict:
        return asdict(self)


def minus(piece_id: str) -> str:
    return f"minus:{piece_id}"


def matches(piece: Piece, only: list[str] | None) -> bool:
    if not only:
        return True
    return any(piece.id == o or piece.kind == o or piece.id.startswith(o) for o in only)


def build_variants(pieces: list[Piece], only: list[str] | None = None, bare: bool = True) -> list[Variant]:
    variants = [Variant(BASELINE)]
    variants += [Variant(minus(p.id), [p.id]) for p in pieces if matches(p, only)]
    if bare and pieces:
        variants.append(Variant(BARE, [p.id for p in pieces]))
    return variants


class ApplyError(RuntimeError):
    pass


def remove_section(project: Path, rel: str, piece_id: str) -> None:
    path = project / rel
    text = path.read_text(encoding="utf-8")
    prefix = MEMORY_FILES[rel]
    sections = split_sections(text)
    ids = section_ids(prefix, sections)
    if piece_id not in ids:
        raise ApplyError(f"section {piece_id} not found in {rel}")
    keep = [s.text for sid, s in zip(ids, sections) if sid != piece_id]
    path.write_text("".join(keep), encoding="utf-8")


def remove_hook(project: Path, event: str, index: int) -> None:
    path = project / SETTINGS_FILE
    settings = json.loads(path.read_text(encoding="utf-8"))
    entries = settings["hooks"][event]
    del entries[index]
    if not entries:
        del settings["hooks"][event]
    if not settings["hooks"]:
        del settings["hooks"]
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def apply_variant(variant: Variant, project: str | Path, pieces: list[Piece]) -> None:
    """Mutate the harness in ``project`` (a worktree!) to match ``variant``."""
    project = Path(project)
    if variant.id == BASELINE:
        return
    if variant.id == BARE:
        for rel in MEMORY_FILES:
            (project / rel).unlink(missing_ok=True)
        shutil.rmtree(project / SKILLS_DIR, ignore_errors=True)
        settings = project / SETTINGS_FILE
        if settings.is_file():
            data = json.loads(settings.read_text(encoding="utf-8"))
            if data.pop("hooks", None) is not None:
                settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return
    by_id = {p.id: p for p in pieces}
    for pid in variant.removed:
        piece = by_id.get(pid)
        if piece is None:
            raise ApplyError(f"unknown piece {pid}")
        if piece.kind in ("claude_md", "agents_md"):
            remove_section(project, piece.path, pid)
        elif piece.kind == "skill":
            target = project / piece.path
            if not target.is_dir():
                raise ApplyError(f"skill dir missing: {piece.path}")
            shutil.rmtree(target)
        elif piece.kind == "hook":
            remove_hook(project, piece.detail["event"], piece.detail["index"])
        else:
            raise ApplyError(f"don't know how to remove {piece.kind}")
