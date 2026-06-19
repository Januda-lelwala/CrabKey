from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from ..cognition.context_assembler import ContextAssembler
from ..cognition.memory_manager import MemoryManager
from ..cognition.reflector import Reflector
from ..mal.message import Message, Role
from ..mal.plugin_provider import PluginModelProvider
from ..mal.provider import ModelConfig
from ..mal.provider_registry import get_provider_profile, list_providers
from ..orchestration.hook_dispatcher import HookDispatcher
from ..orchestration.loop_engine import LoopConfig, LoopEngine, StepEvent
from ..orchestration.planner import Planner
from ..orchestration.session_manager import SessionManager
from ..orchestration.thread_manager import ThreadManager
from ..persistence.config import ProjectConfig
from ..persistence.db import Db
from ..safety.checkpoint import Checkpoint
from ..safety.permission_broker import (
    ApprovalDecision,
    Approver,
    Permission,
    PermissionBroker,
    PermissionLevel,
)
from ..safety.sandbox import Sandbox, SandboxConfig
from ..tools import default_registry, load_mcp_servers
from ..tools.memory_tool import SaveMemoryTool
from ..tools.shell_tool import ShellTool
from . import ui
from .commands import load_custom_commands
from .extensions import load_extensions

_GLOBAL_CONTEXT_FILE = Path.home() / ".config" / "crabkey" / "CONTEXT.md"
_GLOBAL_COMMANDS_DIR = Path.home() / ".config" / "crabkey" / "commands"


def _make_summarizer(provider: PluginModelProvider, model: str):
    """Build a provider-backed summarizer for compressing dropped history."""
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
        except Exception:
            return ""  # summarization is best-effort; never break the loop

    return summarize

# Tools that never mutate the workspace — always safe to auto-approve.
_READONLY_TOOLS = (
    "file.read", "file.list", "search.grep", "search.glob",
    "web.fetch", "web.search", "memory.save",
)
# Tools that change files — auto-approved in auto-edit mode, asked otherwise.
_EDIT_TOOLS = ("file.write", "file.edit")

app = typer.Typer(
    name="crabkey",
    help="Model-agnostic agentic coding CLI.",
    add_completion=False,
)
console = Console()

_CRABKEY_ENV_FILE = Path.home() / ".config" / "crabkey" / "env"


def _load_crabkey_env() -> None:
    """Load API keys from ~/.config/crabkey/env into the current process's environment.

    Keys already present in the environment are NOT overwritten, so shell-level
    exports always take precedence.  This lets crabkey work immediately after
    'crabkey configure' without requiring the user to source their shell rc.
    """
    if not _CRABKEY_ENV_FILE.exists():
        return
    for line in _CRABKEY_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"\'')
        os.environ.setdefault(key, val)  # don't override if already set


_load_crabkey_env()


def _resolve_project(cwd: Path) -> tuple[Path, ProjectConfig, Path]:
    config_dir = cwd / ".crabkey"
    config = ProjectConfig.from_project_dir(cwd)
    db_path = config_dir / "memory.db"
    return config_dir, config, db_path


def _make_provider(config: ProjectConfig) -> PluginModelProvider:
    """Resolve provider by name via the plugin registry."""
    try:
        return PluginModelProvider.from_name(config.provider)
    except KeyError:
        known = [p.name for p in list_providers()]
        raise typer.BadParameter(
            f"Unknown provider: {config.provider!r}. "
            f"Available: {', '.join(sorted(known))}"
        )


def _make_approver(broker: PermissionBroker) -> Approver:
    """Build an interactive approver that prompts the user for ASK-level tools."""

    def approve(tool: str, arg: str | None) -> ApprovalDecision:
        console.print()
        detail = f" [dim]{arg}[/dim]" if arg else ""
        console.print(f"  [yellow]⚠[/yellow] [bold]{tool}[/bold] wants to run:{detail}")
        choice = Prompt.ask(
            "    Allow?",
            choices=["y", "n", "a"],
            default="y",
            show_choices=True,
        )
        if choice == "n":
            return ApprovalDecision.DENY
        if choice == "a":
            return ApprovalDecision.ALLOW_ALWAYS
        return ApprovalDecision.ALLOW_ONCE

    return approve


