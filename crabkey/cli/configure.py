"""Interactive configuration wizard for CrabKey.

Walk the user through:
  1. Select a provider
  2. Set / verify the API key (env var)
  3. Select a model
  4. Set max_tokens
  5. Write .crabkey/config.toml
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..mal.provider_registry import list_providers
from ..persistence.config import ProjectConfig


console = Console()


# ── Low-level prompt helpers ─────────────────────────────────────────────────


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    """Prompt the user for a single value. Returns default on empty input."""
    default_hint = f" [dim](leave blank to keep: {default[:6]}{'…' if len(default) > 6 else ''})[/dim]" if default and not secret else (f" [dim](default: {default})[/dim]" if default else "")
    console.print(f"  {label}{default_hint}: ", end="")

    if secret:
        try:
            val = getpass.getpass(prompt="")
        except (EOFError, KeyboardInterrupt):
            return default
    else:
        try:
            val = input()
        except (EOFError, KeyboardInterrupt):
            return default

    return val.strip() or default


def _choose(items: list[tuple[str, str]], label: str, default: int = 1) -> int:
    """Display a numbered list and return the 1-based index chosen."""
    for i, (name, hint) in enumerate(items, 1):
        marker = "[bold cyan]>[/bold cyan]" if i == default else " "
        console.print(f"  {marker} [bold]{i:>2}.[/bold]  {name}  [dim]{hint}[/dim]")

    while True:
        console.print(f"\n  Enter number or name [dim](default {default})[/dim]: ", end="")
        try:
            raw = input().strip()
        except (EOFError, KeyboardInterrupt):
            return default

        if not raw:
            return default

        # Accept a number
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(items):
                return n
            console.print(f"  [yellow]Please enter 1–{len(items)}[/yellow]")
            continue

        # Accept a name prefix
        lower = raw.lower()
        matches = [i for i, (name, _) in enumerate(items, 1) if name.lower().startswith(lower)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            console.print(f"  [yellow]Ambiguous: matches {', '.join(str(m) for m in matches)}[/yellow]")
        else:
            console.print(f"  [yellow]No match for {raw!r}[/yellow]")


# ── Step 1: provider selection ───────────────────────────────────────────────


def _select_provider(current: str) -> str:
    console.print("\n[bold]Step 1 — Select a provider[/bold]\n")

    profiles = sorted(list_providers(), key=lambda p: p.name)
    items: list[tuple[str, str]] = []
    default_idx = 1

    for i, p in enumerate(profiles, 1):
        key_set = any(os.environ.get(v) for v in p.env_vars)
        status = "[green]key set ✓[/green]" if key_set else "[dim]no key[/dim]"
        hint = f"{p.display_name or p.name}  {status}"
        items.append((p.name, hint))
        if p.name == current:
            default_idx = i

    idx = _choose(items, "provider", default=default_idx)
    return profiles[idx - 1].name


# ── Step 2: API key ───────────────────────────────────────────────────────────


_CRABKEY_ENV_FILE = Path.home() / ".config" / "crabkey" / "env"


def _configure_api_key(provider_name: str) -> None:
    from ..mal.provider_registry import get_provider_profile

    profile = get_provider_profile(provider_name)
    if profile is None:
        return

    # Find the primary API key variable (ignore URL-style vars)
    primary_var = next(
        (v for v in profile.env_vars if "API_KEY" in v.upper() or "TOKEN" in v.upper()),
        None,
    )
    if not primary_var:
        return  # provider doesn't need an API key (e.g. local)

    console.print(f"\n[bold]Step 2 — API key for [cyan]{provider_name}[/cyan][/bold]\n")

    current_val = os.environ.get(primary_var, "")

    if current_val:
        console.print(f"  [green]✓[/green]  {primary_var} is already set in your environment.")
        change = _prompt("Change it? (y/N)", default="n").lower()
        if change != "y":
            return

    console.print(f"  Enter your API key:")
    new_key = _prompt(f"  {primary_var}", secret=False)

    if not new_key:
        console.print("  [dim]Skipped — key unchanged.[/dim]")
        return

    # 1. Save to ~/.config/crabkey/env so all crabkey commands load it immediately
    _write_to_crabkey_env(primary_var, new_key)
    # 2. Also write to shell rc for non-crabkey tools / new shells
    _write_env_var_to_shell(primary_var, new_key)
    # 3. Set in the current process so the rest of this wizard sees it
    os.environ[primary_var] = new_key
    console.print(f"  [green]✓[/green]  {primary_var} saved.")


def _write_to_crabkey_env(var: str, value: str) -> None:
    """Upsert VAR=value in ~/.config/crabkey/env (loaded automatically by all crabkey commands)."""
    _CRABKEY_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = _CRABKEY_ENV_FILE.read_text(encoding="utf-8") if _CRABKEY_ENV_FILE.exists() else ""
    new_lines = []
    replaced = False
    for line in existing.splitlines():
        if line.startswith(f"{var}=") or line.startswith(f"{var} ="):
            new_lines.append(f'{var}="{value}"')
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f'{var}="{value}"')
    _CRABKEY_ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    console.print(f"  [dim]Saved to {_CRABKEY_ENV_FILE}[/dim]")


def _write_env_var_to_shell(var: str, value: str) -> None:
    """Also export to shell rc so other tools (non-crabkey) see the key in new shells."""
    shell = os.environ.get("SHELL", "")
    if "fish" in shell:
        console.print(f"  [dim]Fish shell: run [bold]set -Ux {var} '…'[/bold] to persist for other tools.[/dim]")
        return

    rc = Path.home() / ".zshenv" if "zsh" in shell else Path.home() / ".bashrc"
    existing = rc.read_text(encoding="utf-8") if rc.exists() else ""

    if f"export {var}=" in existing:
        new_lines = [
            f'export {var}="{value}"' if line.startswith(f"export {var}=") else line
            for line in existing.splitlines()
        ]
        rc.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    else:
        with rc.open("a", encoding="utf-8") as f:
            f.write(f'\nexport {var}="{value}"\n')

    console.print(f"  [dim]Also written to {rc} for new shell sessions.[/dim]")


# ── Step 3: model selection ───────────────────────────────────────────────────


def _select_model(provider_name: str, current_model: str) -> str:
    from ..mal.provider_registry import get_provider_profile
    from ..mal.model_catalog import list_agentic_models

    console.print(f"\n[bold]Step 3 — Select a model[/bold]\n")

    profile = get_provider_profile(provider_name)
    models: list[str] = []
    source = "unknown"

    if profile:
        api_key = next((os.environ.get(v) for v in profile.env_vars if os.environ.get(v)), None)
        with console.status("[dim]Fetching model list…[/dim]", spinner="dots"):
            live = profile.fetch_models(api_key=api_key, timeout=6.0)
        if live:
            models = live
            source = "live"

    if not models:
        models = list_agentic_models(provider_name)
        source = "models.dev"

    if not models and profile:
        models = list(profile.fallback_models)
        source = "fallback"

    if not models:
        console.print("  [dim]No models found. Enter a model name manually:[/dim]")
        return _prompt("  Model", default=current_model)

    console.print(f"  [dim]Source: {source} — {len(models)} models[/dim]\n")

    # Show up to 20 models; if more, let user also type a name
    display = models[:20]
    items = [(m, "") for m in display]
    if len(models) > 20:
        items.append(("(type a model name not listed above)", ""))

    default_idx = next((i for i, m in enumerate(display, 1) if m == current_model), 1)
    idx = _choose(items, "model", default=default_idx)

    if idx > len(display):
        return _prompt("  Model name", default=current_model)

    return display[idx - 1]


# ── Step 4: max_tokens ────────────────────────────────────────────────────────


def _select_max_tokens(current: int) -> int:
    console.print(f"\n[bold]Step 4 — Max tokens[/bold]\n")
    console.print("  Controls how long the model's responses can be.")
    raw = _prompt("  max_tokens", default=str(current))
    try:
        val = int(raw)
        if val < 256:
            console.print("  [yellow]Too low — using 256.[/yellow]")
            return 256
        return val
    except ValueError:
        console.print("  [yellow]Invalid number — keeping current value.[/yellow]")
        return current


# ── Main wizard ───────────────────────────────────────────────────────────────


def run_configure(cwd: Path, global_config: bool = False) -> None:
    """Run the full interactive configuration wizard."""
    if global_config:
        config_path = Path.home() / ".config" / "crabkey" / "config.toml"
        scope_label = "global (~/.config/crabkey/config.toml)"
    else:
        config_path = cwd / ".crabkey" / "config.toml"
        scope_label = f"project ({config_path})"

    console.print(Panel(
        f"[bold]CrabKey configuration wizard[/bold]\n"
        f"[dim]Writing to {scope_label}[/dim]",
        border_style="cyan",
    ))

    # Load existing config as starting point
    existing = ProjectConfig.load(config_path)

    provider = _select_provider(existing.provider)
    _configure_api_key(provider)
    model = _select_model(provider, existing.model)
    max_tokens = _select_max_tokens(existing.max_tokens)

    # Summary
    console.print("\n")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("provider", provider)
    table.add_row("model", model)
    table.add_row("max_tokens", str(max_tokens))
    console.print(Panel(table, title="Summary", border_style="green"))

    confirm = _prompt("\n  Write config? (Y/n)", default="y").lower()
    if confirm in ("n", "no"):
        console.print("[dim]Aborted — no changes written.[/dim]")
        return

    new_config = ProjectConfig(provider=provider, model=model, max_tokens=max_tokens)
    new_config.save(config_path)
    console.print(f"\n[green]✓[/green]  Config saved to [bold]{config_path}[/bold]")
    console.print(f"\n  [dim]Run [bold]crabkey chat[/bold] to start a session.[/dim]\n")
