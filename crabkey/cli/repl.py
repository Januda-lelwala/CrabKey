"""Interactive REPL for CrabKey with session and thread management.

Slash commands:
    /session new [name]        Create a new session
    /session list              List all sessions
    /session switch <name|id>  Switch to an existing session

    /thread new [name]         Fork a thread from the current session
    /thread list               List threads in the current session
    /thread exit               Exit current thread, back to session

    /status                    Show current session and thread
    /clear                     Clear the screen
    /help                      Print this help
    /quit  /q                  Exit the REPL
"""

from __future__ import annotations

import sys
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

from ..mal.message import Message, Role
from ..mal.provider import ModelConfig
from ..orchestration.session_manager import Session, SessionManager
from ..orchestration.thread_manager import Thread, ThreadManager
from ..persistence.db import Db
from . import ui


class ConversationContext:
    """Tracks the active session + optional active thread and builds LLM context."""

    def __init__(self, session_mgr: SessionManager, thread_mgr: ThreadManager, db: Db) -> None:
        self._session_mgr = session_mgr
        self._thread_mgr = thread_mgr
        self._db = db

    @property
    def session(self) -> Session | None:
        return self._session_mgr.active

    @property
    def thread(self) -> Thread | None:
        return self._thread_mgr.active

    @property
    def in_thread(self) -> bool:
        return self._thread_mgr.active is not None

    def prompt_label(self) -> str:
        """Rich-formatted label shown before the user input prompt."""
        sess = self.session
        thr = self.thread
        parts: list[str] = []
        if sess:
            parts.append(f"[cyan]session:[bold]{sess.name}[/bold][/cyan]")
        if thr:
            parts.append(f"[yellow]thread:[bold]{thr.name}[/bold][/yellow]")
        label = " ".join(parts) if parts else "[dim]no session[/dim]"
        return f"[{label}]"

    def get_context_messages(self) -> list[Message]:
        """Build the full message list to send to the LLM.

        In a thread: session messages up to the fork point + thread-local messages.
        In a session: all session messages.
        """
        sess = self.session
        thr = self.thread

        if sess is None:
            return []

        if thr is not None:
            session_slice = sess.messages[: thr.forked_at]
            return session_slice + thr.history

        return list(sess.messages)

    async def append_user(self, content: str) -> None:
        if self.in_thread:
            await self._thread_mgr.append_message("user", content)
        else:
            await self._session_mgr.append_message("user", content)

    async def append_assistant(self, content: str) -> None:
        if self.in_thread:
            await self._thread_mgr.append_message("assistant", content)
        else:
            await self._session_mgr.append_message("assistant", content)


