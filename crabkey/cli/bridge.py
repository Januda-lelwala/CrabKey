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

This drives the *same* LoopEngine the `crabkey run` command uses, so the TUI
gets the full feature set — tools, checkpoints, MCP servers, extensions,
sub-agents, hierarchical context, and telemetry — with no separate loop to keep
in sync.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from ..cognition.context_assembler import ContextAssembler
from ..cognition.memory_manager import MemoryManager
from ..mal.message import Message, Role
from ..mal.plugin_provider import PluginModelProvider
from ..mal.provider import ModelConfig
from ..mal.provider_registry import list_providers
from ..observability import Telemetry
from ..orchestration.agent_router import AgentRouter
from ..orchestration.hook_dispatcher import HookDispatcher
from ..orchestration.loop_engine import LoopConfig, LoopEngine, StepEvent
from ..orchestration.session_manager import SessionManager
from ..orchestration.thread_manager import ThreadManager
from ..persistence.config import ProjectConfig
from ..persistence.db import Db
from ..safety.checkpoint import Checkpoint
from ..safety.permission_broker import Permission, PermissionBroker, PermissionLevel
from ..safety.sandbox import Sandbox, SandboxConfig
from ..tools import ToolRegistry, default_registry, load_mcp_servers
from ..tools.agent_tool import AgentDispatchTool
from ..tools.memory_tool import SaveMemoryTool
from ..tools.shell_tool import ShellTool
from .commands import load_custom_commands
from .extensions import load_extensions
from .repl import ConversationContext

_CRABKEY_ENV_FILE = Path.home() / ".config" / "crabkey" / "env"
_GLOBAL_CONTEXT_FILE = Path.home() / ".config" / "crabkey" / "CONTEXT.md"
_GLOBAL_COMMANDS_DIR = Path.home() / ".config" / "crabkey" / "commands"

_SYSTEM_PROMPT = (
    "You are CrabKey, an agentic coding assistant running in a terminal UI. "
    "Work methodically and use the available tools to inspect and edit files, "
    "run shell commands, search the codebase, and fetch the web. Prefer minimal, "
    "targeted edits. Keep prose concise; the user is reading you in a TUI."
)


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


def _make_summarizer(provider: PluginModelProvider, model: str):
    cfg = ModelConfig(model=model, max_tokens=512)

    async def summarize(messages: list[Message]) -> str:
        excerpt = "\n".join(f"[{m.role.value}] {m.content or ''}" for m in messages)
        prompt = [
            Message(role=Role.SYSTEM, content=(
                "Summarize this earlier portion of a coding session concisely, "
                "preserving decisions made, file paths touched, and any open tasks."
            )),
            Message(role=Role.USER, content=excerpt),
        ]
        try:
            resp = await provider.complete(prompt, cfg)
            return resp.message.content or ""
        except Exception:  # noqa: BLE001 — summarization is best-effort
            return ""

    return summarize


