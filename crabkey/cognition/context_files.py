"""Hierarchical context-file loading with @import resolution.

Mirrors Gemini CLI's GEMINI.md model: a global context file plus the project's
context file are merged, and either may pull in other files inline via
`@relative/path.md` references (recursively, with cycle/depth guards).
"""

from __future__ import annotations

import re
from pathlib import Path

# Matches an @import token: @ followed by a non-whitespace path.
_IMPORT_RE = re.compile(r"(?<!\S)@([^\s]+)")
_MAX_DEPTH = 10


def resolve_imports(
    text: str,
    base_dir: Path,
    _seen: set[Path] | None = None,
    _depth: int = 0,
) -> str:
    """Inline `@path` references in *text*, resolving each relative to *base_dir*.

    Unresolvable paths and tokens beyond the depth/cycle guards are left verbatim.
    """
    if _depth >= _MAX_DEPTH:
        return text
    seen = _seen if _seen is not None else set()

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(1)
        target = (base_dir / raw).expanduser()
        try:
            resolved = target.resolve()
        except OSError:
            return match.group(0)
        if not resolved.is_file() or resolved in seen:
            return match.group(0)  # missing or cyclic — leave the token as-is
        seen.add(resolved)
        inner = resolved.read_text(encoding="utf-8", errors="replace")
        return resolve_imports(inner, resolved.parent, seen, _depth + 1)

    return _IMPORT_RE.sub(_replace, text)


def load_context(files: list[Path]) -> str | None:
    """Merge the given context files (in priority order) into one document.

    Each file's @imports are resolved relative to that file's directory. Missing
    files are skipped. Returns None if nothing was found.
    """
    blocks: list[str] = []
    for path in files:
        path = path.expanduser()
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        blocks.append(resolve_imports(text, path.parent))
    if not blocks:
        return None
    return "\n\n".join(b.strip() for b in blocks if b.strip()) or None
