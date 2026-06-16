from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ..mal.message import Message, Role
from ..persistence.db import Db, ThreadRecord


@dataclass
class Thread:
    id: str
    session_id: str
    name: str
    forked_at: int              # number of session messages when this thread was created
    history: list[Message] = field(default_factory=list)  # thread-local additions only


class ThreadManager:
    """Creates, switches between, and persists threads within a session.

    A thread forks from the session at creation time. Its effective context is:
        session.messages[:forked_at] + thread.history

    When the thread is exited the session's messages are untouched.
    """

    def __init__(self, db: Db) -> None:
        self._db = db
        self._threads: dict[str, Thread] = {}  # keyed by thread_id
        self._active_id: str | None = None

    @property
    def active(self) -> Thread | None:
        if self._active_id:
            return self._threads.get(self._active_id)
        return None

    async def new(self, session_id: str, name: str | None = None, forked_at: int = 0) -> Thread:
        thread_id = str(uuid.uuid4())
        name = name or f"thread-{thread_id[:8]}"
        await self._db.create_thread(thread_id, session_id, name, forked_at=forked_at)
        thread = Thread(id=thread_id, session_id=session_id, name=name, forked_at=forked_at)
        self._threads[thread_id] = thread
        self._active_id = thread_id
        return thread

    async def switch(self, thread_id: str) -> Thread:
        if thread_id in self._threads:
            self._active_id = thread_id
            return self._threads[thread_id]

        record = await self._db.get_thread(thread_id)
        if record is None:
            raise KeyError(f"Thread {thread_id!r} not found.")
        rows = await self._db.get_messages(thread_id)
        history = [Message(role=Role(r.role), content=r.content) for r in rows]
        thread = Thread(
            id=thread_id,
            session_id=record.session_id,
            name=record.name,
            forked_at=record.forked_at,
            history=history,
        )
        self._threads[thread_id] = thread
        self._active_id = thread_id
        return thread

    def exit_thread(self) -> None:
        """Deactivate the current thread. Back to session."""
        self._active_id = None

    def list_for_session(self, session_id: str) -> list[Thread]:
        return [t for t in self._threads.values() if t.session_id == session_id]

    async def append_message(self, role: str, content: str | None) -> None:
        """Append a message to the active thread."""
        thread = self.active
        if thread is None:
            raise RuntimeError("No active thread.")
        thread.history.append(Message(role=Role(role), content=content))
        await self._db.append_message(thread.id, "thread", role, content)