def _build_broker(allow_all: bool, auto_edit: bool) -> tuple[PermissionBroker, Approver | None]:
    """Configure the permission broker for the chosen approval mode.

    - allow_all (YOLO): everything is auto-approved, no prompts.
    - auto_edit: reads + file edits auto-approved, shell still asks.
    - default: only read-only tools auto-approved; edits and shell ask.
    """
    broker = PermissionBroker()
    if allow_all:
        broker.add_rule(Permission(tool="*", level=PermissionLevel.ALLOW))
        return broker, None

    for t in _READONLY_TOOLS:
        broker.add_rule(Permission(tool=t, level=PermissionLevel.ALLOW))
    if auto_edit:
        for t in _EDIT_TOOLS:
            broker.add_rule(Permission(tool=t, level=PermissionLevel.ALLOW))
    # Everything else (edits when not auto-edit, shell.run, MCP tools) → ASK.
    return broker, _make_approver(broker)


@app.command()
def run(
    goal: Optional[str] = typer.Argument(None, help="Goal for the agent. If omitted, enters interactive mode."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override the model."),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Override the provider."),
    max_iter: int = typer.Option(20, "--max-iter", help="Maximum loop iterations."),
    no_plan: bool = typer.Option(False, "--no-plan", help="Skip the planning step."),
    allow_all: bool = typer.Option(False, "--allow-all", "--yolo", help="Auto-approve ALL tools (dangerous)."),
    auto_edit: bool = typer.Option(False, "--auto-edit", help="Auto-approve file edits; still ask for shell."),
    no_checkpoint: bool = typer.Option(False, "--no-checkpoint", help="Disable git checkpoints before edits."),
    output: str = typer.Option("text", "--output", "-o", help="Output format: text or json (json implies headless)."),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Project root directory."),
) -> None:
    """Run CrabKey in agent mode toward a goal.

    Headless usage: pipe the goal on stdin (e.g. `echo "fix the bug" | crabkey run`)
    and/or pass `--output json` for machine-readable results and exit codes.
    """
    # Read the goal from stdin when piped and no goal argument was given.
    if goal is None and not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        goal = piped or None

    if output not in ("text", "json"):
        raise typer.BadParameter("--output must be 'text' or 'json'.")

    code = asyncio.run(_run_async(
        goal, model, provider, max_iter, no_plan, allow_all, auto_edit, no_checkpoint, output, cwd
    ))
    raise typer.Exit(code)


