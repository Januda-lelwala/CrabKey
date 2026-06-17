from __future__ import annotations

import asyncio
import os
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
from ..safety.permission_broker import Permission, PermissionBroker, PermissionLevel
from ..safety.sandbox import Sandbox, SandboxConfig
from ..tools import default_registry
from ..tools.shell_tool import ShellTool
from . import ui

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


@app.command()
def run(
    goal: Optional[str] = typer.Argument(None, help="Goal for the agent. If omitted, enters interactive mode."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override the model."),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Override the provider."),
    max_iter: int = typer.Option(20, "--max-iter", help="Maximum loop iterations."),
    no_plan: bool = typer.Option(False, "--no-plan", help="Skip the planning step."),
    allow_all: bool = typer.Option(False, "--allow-all", help="Grant ALLOW to all tools (dangerous)."),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Project root directory."),
) -> None:
    """Run CrabKey in agent mode toward a goal."""
    asyncio.run(_run_async(goal, model, provider, max_iter, no_plan, allow_all, cwd))


async def _run_async(
    goal: str | None,
    model_override: str | None,
    provider_override: str | None,
    max_iter: int,
    no_plan: bool,
    allow_all: bool,
    cwd: Path,
) -> None:
    config_dir, project_config, db_path = _resolve_project(cwd)

    if provider_override:
        project_config.provider = provider_override
    if model_override:
        project_config.model = model_override

    provider = _make_provider(project_config)
    db = Db(db_path)
    await db.initialize()

    context_file = config_dir / "CONTEXT.md"
    memory = MemoryManager(context_file=context_file)
    assembler = ContextAssembler(memory)
    reflector = Reflector(provider)
    planner = Planner(provider)
    thread_mgr = ThreadManager(db)

    broker = PermissionBroker()
    if allow_all:
        broker.add_rule(Permission(tool="*", level=PermissionLevel.ALLOW))
    else:
        for t in ["file.read", "file.list", "file.write", "file.edit", "shell.run", "web.fetch"]:
            broker.add_rule(Permission(tool=t, level=PermissionLevel.ALLOW))

    sandbox = Sandbox(SandboxConfig(allowed_paths=[cwd]))
    tools = default_registry()
    tools.register(ShellTool(sandbox=sandbox))

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
    )

    if goal is None:
        goal = Prompt.ask("[bold cyan]Goal[/bold cyan]")

    thread = await thread_mgr.new(name=goal[:60])

    # Display big banner and details
    ui.header_banner(console, "🦀 CrabKey", "Agentic Coding Assistant")
    provider_name = provider.profile.name if hasattr(provider, 'profile') else "Unknown"
    tools_list = ["file.read", "file.list", "file.write", "file.edit", "shell.run", "web.fetch"]
    ui.details_panel(console, model_config.model, provider_name, tools_list)

    console.print(Panel(
        f"[bold]{goal}[/bold]",
        title="[bold cyan]Goal[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))

    if not no_plan:
        console.print()
        ui.section_header(console, "Planning", "▸")
        with ui.spinner_status(console, "Generating plan…"):
            plan = await planner.plan(goal)
        if plan.steps:
            lines = "\n".join(f"[bold]{s.index}.[/bold] {s.description}" + (f" [dim][{s.tool_hint}][/dim]" if s.tool_hint else "") for s in plan.steps)
            console.print(Panel(Markdown(lines), title="[bold]Plan[/bold]", border_style="yellow", padding=(1, 2)))

    console.print()
    ui.section_header(console, "Execution", "▸")
    console.print()

    def on_event(evt: StepEvent) -> None:
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

    await loop.run(goal=goal, thread_id=thread.id, model_config=model_config, working_dir=str(cwd), on_event=on_event)

    total_in, total_out = await db.total_cost_tokens(thread.id)
    console.print(f"\n[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]")
    console.print(f"[dim]Tokens: {total_in:,} in · {total_out:,} out · thread {thread.id[:8]}[/dim]")
    console.print()


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
    thread_mgr = ThreadManager(db)
    for t in thread_mgr.list():
        console.print(f"  {t.id[:8]}  {t.name}")


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

    ctx = ConversationContext(session_mgr, thread_mgr, db)
    repl = Repl(
        ctx=ctx,
        session_mgr=session_mgr,
        thread_mgr=thread_mgr,
        provider=provider,
        model_config=model_config,
        console=console,
    )
    await repl.run()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
