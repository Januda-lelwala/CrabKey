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

from ..mal.message import Message, Role
from ..mal.provider import ModelConfig
from ..orchestration.session_manager import Session, SessionManager
from ..orchestration.thread_manager import Thread, ThreadManager
from ..persistence.db import Db


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
            self._console.print("[yellow]Usage: /session new|list|switch[/yellow]")
            return

        sub = args[0]

        if sub == "new":
            name = " ".join(args[1:]) or None
            session = await self._session_mgr.new(name)
            # Exit any active thread when switching sessions
            self._thread_mgr.exit_thread()
            self._console.print(
                f"[green]✓[/green] New session [bold cyan]{session.name}[/bold cyan] "
                f"[dim]({session.id[:8]})[/dim]"
            )

        elif sub == "list":
            records = await self._session_mgr.list_all()
            if not records:
                self._console.print("[dim]No sessions yet.[/dim]")
                return
            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
            table.add_column("ID", style="dim", no_wrap=True)
            table.add_column("Name", style="cyan")
            table.add_column("Updated", style="dim")
            active = self._session_mgr.active
            for r in records:
                marker = " ←" if (active and r.id == active.id) else ""
                table.add_row(
                    r.id[:8],
                    r.name + marker,
                    r.updated_at.strftime("%Y-%m-%d %H:%M"),
                )
            self._console.print(table)

        elif sub == "switch":
            if len(args) < 2:
                self._console.print("[yellow]Usage: /session switch <name|id>[/yellow]")
                return
            name_or_id = " ".join(args[1:])
            try:
                session = await self._session_mgr.switch(name_or_id)
                self._thread_mgr.exit_thread()
                self._console.print(
                    f"[green]✓[/green] Switched to session [bold cyan]{session.name}[/bold cyan]"
                )
            except KeyError:
                self._console.print(f"[red]Session {name_or_id!r} not found.[/red]")

        else:
            self._console.print(f"[yellow]Unknown session subcommand: {sub!r}[/yellow]")

    async def _cmd_thread(self, args: list[str]) -> None:
        if not args:
            self._console.print("[yellow]Usage: /thread new|list|exit[/yellow]")
            return

        sub = args[0]
        session = self._session_mgr.active

        if session is None:
            self._console.print("[red]No active session. Create one with /session new[/red]")
            return

        if sub == "new":
            name = " ".join(args[1:]) or None
            forked_at = len(session.messages)
            thread = await self._thread_mgr.new(
                session_id=session.id,
                name=name,
                forked_at=forked_at,
            )
            self._console.print(
                f"[green]✓[/green] Thread [bold yellow]{thread.name}[/bold yellow] created "
                f"[dim](forked at {forked_at} messages)[/dim]"
            )

        elif sub == "exit":
            thr = self._thread_mgr.active
            if thr is None:
                self._console.print("[dim]Not in a thread.[/dim]")
                return
            name = thr.name
            self._thread_mgr.exit_thread()
            self._console.print(
                f"[green]✓[/green] Exited thread [bold yellow]{name}[/bold yellow] "
                f"— back to session [bold cyan]{session.name}[/bold cyan]"
            )

        elif sub == "list":
            records = await self._db_list_threads(session.id)
            if not records:
                self._console.print("[dim]No threads in this session.[/dim]")
                return
            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
            table.add_column("ID", style="dim", no_wrap=True)
            table.add_column("Name", style="yellow")
            table.add_column("Fork point", style="dim")
            table.add_column("Created", style="dim")
            active_thr = self._thread_mgr.active
            for r in records:
                marker = " ←" if (active_thr and r.id == active_thr.id) else ""
                table.add_row(
                    r.id[:8],
                    r.name + marker,
                    str(r.forked_at),
                    r.created_at.strftime("%Y-%m-%d %H:%M"),
                )
            self._console.print(table)

        else:
            self._console.print(f"[yellow]Unknown thread subcommand: {sub!r}[/yellow]")

    async def _db_list_threads(self, session_id: str):
        return await self._session_mgr._db.list_threads_for_session(session_id)

    def _cmd_status(self) -> None:
        sess = self._session_mgr.active
        thr = self._thread_mgr.active
        lines: list[str] = []
        if sess:
            msg_count = len(sess.messages)
            lines.append(f"Session : [cyan bold]{sess.name}[/cyan bold] [dim]({sess.id[:8]}) — {msg_count} messages[/dim]")
        else:
            lines.append("Session : [dim]none[/dim]")

        if thr:
            lines.append(
                f"Thread  : [yellow bold]{thr.name}[/yellow bold] [dim]({thr.id[:8]}) "
                f"— forked at {thr.forked_at}, {len(thr.history)} thread messages[/dim]"
            )
        else:
            lines.append("Thread  : [dim]none[/dim]")

        self._console.print(Panel("\n".join(lines), title="Status", border_style="dim"))

    def _cmd_help(self) -> None:
        self._console.print(Panel(__doc__ or "", title="CrabKey slash commands", border_style="dim"))

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
            self._console.print(f"[yellow]Unknown command: /{cmd}  — try /help[/yellow]")

        return True

    # ── LLM turn ─────────────────────────────────────────────────────────────

    async def _llm_turn(self, user_input: str) -> None:
        await self._ctx.append_user(user_input)

        messages = self._ctx.get_context_messages()
        try:
            response = await self._provider.complete(messages, self._model_config)
        except Exception as exc:
            self._console.print(f"[red]Provider error: {exc}[/red]")
            return

        reply = response.message.content or ""
        await self._ctx.append_assistant(reply)

        self._console.print()
        self._console.print(Markdown(reply))
        self._console.print()

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        self._console.print(
            Panel(
                "[dim]Type a message to chat. Use [bold]/help[/bold] for slash commands.[/dim]",
                border_style="cyan",
                title="CrabKey",
            )
        )

        while self._running:
            label = self._ctx.prompt_label()
            try:
                # Rich doesn't have async prompt; use input() with a formatted prefix
                self._console.print(f"{label} ", end="")
                user_input = await _async_input()
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
                    self._console.print(
                        "[yellow]No active session. Create one first: /session new[/yellow]"
                    )
                    continue
                await self._llm_turn(user_input)


async def _async_input() -> str:
    """Read a line from stdin without blocking the event loop."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sys.stdin.readline)
