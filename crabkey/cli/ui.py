"""Rich UI components and styling for CrabKey TUI.

Provides consistent, polished styling matching Claude Code's interface.
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich.table import Table
from rich.style import Style
from rich.box import Box


def header_banner(console: Console, title: str = "CrabKey", subtitle: str = "") -> None:
    """Display a massive header banner like Claude Code."""
    console.print()
    # Big bold text for CrabKey
    console.print(f"[bold cyan]{title}[/bold cyan]", style="bold", highlight=False)
    if subtitle:
        console.print(f"[dim]{subtitle}[/dim]")
    console.print()


def details_panel(console: Console, model: str, provider: str, tools: list[str]) -> None:
    """Display session details panel with model, provider, and tools."""
    console.print()
    table = Table(show_header=False, box=None, padding=(0, 2), show_edge=False)
    table.add_column(style="dim", width=20)
    table.add_column(style="cyan")

    table.add_row("[bold]Model[/bold]", model)
    table.add_row("[bold]Provider[/bold]", provider)
    table.add_row("[bold]Tools[/bold]", ", ".join(tools) if tools else "[dim]none[/dim]")

    console.print(Panel(table, border_style="cyan", padding=(1, 2), title="[bold cyan]Session Details[/bold cyan]"))
    console.print()


def section_header(console: Console, title: str, icon: str = "▸") -> None:
    """Display a section header with consistent styling."""
    console.print(f"[bold cyan]{icon}[/bold cyan] [bold]{title}[/bold]")


def boxed_input_top(console: Console) -> None:
    """Display the top line of input box."""
    console.print("[cyan]┌─────────────────────────────────────────────────────────────┐[/cyan]")


def boxed_input_bottom(console: Console) -> None:
    """Display the bottom line of input box."""
    # Use plain print to ensure it appears after stdin.readline()
    print("\033[36m└─────────────────────────────────────────────────────────────┘\033[0m", flush=True)


def display_below_input(console: Console, content: str) -> None:
    """Display content below the input box (for assistant messages, etc)."""
    console.print()
    console.print(content)
    console.print()


def info_panel(console: Console, content: str, title: str = "", border_style: str = "cyan") -> None:
    """Display an info panel with consistent styling."""
    console.print(Panel(
        content,
        title=f"[bold]{title}[/bold]" if title else None,
        border_style=border_style,
        padding=(1, 2),
        expand=False,
    ))


def success_message(console: Console, message: str) -> None:
    """Display a success message."""
    console.print(f"[green]✓[/green] {message}")


def error_message(console: Console, message: str) -> None:
    """Display an error message."""
    console.print(f"[red]✗[/red] {message}")


def warning_message(console: Console, message: str) -> None:
    """Display a warning message."""
    console.print(f"[yellow]⚠[/yellow] {message}")


def input_prompt(console: Console, label: str, default: str = "") -> str:
    """Display an input prompt with consistent styling."""
    default_hint = f" [dim]({default})[/dim]" if default else ""
    console.print(f"[cyan]▸[/cyan] {label}{default_hint}: ", end="", highlight=False)
    return input()


def create_two_column_table(
    headers: tuple[str, str],
    rows: list[tuple[str, str]],
    header_style: str = "bold cyan",
) -> Table:
    """Create a two-column table with consistent styling."""
    table = Table(show_header=True, header_style=header_style, box=None, padding=(0, 2))
    table.add_column(headers[0], style="dim", no_wrap=False)
    table.add_column(headers[1], style="bold")
    for key, value in rows:
        table.add_row(key, value)
    return table


def create_status_table(
    rows: list[dict],
    title: str = "Status",
    border_style: str = "cyan",
) -> Panel:
    """Create a status info table with consistent styling."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold cyan")

    for row in rows:
        label = row.get("label", "")
        value = row.get("value", "")
        table.add_row(label, value)

    return Panel(table, title=f"[bold]{title}[/bold]", border_style=border_style, padding=(1, 2))


def format_code_snippet(code: str, max_length: int = 100) -> str:
    """Format a code snippet for display."""
    if len(code) > max_length:
        return f"[dim]{code[:max_length]}...[/dim]"
    return f"[dim]{code}[/dim]"


def spinner_status(console: Console, message: str) -> object:
    """Return a status context manager with spinner."""
    return console.status(f"[dim]{message}[/dim]", spinner="dots")


def list_items(console: Console, items: list[str], title: str = "", bullet: str = "•") -> None:
    """Display a formatted list of items."""
    if title:
        section_header(console, title)
    for item in items:
        console.print(f"  [cyan]{bullet}[/cyan] {item}")
