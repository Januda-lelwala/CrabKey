from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any

from .base import Tool, ToolContext


class FileReadTool(Tool):
    name = "file.read"
    description = "Read the contents of a file. Returns the text content."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or repo-relative file path."},
            "offset": {"type": "integer", "description": "Line number to start reading from (1-indexed)."},
            "limit": {"type": "integer", "description": "Maximum number of lines to return."},
        },
        "required": ["path"],
    }

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        path = Path(arguments["path"])
        if not path.is_absolute():
            path = Path(ctx.working_dir) / path
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        offset = max(0, arguments.get("offset", 1) - 1)
        limit = arguments.get("limit", len(lines))
        return "".join(lines[offset : offset + limit])


class FileWriteTool(Tool):
    name = "file.write"
    description = "Write (overwrite) a file with the given content."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        path = Path(arguments["path"])
        if not path.is_absolute():
            path = Path(ctx.working_dir) / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments["content"], encoding="utf-8")
        return f"Written {len(arguments['content'])} bytes to {path}."


class FileEditTool(Tool):
    name = "file.edit"
    description = "Replace an exact string in a file. Fails if the old_string is not found or is ambiguous."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
        },
        "required": ["path", "old_string", "new_string"],
    }

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        path = Path(arguments["path"])
        if not path.is_absolute():
            path = Path(ctx.working_dir) / path
        old, new = arguments["old_string"], arguments["new_string"]
        content = path.read_text(encoding="utf-8")
        count = content.count(old)
        if count == 0:
            raise ValueError(f"old_string not found in {path}.")
        if count > 1:
            raise ValueError(f"old_string appears {count} times in {path}; provide more context.")
        updated = content.replace(old, new, 1)
        path.write_text(updated, encoding="utf-8")
        diff = "".join(difflib.unified_diff(
            content.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
            n=3,
        ))
        return diff or "No visible diff."


class FileListTool(Tool):
    name = "file.list"
    description = "List files in a directory (non-recursive by default)."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "recursive": {"type": "boolean"},
        },
        "required": ["path"],
    }

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        base = Path(arguments["path"])
        if not base.is_absolute():
            base = Path(ctx.working_dir) / base
        recursive = arguments.get("recursive", False)
        if recursive:
            paths = sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())
        else:
            paths = sorted(str(p.name) for p in base.iterdir())
        return "\n".join(paths)
