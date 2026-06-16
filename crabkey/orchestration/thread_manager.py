from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ..mal.message import Message
from ..persistence.db import Db, ThreadRecord


@dataclass
class Thread:
    id: str
    name: str
    history: list[Message] = field(default_factory=list)


class ThreadManager:
    """Creates, switches between, and persists conversation threads."""

    def __init__(self, db: Db) -> None:
        self._db = db
        self._threads: dict[str, Thread] = {}
        self._active_id: str | None = None

    async def new(self, name: str | None = None) -> Thread:
        thread_id = str(uuid.uuid4())
        name = name or f"thread-{thread_id[:8]}"
        await self._db.create_thread(thread_id, name)
        thread = Thread(id=thread_id, name=name)
        self._threads[thread_id] = thread
        self._active_id = thread_id
        return thread

    async def switch(self, thread_id: str) -> Thread:
        if thread_id not in self._threads:
            record = await self._db.get_thread(thread_id)
            if record is None:
                raise KeyError(f"Thread {thread_id!r} not found.")
            rows = await self._db.get_messages(thread_id)
            from ..mal.message import Role
            history = [Message(role=Role(r.role), content=r.content) for r in rows]
            self._threads[thread_id] = Thread(id=thread_id, name=record.name, history=history)
        self._active_id = thread_id
        return self._threads[thread_id]

    @property
    def active(self) -> Thread | None:
        if self._active_id:
            return self._threads.get(self._active_id)
        return None

    def list(self) -> list[Thread]:
        return list(self._threads.values())
