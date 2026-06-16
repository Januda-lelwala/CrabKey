from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext
from ..safety.sandbox import Sandbox, SandboxConfig


class ShellTool(Tool):
    name = "shell.run"
    description = "Run a shell command and return its stdout/stderr. Restricted by sandbox policy."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute."},
            "cwd": {"type": "string", "description": "Working directory (defaults to project root)."},
            "timeout": {"type": "number", "description": "Timeout in seconds (default 30)."},
        },
        "required": ["command"],
    }

    def __init__(self, sandbox: Sandbox | None = None) -> None:
        self._sandbox = sandbox or Sandbox()

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        cwd = arguments.get("cwd", ctx.working_dir)
        timeout = arguments.get("timeout", 30.0)
        original_timeout = self._sandbox.config.timeout_seconds
        self._sandbox.config.timeout_seconds = timeout
        try:
            code, stdout, stderr = await self._sandbox.run(arguments["command"], cwd=cwd)
        finally:
            self._sandbox.config.timeout_seconds = original_timeout
        parts = []
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(f"[stderr]\n{stderr}")
        parts.append(f"[exit {code}]")
        return "\n".join(parts)
