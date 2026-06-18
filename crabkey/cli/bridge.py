"""Headless JSON bridge between the CrabKey engine and the Ink (Node) TUI.

The Ink frontend spawns this module as a subprocess and talks to it over a
newline-delimited JSON protocol:

  Frontend → bridge (stdin, one JSON object per line):
    {"type": "prompt", "text": "..."}   run an agentic turn for this message
    {"type": "quit"}                      shut down

  bridge → frontend (stdout, one JSON object per line):
    {"type": "ready",   provider, model, missing_key, cwd, providers}
    {"type": "thinking"}                  model is being queried
    {"type": "text",       data}          assistant text block
    {"type": "tool_call",  tool, args}    a tool is about to run
    {"type": "tool_result",tool, data, is_error}
    {"type": "turn_end",   usage:{in,out,total_in,total_out}}
    {"type": "error",      data}

Everything written to stdout is protocol JSON; human/log output goes to stderr
so it never corrupts the stream the frontend parses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from ..cognition.context_assembler import ContextAssembler
from ..cognition.memory_manager import MemoryManager
from ..mal.message import Message, Role, ToolResult
from ..mal.plugin_provider import PluginModelProvider
from ..mal.provider import ModelConfig
from ..mal.provider_registry import list_providers
from ..persistence.config import ProjectConfig
from ..persistence.db import Db
from ..safety.permission_broker import Permission, PermissionBroker, PermissionLevel
from ..safety.sandbox import Sandbox, SandboxConfig
from ..tools import default_registry
from ..tools.base import ToolContext
from ..tools.shell_tool import ShellTool

_CRABKEY_ENV_FILE = Path.home() / ".config" / "crabkey" / "env"

_SYSTEM_PROMPT = (
    "You are CrabKey, an agentic coding assistant running in a terminal UI. "
    "Work methodically and use the available tools to inspect and edit files, "
    "run shell commands, and fetch the web. Prefer minimal, targeted edits. "
    "Keep prose concise; the user is reading you in a TUI."
)

_DEFAULT_TOOLS = ["file.read", "file.list", "file.write", "file.edit", "shell.run", "web.fetch"]


def _load_crabkey_env() -> None:
    """Mirror app.py: load saved API keys without overriding the live env."""
    if not _CRABKEY_ENV_FILE.exists():
        return
    for line in _CRABKEY_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip("\"'"))


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _format_error(provider: PluginModelProvider, exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    profile = provider.profile
    if "401" in msg or "403" in msg or "authentication" in low or "api key" in low:
        var = provider.missing_key() or next(
            (v for v in profile.env_vars if "API_KEY" in v.upper() or "TOKEN" in v.upper()), None
        )
        hint = f" Set {var} or run `crabkey configure`." if var else " Run `crabkey configure`."
        return f"Authentication failed for provider '{profile.name}'.{hint}"
    if "404" in msg or ("model" in low and "not found" in low):
        return f"Model not found. Run `crabkey models {profile.name}` to see available models."
    if "429" in msg or "rate limit" in low:
        return f"Rate limited by {profile.name}. Wait a moment and retry."
    return f"Provider error ({profile.name}): {msg}"


class BridgeSession:
    def __init__(self, cwd: Path, provider: PluginModelProvider, config: ProjectConfig) -> None:
        self._cwd = cwd
        self._provider = provider
        self._config = config
        self._history: list[Message] = []
        self._tool_ctx = ToolContext(working_dir=str(cwd))
        self._total_in = 0
        self._total_out = 0

        memory = MemoryManager(context_file=cwd / ".crabkey" / "CONTEXT.md")
        self._assembler = ContextAssembler(memory)

        self._broker = PermissionBroker()
        for tool in _DEFAULT_TOOLS:
            self._broker.add_rule(Permission(tool=tool, level=PermissionLevel.ALLOW))

        sandbox = Sandbox(SandboxConfig(allowed_paths=[cwd]))
        self._tools = default_registry()
        self._tools.register(ShellTool(sandbox=sandbox))

        self._model_config = ModelConfig(
            model=config.model,
            max_tokens=config.max_tokens,
            system=_SYSTEM_PROMPT,
        )

    async def run_turn(self, text: str, max_iterations: int = 20) -> None:
        self._history.append(Message(role=Role.USER, content=text))

        for _ in range(max_iterations):
            _emit({"type": "thinking"})
            prompt = await self._assembler.build(self._history, base_system=self._model_config.system)
            try:
                resp = await self._provider.complete(
                    prompt, self._model_config, tools=self._tools.schemas()
                )
            except Exception as exc:  # noqa: BLE001 — surface every failure to the UI
                _emit({"type": "error", "data": _format_error(self._provider, exc)})
                return

            self._total_in += resp.usage.input_tokens
            self._total_out += resp.usage.output_tokens

            if resp.message.content:
                _emit({"type": "text", "data": resp.message.content})

            self._history.append(resp.message)

            if resp.stop_reason == "end_turn" or not resp.message.tool_calls:
                break

            results: list[ToolResult] = []
            for tc in resp.message.tool_calls:
                _emit({"type": "tool_call", "tool": tc.name, "args": json.dumps(tc.arguments)})
                try:
                    self._broker.require(tc.name)
                    tool = self._tools.get(tc.name)
                    output = await tool.run(tc.arguments, self._tool_ctx)
                    is_error = False
                except Exception as exc:  # noqa: BLE001
                    output = f"Error: {exc}"
                    is_error = True
                _emit({"type": "tool_result", "tool": tc.name, "data": output, "is_error": is_error})
                results.append(
                    ToolResult(tool_call_id=tc.id, name=tc.name, content=output, is_error=is_error)
                )
            self._history.append(Message(role=Role.TOOL, tool_results=results))

        _emit({
            "type": "turn_end",
            "usage": {
                "total_in": self._total_in,
                "total_out": self._total_out,
            },
        })


async def _read_line() -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sys.stdin.readline)


async def main_async(args: argparse.Namespace) -> None:
    _load_crabkey_env()

    cwd = Path(args.cwd).resolve()
    config = ProjectConfig.from_project_dir(cwd)
    if args.provider:
        config.provider = args.provider
    if args.model:
        config.model = args.model

    try:
        provider = PluginModelProvider.from_name(config.provider)
    except KeyError:
        _emit({"type": "error", "data": f"Unknown provider: {config.provider!r}"})
        return

    # Touch the DB so the project is initialized like the other commands.
    db = Db(cwd / ".crabkey" / "memory.db")
    try:
        await db.initialize()
    except Exception:  # noqa: BLE001 — DB is non-essential for the TUI
        pass

    session = BridgeSession(cwd, provider, config)

    _emit({
        "type": "ready",
        "provider": config.provider,
        "model": config.model,
        "missing_key": provider.missing_key(),
        "cwd": str(cwd),
        "providers": sorted(p.name for p in list_providers()),
    })

    while True:
        line = await _read_line()
        if not line:  # EOF — parent closed the pipe
            break
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError:
            continue

        kind = cmd.get("type")
        if kind == "quit":
            break
        if kind == "prompt":
            text = (cmd.get("text") or "").strip()
            if text:
                await session.run_turn(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="CrabKey TUI JSON bridge (internal)")
    parser.add_argument("--cwd", default=str(Path.cwd()))
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args))
    except (KeyboardInterrupt, BrokenPipeError):
        pass


if __name__ == "__main__":
    main()
