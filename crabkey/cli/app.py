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
from ..orchestration.thread_manager import ThreadManager
from ..persistence.config import ProjectConfig
from ..persistence.db import Db
from ..safety.checkpoint import Checkpoint
from ..safety.permission_broker import Permission, PermissionBroker, PermissionLevel
from ..safety.sandbox import Sandbox, SandboxConfig
from ..tools import default_registry
from ..tools.shell_tool import ShellTool

app = typer.Typer(
    name="crabkey",
    help="Model-agnostic agentic coding CLI.",
    add_completion=False,
)
console = Console()


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
    console.print(Panel(f"[bold]Goal:[/bold] {goal}", title="CrabKey", border_style="cyan"))

    if not no_plan:
        plan = await planner.plan(goal)
        if plan.steps:
            lines = "\n".join(f"{s.index}. {s.description}" + (f" `[{s.tool_hint}]`" if s.tool_hint else "") for s in plan.steps)
            console.print(Panel(Markdown(lines), title="Plan", border_style="yellow"))

    def on_event(evt: StepEvent) -> None:
        if evt.kind == "text" and evt.data:
            console.print(Markdown(evt.data))
        elif evt.kind == "tool_call":
            console.print(f"  [dim]→ {evt.tool_name}({evt.data[:120]}...)[/dim]" if len(evt.data) > 120 else f"  [dim]→ {evt.tool_name}({evt.data})[/dim]")
        elif evt.kind == "tool_result":
            preview = evt.data[:200].replace("\n", " ")
            console.print(f"  [dim]← {preview}[/dim]")
        elif evt.kind == "done":
            console.print("[green]✓ Done[/green]")
        elif evt.kind == "error":
            console.print(f"[red]✗ {evt.data}[/red]")

    await loop.run(goal=goal, thread_id=thread.id, model_config=model_config, working_dir=str(cwd), on_event=on_event)

    total_in, total_out = await db.total_cost_tokens(thread.id)
    console.print(f"\n[dim]Tokens: {total_in:,} in / {total_out:,} out · thread {thread.id[:8]}[/dim]")


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

    table = Table(title="CrabKey Providers", show_lines=False)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Mode", style="dim")
    table.add_column("Env var(s)", style="dim")
    table.add_column("Description")

    for p in sorted(_list(), key=lambda x: x.name):
        env = ", ".join(p.env_vars[:2]) or "—"
        table.add_row(p.name, p.api_mode, env, p.description or p.display_name)

    console.print(table)


@app.command(name="models")
def list_models_cmd(
    provider: str = typer.Argument(..., help="Provider name (e.g. anthropic, openrouter)"),
) -> None:
    """List agentic models available for a provider (from models.dev catalog)."""
    from ..mal.model_catalog import list_agentic_models
    from ..mal.provider_registry import get_provider_profile

    profile = get_provider_profile(provider)
    if profile is None:
        console.print(f"[red]Unknown provider: {provider!r}. Run 'crabkey providers' to see available providers.[/red]")
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

    console.print(f"\n[bold]{profile.display_name or provider}[/bold] models ({source}):\n")
    for m in models:
        console.print(f"  {m}")
    console.print()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