class BridgeSession:
    """Drives the LoopEngine and owns session/thread state for the TUI.

    Conversation history is sourced from the active session/thread (via
    ConversationContext), so /session and /thread switch what the model sees.
    """

    def __init__(
        self,
        cwd: Path,
        provider: PluginModelProvider,
        loop: LoopEngine,
        model_config: ModelConfig,
        db: Db,
        session_mgr: SessionManager,
        thread_mgr: ThreadManager,
        ctx: ConversationContext,
    ) -> None:
        self._cwd = cwd
        self._provider = provider
        self._loop = loop
        self._model_config = model_config
        self._db = db
        self._session_mgr = session_mgr
        self._thread_mgr = thread_mgr
        self._ctx = ctx

    def _current_id(self) -> str:
        thr = self._ctx.thread
        return thr.id if thr is not None else self._ctx.session.id

    def _emit_state(self) -> None:
        sess = self._ctx.session
        thr = self._ctx.thread
        _emit({
            "type": "state",
            "session": sess.name if sess else None,
            "thread": thr.name if thr else None,
        })

    async def run_turn(self, text: str) -> None:
        _emit({"type": "thinking"})

        def on_event(evt: StepEvent) -> None:
            if evt.kind == "text" and evt.data:
                _emit({"type": "text", "data": evt.data})
            elif evt.kind == "tool_call":
                _emit({"type": "tool_call", "tool": evt.tool_name, "args": evt.data})
            elif evt.kind == "tool_result":
                _emit({"type": "tool_result", "tool": evt.tool_name, "data": evt.data, "is_error": evt.is_error})
            elif evt.kind == "error":
                _emit({"type": "error", "data": evt.data})

        cur_id = self._current_id()
        # Prior turns from the active session/thread become the model's context.
        history = list(self._ctx.get_context_messages())
        await self._ctx.append_user(text)
        try:
            await self._loop.run(
                goal=text,
                thread_id=cur_id,
                model_config=self._model_config,
                working_dir=str(self._cwd),
                on_event=on_event,
                history=history,
            )
        except Exception as exc:  # noqa: BLE001 — surface every failure to the UI
            _emit({"type": "error", "data": _format_error(self._provider, exc)})
            return

        final = next((m.content for m in reversed(history) if m.role == Role.ASSISTANT and m.content), "")
        if final:
            await self._ctx.append_assistant(final)

        total_in, total_out = await self._db.total_cost_tokens(cur_id)
        _emit({"type": "turn_end", "usage": {"total_in": total_in, "total_out": total_out}})

    async def handle_session(self, action: str | None, name: str | None) -> None:
        if action == "new":
            sess = await self._session_mgr.new(name or None)
            self._thread_mgr.exit_thread()
            _emit({"type": "info", "data": f"New session: {sess.name}"})
        elif action == "switch":
            try:
                sess = await self._session_mgr.switch(name or "")
                self._thread_mgr.exit_thread()
                _emit({"type": "info", "data": f"Switched to session: {sess.name}"})
            except KeyError:
                _emit({"type": "error", "data": f"Session {name!r} not found"})
                return
        elif action == "list":
            records = await self._session_mgr.list_all()
            active = self._session_mgr.active
            lines = [
                f"  {'→' if active and r.id == active.id else ' '} {r.name}  [{r.id[:8]}]"
                for r in records
            ] or ["  (no sessions)"]
            _emit({"type": "info", "data": "Sessions:\n" + "\n".join(lines)})
            return
        else:
            _emit({"type": "info", "data": "Usage: /session new|list|switch [name]"})
            return
        self._emit_state()

    async def handle_thread(self, action: str | None, name: str | None) -> None:
        session = self._session_mgr.active
        if session is None:
            _emit({"type": "error", "data": "No active session. Use /session new first."})
            return
        if action == "new":
            thread = await self._thread_mgr.new(
                session_id=session.id, name=name or None, forked_at=len(session.messages)
            )
            _emit({"type": "info", "data": f"New thread: {thread.name} (forked at {thread.forked_at} messages)"})
        elif action == "exit":
            thr = self._thread_mgr.active
            if thr is None:
                _emit({"type": "info", "data": "Not in a thread."})
                return
            self._thread_mgr.exit_thread()
            _emit({"type": "info", "data": f"Exited thread {thr.name} — back to session {session.name}"})
        elif action == "list":
            records = await self._db.list_threads_for_session(session.id)
            active = self._thread_mgr.active
            lines = [
                f"  {'→' if active and r.id == active.id else ' '} {r.name}  [{r.id[:8]}] forked@{r.forked_at}"
                for r in records
            ] or ["  (no threads)"]
            _emit({"type": "info", "data": "Threads:\n" + "\n".join(lines)})
            return
        else:
            _emit({"type": "info", "data": "Usage: /thread new|list|exit [name]"})
            return
        self._emit_state()