class Repl:
    """Interactive read-eval-print loop for CrabKey chat."""

    def __init__(
        self,
        ctx: ConversationContext,
        session_mgr: SessionManager,
        thread_mgr: ThreadManager,
        provider: Any,
        model_config: ModelConfig,
        console: Console,
    ) -> None:
        self._ctx = ctx
        self._session_mgr = session_mgr
        self._thread_mgr = thread_mgr
        self._provider = provider
        self._model_config = model_config
        self._console = console
        self._running = False

    # ── Slash commands ────────────────────────────────────────────────────────

    async def _cmd_session(self, args: list[str]) -> None:
        if not args:
            ui.warning_message(self._console, "Usage: /session new|list|switch")
            return

        sub = args[0]

        if sub == "new":
            name = " ".join(args[1:]) or None
            session = await self._session_mgr.new(name)
            self._thread_mgr.exit_thread()
            ui.success_message(
                self._console,
                f"New session [bold cyan]{session.name}[/bold cyan] [dim]({session.id[:8]})[/dim]"
            )

        elif sub == "list":
            records = await self._session_mgr.list_all()
            if not records:
                self._console.print("[dim]No sessions yet.[/dim]")
                return
            table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
            table.add_column("ID", style="dim", no_wrap=True)
            table.add_column("Name", style="cyan")
            table.add_column("Updated", style="dim")
            active = self._session_mgr.active
            for r in records:
                marker = " [cyan]←[/cyan]" if (active and r.id == active.id) else ""
                table.add_row(
                    r.id[:8],
                    r.name + marker,
                    r.updated_at.strftime("%Y-%m-%d %H:%M"),
                )
            self._console.print(Panel(table, title="[bold]Sessions[/bold]", border_style="cyan", padding=(0, 1)))

        elif sub == "switch":
            if len(args) < 2:
                ui.warning_message(self._console, "Usage: /session switch <name|id>")
                return
            name_or_id = " ".join(args[1:])
            try:
                session = await self._session_mgr.switch(name_or_id)
                self._thread_mgr.exit_thread()
                ui.success_message(
                    self._console,
                    f"Switched to session [bold cyan]{session.name}[/bold cyan]"
                )
            except KeyError:
                ui.error_message(self._console, f"Session {name_or_id!r} not found")

        else:
            ui.warning_message(self._console, f"Unknown session subcommand: {sub!r}")

    async def _cmd_thread(self, args: list[str]) -> None:
        if not args:
            ui.warning_message(self._console, "Usage: /thread new|list|exit")
            return

        sub = args[0]
        session = self._session_mgr.active

        if session is None:
            ui.error_message(self._console, "No active session. Create one with /session new")
            return

        if sub == "new":
            name = " ".join(args[1:]) or None
            forked_at = len(session.messages)
            thread = await self._thread_mgr.new(
                session_id=session.id,
                name=name,
                forked_at=forked_at,
            )
            ui.success_message(
                self._console,
                f"Thread [bold yellow]{thread.name}[/bold yellow] created [dim](forked at {forked_at} messages)[/dim]"
            )

        elif sub == "exit":
            thr = self._thread_mgr.active
            if thr is None:
                self._console.print("[dim]Not in a thread.[/dim]")
                return
            name = thr.name
            self._thread_mgr.exit_thread()
            ui.success_message(
                self._console,
                f"Exited thread [bold yellow]{name}[/bold yellow] — back to session [bold cyan]{session.name}[/bold cyan]"
            )

        elif sub == "list":
            records = await self._db_list_threads(session.id)
            if not records:
                self._console.print("[dim]No threads in this session.[/dim]")
                return
            table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
            table.add_column("ID", style="dim", no_wrap=True)
            table.add_column("Name", style="yellow")
            table.add_column("Fork point", style="dim")
            table.add_column("Created", style="dim")
            active_thr = self._thread_mgr.active
            for r in records:
                marker = " [yellow]←[/yellow]" if (active_thr and r.id == active_thr.id) else ""
                table.add_row(
                    r.id[:8],
                    r.name + marker,
                    str(r.forked_at),
                    r.created_at.strftime("%Y-%m-%d %H:%M"),
                )
            self._console.print(Panel(table, title="[bold]Threads[/bold]", border_style="yellow", padding=(0, 1)))

        else:
            ui.warning_message(self._console, f"Unknown thread subcommand: {sub!r}")

    async def _db_list_threads(self, session_id: str):
        return await self._session_mgr._db.list_threads_for_session(session_id)

    def _cmd_status(self) -> None:
        sess = self._session_mgr.active
        thr = self._thread_mgr.active
        rows: list[dict] = []

        if sess:
            msg_count = len(sess.messages)
            rows.append({
                "label": "Session",
                "value": f"[cyan bold]{sess.name}[/cyan bold] [dim]({sess.id[:8]}) — {msg_count} messages[/dim]"
            })
        else:
            rows.append({"label": "Session", "value": "[dim]none[/dim]"})

        if thr:
            rows.append({
                "label": "Thread",
                "value": f"[yellow bold]{thr.name}[/yellow bold] [dim]({thr.id[:8]}) — forked at {thr.forked_at}, {len(thr.history)} thread messages[/dim]"
            })
        else:
            rows.append({"label": "Thread", "value": "[dim]none[/dim]"})

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="dim")
        table.add_column(style="bold")
        for row in rows:
            table.add_row(row["label"], row["value"])

        self._console.print(Panel(table, title="[bold]Status[/bold]", border_style="dim", padding=(1, 2)))

    def _cmd_help(self) -> None:
        self._console.print(Panel(__doc__ or "", title="[bold]CrabKey Commands[/bold]", border_style="dim", padding=(1, 2)))

    # ── Error formatting ──────────────────────────────────────────────────────

    def _format_provider_error(self, exc: Exception) -> str:
        msg = str(exc)
        profile = self._provider.profile
        missing = self._provider.missing_key()

        # Auth / key errors
        is_auth = (
            "401" in msg
            or "403" in msg
            or "authentication" in msg.lower()
            or "api key" in msg.lower()
            or "missing authentication" in msg.lower()
            or "invalid x-api-key" in msg.lower()
            or isinstance(exc, RuntimeError) and "API key" in msg
        )
        if is_auth:
            var = missing or next(
                (v for v in profile.env_vars if "API_KEY" in v.upper() or "TOKEN" in v.upper()), None
            )
            hint = (
                f"\n  Set [bold]{var}[/bold] or run [bold]crabkey configure[/bold]."
                if var else "\n  Run [bold]crabkey configure[/bold] to set up authentication."
            )
            return f"[red]Authentication failed[/red] for provider [cyan]{profile.name}[/cyan].{hint}"

        # Model not found
        if "404" in msg or "model" in msg.lower() and "not found" in msg.lower():
            return (
                f"[red]Model not found:[/red] [bold]{self._model_config.model}[/bold]\n"
                f"  Run [bold]crabkey models {profile.name}[/bold] to see available models."
            )

        # Rate limit
        if "429" in msg or "rate limit" in msg.lower():
            return f"[yellow]Rate limited[/yellow] by [cyan]{profile.name}[/cyan]. Wait a moment and retry."

        # Generic fallback
        return f"[red]Provider error ({profile.name}):[/red] {msg}"

    # ── Command dispatch ──────────────────────────────────────────────────────

    async def _handle_slash(self, line: str) -> bool:
        """Parse and dispatch a slash command. Returns True to continue the loop."""
        parts = line[1:].split()  # strip leading /
        if not parts:
            return True
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "session":
            await self._cmd_session(args)
        elif cmd == "thread":
            await self._cmd_thread(args)
        elif cmd == "status":
            self._cmd_status()
        elif cmd == "help":
            self._cmd_help()
        elif cmd == "clear":
            self._console.clear()
        elif cmd in ("quit", "q", "exit"):
            return False
        else:
            ui.warning_message(self._console, f"Unknown command: /{cmd}  — try /help")

        return True

    # ── LLM turn ─────────────────────────────────────────────────────────────

    async def _llm_turn(self, user_input: str) -> None:
        await self._ctx.append_user(user_input)

        messages = self._ctx.get_context_messages()
        try:
            response = await self._provider.complete(messages, self._model_config)
        except Exception as exc:
            self._console.print(self._format_provider_error(exc))
            return

        reply = response.message.content or ""
        await self._ctx.append_assistant(reply)

        # Print response below the input box
        self._console.print()
        self._console.print(Markdown(reply))
        self._console.print()

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True

        # Display big banner
        ui.header_banner(self._console, "🦀 CrabKey", "AI-Powered Coding Assistant")

        # Display session details
        model = self._model_config.model
        provider_name = self._provider.profile.name if hasattr(self._provider, 'profile') else "Unknown"
        tools_list = ["file.read", "file.write", "file.edit", "shell.run", "web.fetch"]
        ui.details_panel(self._console, model, provider_name, tools_list)

        self._console.print("[dim]Type a message to chat. Use [bold]/help[/bold] for slash commands. [bold]/quit[/bold] to exit.[/dim]")
        self._console.print()

        # Setup prompt_toolkit session for better input handling
        if HAS_PROMPT_TOOLKIT:
            prompt_session = PromptSession()

        while self._running:
            try:
                # Display input box top
                ui.boxed_input_top(self._console)

                # Get input using prompt_toolkit (better terminal handling)
                if HAS_PROMPT_TOOLKIT:
                    user_input = await prompt_session.prompt_async(
                        "You: ",
                        mouse_support=False,
                    )
                else:
                    # Fallback to basic input
                    print("\033[1;36mYou:\033[0m ", end="", flush=True)
                    user_input = sys.stdin.readline().rstrip('\n')

                # Display input box bottom
                ui.boxed_input_bottom(self._console)
            except (EOFError, KeyboardInterrupt):
                self._console.print("\n[dim]Bye.[/dim]")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                should_continue = await self._handle_slash(user_input)
                if not should_continue:
                    self._console.print("[dim]Bye.[/dim]")
                    break
            else:
                if self._session_mgr.active is None:
                    ui.error_message(
                        self._console,
                        "No active session. Create one first: /session new"
                    )
                    continue
                await self._llm_turn(user_input)


async def _async_input() -> str:
    """Read a line from stdin without blocking the event loop."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sys.stdin.readline)
