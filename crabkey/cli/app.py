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
from ..mal.adapters.anthropic import AnthropicAdapter
from ..mal.provider import ModelConfig
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


def _make_provider(config: ProjectConfig):
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if config.provider == "anthropic":
        return AnthropicAdapter(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    if config.provider in ("openai", "openrouter"):
        from ..mal.adapters.openai import OpenAIAdapter, OpenRouterAdapter
        if config.provider == "openrouter":
            return OpenRouterAdapter(api_key=os.environ.get("OPENROUTER_API_KEY", ""))
        return OpenAIAdapter(api_key=os.environ.get("OPENAI_API_KEY", ""))
    if config.provider == "local":
        from ..mal.adapters.local import LocalAdapter
        return LocalAdapter()
    raise typer.BadParameter(f"Unknown provider: {config.provider!r}")


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
