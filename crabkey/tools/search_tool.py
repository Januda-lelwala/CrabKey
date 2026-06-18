from __future__ import annotations

import asyncio
import fnmatch
import re
import shutil
from pathlib import Path
from typing import Any

from .base import Tool, ToolContext

# Directories that are almost never what the user wants to search and are huge.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".venv-test", "dist", "build", ".mypy_cache", ".pytest_cache"}


def _resolve(base: str | None, ctx: ToolContext) -> Path:
    p = Path(base) if base else Path(ctx.working_dir)
    if not p.is_absolute():
        p = Path(ctx.working_dir) / p
    return p


class GrepTool(Tool):
    name = "search.grep"
    description = (
        "Search file contents for a regular expression. "
        "Returns matching lines formatted as path:line:text. Read-only."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression to search for."},
            "path": {"type": "string", "description": "Directory to search (defaults to project root)."},
            "glob": {"type": "string", "description": "Filename filter, e.g. '*.py' (default '*')."},
            "ignore_case": {"type": "boolean", "description": "Case-insensitive match (default false)."},
            "max_results": {"type": "integer", "description": "Cap on matches returned (default 200)."},
        },
        "required": ["pattern"],
    }

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        base = _resolve(arguments.get("path"), ctx)
        pattern = arguments["pattern"]
        glob = arguments.get("glob", "*")
        ignore_case = bool(arguments.get("ignore_case", False))
        max_results = int(arguments.get("max_results", 200))

        if shutil.which("rg"):
            lines = await self._run_ripgrep(base, pattern, glob, ignore_case, max_results)
        else:
            lines = self._run_python(base, pattern, glob, ignore_case, max_results)

        if not lines:
            return "No matches."
        return "\n".join(lines)

    async def _run_ripgrep(
        self, base: Path, pattern: str, glob: str, ignore_case: bool, max_results: int
    ) -> list[str]:
        args = ["rg", "--line-number", "--no-heading", "--color", "never"]
        if ignore_case:
            args.append("-i")
        if glob and glob != "*":
            args += ["-g", glob]
        args += ["-e", pattern, str(base)]
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        # rg exits 1 when there are no matches — that's not an error for us.
        out = stdout.decode(errors="replace").splitlines()
        return out[:max_results]

    def _run_python(
        self, base: Path, pattern: str, glob: str, ignore_case: bool, max_results: int
    ) -> list[str]:
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags)
        results: list[str] = []
        for path in self._walk(base, glob):
            try:
                text = path.read_text(encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, OSError):
                continue  # binary or unreadable — skip
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    results.append(f"{path}:{lineno}:{line.rstrip()}")
                    if len(results) >= max_results:
                        return results
        return results

    def _walk(self, base: Path, glob: str):
        if base.is_file():
            yield base
            return
        for path in sorted(base.rglob("*")):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.is_file() and fnmatch.fnmatch(path.name, glob):
                yield path


class GlobTool(Tool):
    name = "search.glob"
    description = "Find files matching a glob pattern (e.g. '**/*.py'). Returns sorted paths. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py' or 'src/*.ts'."},
            "path": {"type": "string", "description": "Base directory (defaults to project root)."},
            "max_results": {"type": "integer", "description": "Cap on paths returned (default 500)."},
        },
        "required": ["pattern"],
    }

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        base = _resolve(arguments.get("path"), ctx)
        pattern = arguments["pattern"]
        max_results = int(arguments.get("max_results", 500))

        matches = []
        for path in sorted(base.glob(pattern)):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.is_file():
                matches.append(str(path))
                if len(matches) >= max_results:
                    break
        if not matches:
            return "No files matched."
        return "\n".join(matches)
