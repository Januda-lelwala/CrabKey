from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolContext

_MEMORY_HEADING = "## CrabKey Memory"


class SaveMemoryTool(Tool):
    """Persist a durable fact to the project's CONTEXT.md.

    Facts saved here are loaded by the ContextAssembler into the system prompt on
    every future turn (and across sessions), so the agent can remember decisions,
    conventions, and user preferences. This mirrors Gemini CLI's save_memory.
    """

    name = "memory.save"
    description = (
        "Remember a durable fact about this project (a decision, convention, or "
        "user preference) so it is available in future turns and sessions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "A single concise fact to remember."},
        },
        "required": ["fact"],
    }

    def __init__(self, context_file: Path) -> None:
        self._context_file = context_file

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        fact = arguments["fact"].strip()
        if not fact:
            raise ValueError("Cannot save an empty fact.")

        existing = ""
        if self._context_file.exists():
            existing = self._context_file.read_text(encoding="utf-8")

        bullet = f"- {fact}"
        if bullet in existing:
            return f"Already remembered: {fact}"

        if _MEMORY_HEADING in existing:
            updated = self._append_under_heading(existing, bullet)
        else:
            sep = "" if not existing or existing.endswith("\n") else "\n"
            block = f"{sep}\n{_MEMORY_HEADING}\n{bullet}\n"
            updated = existing + block

        self._context_file.parent.mkdir(parents=True, exist_ok=True)
        self._context_file.write_text(updated, encoding="utf-8")
        return f"Remembered: {fact}"

    @staticmethod
    def _append_under_heading(existing: str, bullet: str) -> str:
        lines = existing.splitlines()
        out: list[str] = []
        inserted = False
        for i, line in enumerate(lines):
            out.append(line)
            if not inserted and line.strip() == _MEMORY_HEADING:
                # Find the end of this section's existing bullets and append after them.
                j = i + 1
                while j < len(lines) and lines[j].startswith("- "):
                    out.append(lines[j])
                    j += 1
                out.append(bullet)
                inserted = True
                out.extend(lines[j:])
                break
        return "\n".join(out) + "\n"
