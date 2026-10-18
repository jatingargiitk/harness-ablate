"""Discover the pieces of a coding-agent harness.

A *piece* is the unit we ablate:
  * one section of CLAUDE.md / .claude/CLAUDE.md / AGENTS.md (split by markdown heading)
  * one skill directory under .claude/skills/
  * one hook entry in .claude/settings.json

Piece ids are stable across runs, e.g. ``claude_md:"## Testing"``, ``skill:pdf``,
``hook:PostToolUse[0]``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MEMORY_FILES = {
    "CLAUDE.md": "claude_md",
    ".claude/CLAUDE.md": "claude_md(.claude)",
    "AGENTS.md": "agents_md",
}
SKILLS_DIR = ".claude/skills"
SETTINGS_FILE = ".claude/settings.json"
HARNESS_PATHS = ["CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude"]

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
PREAMBLE = "(preamble)"
WHOLE_FILE = "(whole file)"


def tokens_of(text: str) -> int:
    """Rough token count: characters / 4."""
    return (len(text) + 3) // 4


@dataclass
class Section:
    title: str  # e.g. "## Testing", "(preamble)", "(whole file)"
    start: int  # first line index (inclusive)
    end: int  # last line index (exclusive)
    text: str


@dataclass
class Piece:
    id: str
    kind: str  # claude_md | agents_md | skill | hook
    path: str  # relative to the project dir
    title: str
    tokens: int
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------ sections
def headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(line index, level, text) for every ATX heading outside fenced code blocks."""
    out = []
    fence: str | None = None
    for i, line in enumerate(lines):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and line.strip() == marker:
                fence = None
            continue
        if fence is not None:
            continue
        h = HEADING_RE.match(line)
        if h:
            out.append((i, len(h.group(1)), h.group(2).strip()))
    return out


def split_level(heads: list[tuple[int, int, str]]) -> int | None:
    """Heading level that defines a piece.

    The shallowest level in the file, except when there is exactly one heading
    at that level and it comes first (a document title): then the next level.
    Deeper headings stay inside their parent section.
    """
    if not heads:
        return None
    levels = sorted({lvl for _, lvl, _ in heads})
    top = levels[0]
    tops = [h for h in heads if h[1] == top]
    if len(tops) == 1 and heads[0][1] == top and len(levels) > 1:
        return levels[1]
    return top


def split_sections(text: str) -> list[Section]:
    """Split markdown into ablatable sections. Concatenating them returns ``text``."""
    lines = text.splitlines(keepends=True)
    heads = headings([ln.rstrip("\n") for ln in lines])
    level = split_level(heads)
    if level is None:
        return [Section(WHOLE_FILE, 0, len(lines), text)] if text.strip() else []
    starts = [(i, f"{'#' * lvl} {t}") for i, lvl, t in heads if lvl == level]
    sections: list[Section] = []
    if starts[0][0] > 0:
        pre = "".join(lines[: starts[0][0]])
        sections.append(Section(PREAMBLE, 0, starts[0][0], pre))
    for n, (i, title) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        sections.append(Section(title, i, end, "".join(lines[i:end])))
    return sections


def section_ids(prefix: str, sections: list[Section]) -> list[str]:
    seen: dict[str, int] = {}
    ids = []
    for s in sections:
        seen[s.title] = seen.get(s.title, 0) + 1
        suffix = f"#{seen[s.title]}" if seen[s.title] > 1 else ""
        ids.append(f'{prefix}:"{s.title}"{suffix}')
    return ids


# ------------------------------------------------------------------ discovery
def memory_pieces(project: Path) -> list[Piece]:
    pieces = []
    for rel, prefix in MEMORY_FILES.items():
        path = project / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        sections = split_sections(text)
        for sid, s in zip(section_ids(prefix, sections), sections):
            if not s.text.strip():
                continue
            pieces.append(Piece(
                id=sid, kind=prefix.split("(")[0], path=rel, title=s.title, tokens=tokens_of(s.text),
                detail={"lines": [s.start + 1, s.end]},
            ))
    return pieces


def skill_pieces(project: Path) -> list[Piece]:
    root = project / SKILLS_DIR
    if not root.is_dir():
        return []
    pieces = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        skill_md = d / "SKILL.md"
        if not skill_md.is_file():
            continue
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^description:\s*(.+)$", text, re.M)
        pieces.append(Piece(
            id=f"skill:{d.name}", kind="skill", path=f"{SKILLS_DIR}/{d.name}", title=d.name,
            tokens=tokens_of(text), detail={"description": m.group(1).strip() if m else ""},
        ))
    return pieces


def load_settings(project: Path) -> dict[str, Any] | None:
    path = project / SETTINGS_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def hook_pieces(project: Path) -> list[Piece]:
    settings = load_settings(project)
    hooks = (settings or {}).get("hooks") or {}
    pieces = []
    if not isinstance(hooks, dict):
        return pieces
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for i, entry in enumerate(entries):
            cmds = [h.get("command", "") for h in (entry.get("hooks") or []) if isinstance(h, dict)]
            pieces.append(Piece(
                id=f"hook:{event}[{i}]", kind="hook", path=SETTINGS_FILE,
                title=f"{event}[{i}]" + (f" matcher={entry.get('matcher')}" if entry.get("matcher") else ""),
                tokens=0,  # hooks cost no prompt tokens directly; their effect shows up in the run
                detail={"event": event, "index": i, "matcher": entry.get("matcher"), "commands": cmds},
            ))
    return pieces


def discover(project: str | Path) -> list[Piece]:
    project = Path(project)
    return memory_pieces(project) + skill_pieces(project) + hook_pieces(project)


def user_level_harness(home: str | Path | None = None) -> list[str]:
    """Human-readable list of user-level harness files that load in every run."""
    home = Path(home) if home else Path.home()
    found = []
    claude_md = home / ".claude" / "CLAUDE.md"
    if claude_md.is_file():
        found.append(f"~/.claude/CLAUDE.md (~{tokens_of(claude_md.read_text(errors='replace')):,} tokens)")
    skills = home / ".claude" / "skills"
    if skills.is_dir():
        n = sum(1 for d in skills.iterdir() if (d / "SKILL.md").is_file())
        if n:
            found.append(f"~/.claude/skills ({n} skills)")
    settings = home / ".claude" / "settings.json"
    if settings.is_file():
        try:
            hooks = json.loads(settings.read_text()).get("hooks") or {}
            n = sum(len(v) for v in hooks.values() if isinstance(v, list))
            if n:
                found.append(f"~/.claude/settings.json ({n} hook entries)")
        except (json.JSONDecodeError, AttributeError):
            pass
    return found