async def _run_async(
    goal: str | None,
    model_override: str | None,
    provider_override: str | None,
    max_iter: int,
    no_plan: bool,
    allow_all: bool,
    auto_edit: bool,
    no_checkpoint: bool,
    output: str,
    cwd: Path,
) -> int:
    config_dir, project_config, db_path = _resolve_project(cwd)

    if provider_override:
        project_config.provider = provider_override
    if model_override:
        project_config.model = model_override

    headless = output == "json"

    provider = _make_provider(project_config)
    db = Db(db_path)
    await db.initialize()

    # Extensions bundle MCP servers + context + commands under .crabkey/extensions/.
    extensions = load_extensions(cwd)

    context_file = config_dir / "CONTEXT.md"
    memory = MemoryManager(
        context_file=context_file,
        global_context_file=_GLOBAL_CONTEXT_FILE,
        extra_context_files=extensions.context_files,
    )
    summarizer = _make_summarizer(provider, project_config.model)
    assembler = ContextAssembler(memory, summarizer=summarizer)
    reflector = Reflector(provider)
    planner = Planner(provider)
    session_mgr = SessionManager(db)
    thread_mgr = ThreadManager(db)

    # In headless mode there is no human to answer prompts, so never use the
    # interactive approver — ASK-level tools are refused unless --yolo/--auto-edit.
    broker, approver = _build_broker(allow_all, auto_edit)
    if headless:
        approver = None

    sandbox = Sandbox(SandboxConfig(allowed_paths=[cwd]))
    tools = default_registry()
    tools.register(ShellTool(sandbox=sandbox))
    tools.register(SaveMemoryTool(context_file=context_file))

    # Register MCP servers from config ([[mcp_servers]]) plus any from extensions.
    all_mcp_servers = list(project_config.mcp_servers) + extensions.mcp_servers
    mcp_clients = await load_mcp_servers(all_mcp_servers, tools)
    if mcp_clients and not headless:
        console.print(f"[dim]Connected {len(mcp_clients)} MCP server(s).[/dim]")
    if extensions.names and not headless:
        console.print(f"[dim]Loaded extensions: {', '.join(extensions.names)}.[/dim]")

    # Checkpoints require a git repo; silently skip if this isn't one.
    checkpoint: Checkpoint | None = None
    if not no_checkpoint and (cwd / ".git").exists():
        checkpoint = Checkpoint(repo_root=cwd)

    hooks = HookDispatcher()

    model_config = ModelConfig(
        model=project_config.model,
        max_tokens=project_config.max_tokens,
        system="You are CrabKey, an agentic coding assistant. Work methodically. Always prefer minimal, targeted edits.",
    )

    loop = LoopEngine(
        provider=provider,
        tools=tools,
        assembler=assembler,
        db=db,
        broker=broker,
        reflector=reflector,
        config=LoopConfig(max_iterations=max_iter),
        hooks=hooks,
        checkpoint=checkpoint,
        approver=approver,
    )

    if goal is None:
        if headless:
            # Bypass Rich: it soft-wraps and parses [..] markup, corrupting JSON.
            print(json.dumps({"status": "error", "error": "No goal provided."}))
            return 2
        goal = Prompt.ask("[bold cyan]Goal[/bold cyan]")

    # A thread forks from a session, so create the session first.
    session = await session_mgr.new(name=goal[:60])
    thread = await thread_mgr.new(session_id=session.id, name=goal[:60])

    if not headless:
        console.print()
        console.print(Panel(
            f"[bold]{goal}[/bold]",
            title="[bold cyan]Goal[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))

    if not no_plan:
        if headless:
            plan = await planner.plan(goal)
        else:
            console.print()
            ui.section_header(console, "Planning", "▸")
            with ui.spinner_status(console, "Generating plan…"):
                plan = await planner.plan(goal)
            if plan.steps:
                lines = "\n".join(f"[bold]{s.index}.[/bold] {s.description}" + (f" [dim][{s.tool_hint}][/dim]" if s.tool_hint else "") for s in plan.steps)
                console.print(Panel(Markdown(lines), title="[bold]Plan[/bold]", border_style="yellow", padding=(1, 2)))

    if not headless:
        console.print()
        ui.section_header(console, "Execution", "▸")
        console.print()

    # Collected for JSON output; ignored in text mode.
    collected: list[dict] = []
    saw_error = {"value": False}

    # Tracks whether we're mid-stream so we can flush a newline before the next
    # non-delta event (tool call / done) renders.
    stream_state = {"active": False}

    def _end_stream() -> None:
        if stream_state["active"]:
            console.file.write("\n")
            console.file.flush()
            stream_state["active"] = False

    def on_event(evt: StepEvent) -> None:
        if evt.kind == "error":
            saw_error["value"] = True
        if headless:
            collected.append({"kind": evt.kind, "tool": evt.tool_name, "data": evt.data, "iteration": evt.iteration})
            return
        if evt.kind == "text_delta":
            console.file.write(evt.data)
            console.file.flush()
            stream_state["active"] = True
            return
        _end_stream()
        if evt.kind == "text" and evt.data:
            console.print(Markdown(evt.data))
        elif evt.kind == "tool_call":
            tool_snippet = evt.data[:80] + ("…" if len(evt.data) > 80 else "")
            console.print(f"  [cyan]→[/cyan] [dim]{evt.tool_name}({tool_snippet})[/dim]")
        elif evt.kind == "tool_result":
            preview = evt.data[:150].replace("\n", " ")
            console.print(f"  [cyan]←[/cyan] [dim]{preview}[/dim]")
        elif evt.kind == "done":
            console.print("[green]✓[/green] [bold]Done[/bold]")
        elif evt.kind == "error":
            console.print(f"[red]✗[/red] {evt.data}")

    exit_code = 0
    try:
        history = await loop.run(goal=goal, thread_id=thread.id, model_config=model_config, working_dir=str(cwd), on_event=on_event)
    except Exception as exc:
        if headless:
            print(json.dumps({"status": "error", "error": str(exc), "thread_id": thread.id}))
        else:
            console.print(f"[red]✗[/red] {exc}")
        return 1
    finally:
        for client in mcp_clients:
            await client.stop()

    total_in, total_out = await db.total_cost_tokens(thread.id)

    if headless:
        final_text = next(
            (m.content for m in reversed(history) if m.role == Role.ASSISTANT and m.content),
            "",
        )
        print(json.dumps({
            "status": "error" if saw_error["value"] else "ok",
            "goal": goal,
            "thread_id": thread.id,
            "result": final_text,
            "events": collected,
            "tokens": {"input": total_in, "output": total_out},
        }))
        return 1 if saw_error["value"] else 0

    console.print(f"\n[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]")
    console.print(f"[dim]Tokens: {total_in:,} in · {total_out:,} out · thread {thread.id[:8]}[/dim]")
    console.print()
    return exit_code


@app.command()
def tui(
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Override the provider."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override the model."),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Project root directory."),
) -> None:
    """Launch the beautiful Ink (React) terminal UI."""
    from .launcher import launch_tui

    raise typer.Exit(launch_tui(cwd, provider, model))


@app.command()
def threads(
    cwd: Path = typer.Option(Path.cwd(), "--cwd"),
) -> None:
    """List conversation threads for this project."""
    asyncio.run(_list_threads(cwd))


async def _list_threads(cwd: Path) -> None:
    _, _, db_path = _resolve_project(cwd)
    db = Db(db_path)
    await db.initialize()
    found = False
    for session in await db.list_sessions():
        for t in await db.list_threads_for_session(session.id):
            found = True
            console.print(f"  {t.id[:8]}  [dim]{session.name}[/dim]  {t.name}")
    if not found:
        console.print("[dim]No threads yet.[/dim]")


@app.command()
def restore(
    sha: Optional[str] = typer.Argument(None, help="Checkpoint SHA to restore. Omit to list checkpoints."),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Project root directory."),
) -> None:
    """List CrabKey git checkpoints, or restore the workspace to one (hard reset)."""
    asyncio.run(_restore_async(sha, cwd))


async def _restore_async(sha: str | None, cwd: Path) -> None:
    if not (cwd / ".git").exists():
        ui.error_message(console, f"{cwd} is not a git repository — no checkpoints available.")
        raise typer.Exit(1)

    ckpt = Checkpoint(repo_root=cwd)
    checkpoints = await ckpt.list()

    if sha is None:
        if not checkpoints:
            console.print("[dim]No CrabKey checkpoints found.[/dim]")
            return
        console.print()
        ui.section_header(console, "Checkpoints", "▸")
        for info in checkpoints:
            console.print(f"  [cyan]{info.sha[:8]}[/cyan]  {info.label}")
        console.print("\n[dim]Restore with: crabkey restore <sha>[/dim]\n")
        return

    match = next((c for c in checkpoints if c.sha.startswith(sha)), None)
    if match is None:
        ui.error_message(console, f"No checkpoint matching {sha!r}. Run 'crabkey restore' to list them.")
        raise typer.Exit(1)
    await ckpt.restore(match)
    console.print(f"[green]✓[/green] Restored workspace to [cyan]{match.sha[:8]}[/cyan] ({match.label})")


@app.command(name="providers")
def list_providers_cmd() -> None:
    """List all registered model providers."""
    from rich.table import Table
    from ..mal.provider_registry import list_providers as _list

    ui.header_banner(console, "CrabKey Providers")
    table = Table(title=None, show_lines=False, show_header=True, header_style="bold cyan", padding=(0, 2))
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Mode", style="dim")
    table.add_column("Env var(s)", style="dim")
    table.add_column("Description")

    for p in sorted(_list(), key=lambda x: x.name):
        env = ", ".join(p.env_vars[:2]) or "—"
        table.add_row(p.name, p.api_mode, env, p.description or p.display_name)

    console.print(Panel(table, border_style="cyan", padding=(1, 2)))
    console.print()


@app.command(name="models")
def list_models_cmd(
    provider: str = typer.Argument(..., help="Provider name (e.g. anthropic, openrouter)"),
) -> None:
    """List agentic models available for a provider (from models.dev catalog)."""
    from ..mal.model_catalog import list_agentic_models
    from ..mal.provider_registry import get_provider_profile

    profile = get_provider_profile(provider)
    if profile is None:
        ui.error_message(console, f"Unknown provider: {provider!r}. Run 'crabkey providers' to see available providers.")
        raise typer.Exit(1)

    # Try live fetch first, fall back to models.dev catalog, then fallback_models
    api_key = next(
        (os.environ.get(v) for v in profile.env_vars if os.environ.get(v)), None
    )
    live = profile.fetch_models(api_key=api_key, timeout=6.0)
    if live:
        models = live
        source = "live"
    else:
        models = list_agentic_models(provider)
        source = "models.dev"
    if not models:
        models = list(profile.fallback_models)
        source = "fallback"

    console.print()
    ui.section_header(console, f"{profile.display_name or provider} Models", "▸")
    console.print(f"[dim]Source: {source}[/dim]\n")
    for m in models:
        console.print(f"  [cyan]•[/cyan] {m}")
    console.print()


@app.command()
def configure(
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Project root directory."),
    global_: bool = typer.Option(False, "--global", "-g", help="Write to ~/.config/crabkey/config.toml instead of .crabkey/config.toml."),
) -> None:
    """Interactive wizard to select a provider, set an API key, and pick a model."""
    from .configure import run_configure
    run_configure(cwd, global_config=global_)


@app.command()
def chat(
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name to resume or create."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override the model."),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Override the provider."),
    allow_all: bool = typer.Option(False, "--allow-all", help="Grant ALLOW to all tools."),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Project root directory."),
) -> None:
    """Start an interactive chat session with session and thread support."""
    asyncio.run(_chat_async(session, model, provider, allow_all, cwd))