async def _build_session(cwd: Path, config: ProjectConfig, provider: PluginModelProvider):
    """Assemble the shared LoopEngine for the TUI.

    Returns (session, mcp_clients, custom_commands)."""
    db = Db(cwd / ".crabkey" / "memory.db")
    await db.initialize()

    session_mgr = SessionManager(db)
    thread_mgr = ThreadManager(db)
    session = await session_mgr.new(name="main")
    ctx = ConversationContext(session_mgr, thread_mgr, db)

    extensions = load_extensions(cwd)

    memory = MemoryManager(
        context_file=cwd / ".crabkey" / "CONTEXT.md",
        global_context_file=_GLOBAL_CONTEXT_FILE,
        extra_context_files=extensions.context_files,
    )
    assembler = ContextAssembler(memory, summarizer=_make_summarizer(provider, config.model))

    # The TUI streams every tool call/result live, so auto-approve (like --yolo).
    broker = PermissionBroker()
    broker.add_rule(Permission(tool="*", level=PermissionLevel.ALLOW))

    sandbox = Sandbox(SandboxConfig(allowed_paths=[cwd]))
    tools = default_registry()
    tools.register(ShellTool(sandbox=sandbox))
    tools.register(SaveMemoryTool(context_file=cwd / ".crabkey" / "CONTEXT.md"))

    mcp_clients = await load_mcp_servers(list(config.mcp_servers) + extensions.mcp_servers, tools)

    # Sub-agents from config become dispatchable (recursion-guarded toolset).
    agent_router = AgentRouter()
    for agent_cfg in config.agents.values():
        agent_router.from_config(agent_cfg, provider)
    agent_names = agent_router.list_agents()
    if agent_names:
        sub_tools = ToolRegistry()
        for t in tools:
            sub_tools.register(t)

        async def _dispatch(agent_name: str, task: str) -> str:
            agent = agent_router.get(agent_name)
            sub_thread = await thread_mgr.new(session_id=session.id, name=f"sub:{agent_name}")
            sub_loop = LoopEngine(
                provider=agent.provider, tools=sub_tools, assembler=assembler,
                db=db, broker=broker, config=LoopConfig(max_iterations=8, stream=False),
            )
            sub_history = await sub_loop.run(
                goal=task, thread_id=sub_thread.id, model_config=agent.config, working_dir=str(cwd),
            )
            final = next((m.content for m in reversed(sub_history) if m.role == Role.ASSISTANT and m.content), "")
            return final or "(sub-agent produced no output)"

        tools.register(AgentDispatchTool(_dispatch, agent_names))

    checkpoint = Checkpoint(repo_root=cwd) if (cwd / ".git").exists() else None

    hooks = HookDispatcher()
    trace_file = os.environ.get("CRABKEY_TRACE_FILE")
    if trace_file or os.environ.get("CRABKEY_OTEL") == "1":
        Telemetry(trace_file=trace_file, otel=os.environ.get("CRABKEY_OTEL") == "1").register(hooks)

    model_config = ModelConfig(model=config.model, max_tokens=config.max_tokens, system=_SYSTEM_PROMPT)

    # stream=False: the TUI renders one assistant bubble per turn, not token deltas.
    loop = LoopEngine(
        provider=provider, tools=tools, assembler=assembler, db=db, broker=broker,
        config=LoopConfig(max_iterations=20, stream=False),
        hooks=hooks, checkpoint=checkpoint, approver=None,
    )

    # Custom slash commands: global → extensions → project (later overrides earlier).
    command_dirs = [_GLOBAL_COMMANDS_DIR, *extensions.command_dirs, cwd / ".crabkey" / "commands"]
    custom_commands = load_custom_commands(command_dirs)

    session_obj = BridgeSession(
        cwd, provider, loop, model_config, db, session_mgr, thread_mgr, ctx
    )
    return session_obj, mcp_clients, custom_commands


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

    session, mcp_clients, custom_commands = await _build_session(cwd, config, provider)

    _emit({
        "type": "ready",
        "provider": config.provider,
        "model": config.model,
        "missing_key": provider.missing_key(),
        "cwd": str(cwd),
        "providers": sorted(p.name for p in list_providers()),
        "commands": [
            {"name": c.name, "description": c.description, "prompt": c.prompt}
            for c in custom_commands.values()
        ],
    })

    try:
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
            elif kind == "session":
                await session.handle_session(cmd.get("action"), cmd.get("name"))
            elif kind == "thread":
                await session.handle_thread(cmd.get("action"), cmd.get("name"))
    finally:
        for client in mcp_clients:
            await client.stop()


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