async def _chat_async(
    session_name: str | None,
    model_override: str | None,
    provider_override: str | None,
    allow_all: bool,
    cwd: Path,
) -> None:
    from .repl import ConversationContext, Repl

    config_dir, project_config, db_path = _resolve_project(cwd)

    if provider_override:
        project_config.provider = provider_override
    if model_override:
        project_config.model = model_override

    provider = _make_provider(project_config)

    # Pre-flight: warn immediately if the API key is missing rather than
    # letting the first message fail with a cryptic 401.
    missing = provider.missing_key()
    if missing:
        ui.warning_message(
            console,
            f"{missing} is not set. Run [bold]crabkey configure[/bold] or set [bold]{missing}=your-key[/bold]"
        )

    db = Db(db_path)
    await db.initialize()

    session_mgr = SessionManager(db)
    thread_mgr = ThreadManager(db)

    # Resume or create a session
    if session_name:
        try:
            await session_mgr.switch(session_name)
            console.print(f"[dim]Resumed session [cyan]{session_name}[/cyan][/dim]")
        except KeyError:
            sess = await session_mgr.new(session_name)
            console.print(f"[dim]Created session [cyan]{sess.name}[/cyan][/dim]")
    else:
        sess = await session_mgr.new()
        console.print(f"[dim]Started session [cyan]{sess.name}[/cyan]  — use /session new <name> to name it[/dim]")

    model_config = ModelConfig(
        model=project_config.model,
        max_tokens=project_config.max_tokens,
        system=(
            "You are CrabKey, an agentic coding assistant. "
            "Be concise, precise, and helpful."
        ),
    )

    # Discover custom slash commands: global, then extensions, then project
    # (later dirs override earlier ones on name collision).
    extensions = load_extensions(cwd)
    command_dirs = [_GLOBAL_COMMANDS_DIR, *extensions.command_dirs, config_dir / "commands"]
    custom_commands = load_custom_commands(command_dirs)
    if custom_commands:
        console.print(f"[dim]Loaded {len(custom_commands)} custom command(s). Type /help to see them.[/dim]")

    ctx = ConversationContext(session_mgr, thread_mgr, db)
    repl = Repl(
        ctx=ctx,
        session_mgr=session_mgr,
        thread_mgr=thread_mgr,
        provider=provider,
        model_config=model_config,
        console=console,
        custom_commands=custom_commands,
    )
    await repl.run()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
