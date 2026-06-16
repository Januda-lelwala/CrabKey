from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ..mal.message import Message, Role
from ..persistence.db import Db, SessionRecord


@dataclass
class Session:
    id: str
    name: str
    messages: list[Message] = field(default_factory=list)


class SessionManager:
    """Creates, switches between, and persists top-level sessions."""

    def __init__(self, db: Db) -> None:
        self._db = db
        self._sessions: dict[str, Session] = {}
        self._active_id: str | None = None

    @property
    def active(self) -> Session | None:
        if self._active_id:
            return self._sessions.get(self._active_id)
        return None

    async def new(self, name: str | None = None) -> Session:
        session_id = str(uuid.uuid4())
        name = name or f"session-{session_id[:8]}"
        await self._db.create_session(session_id, name)
        session = Session(id=session_id, name=name)
        self._sessions[session_id] = session
        self._active_id = session_id
        return session

    async def switch(self, name_or_id: str) -> Session:
        """Switch to an existing session by name or ID prefix."""
        # Check already-loaded sessions first
        for sid, sess in self._sessions.items():
            if sid == name_or_id or sess.name == name_or_id or sid.startswith(name_or_id):
                self._active_id = sid
                return sess

        record = await self._db.find_session(name_or_id)
        if record is None:
            raise KeyError(f"Session {name_or_id!r} not found.")

        rows = await self._db.get_messages(record.id)
        messages = [Message(role=Role(r.role), content=r.content) for r in rows]
        session = Session(id=record.id, name=record.name, messages=messages)
        self._sessions[record.id] = session
        self._active_id = record.id
        return session

    async def list_all(self) -> list[SessionRecord]:
        return await self._db.list_sessions()

    async def append_message(self, role: str, content: str | None) -> None:
        """Append a message to the active session (both in-memory and DB)."""
        session = self.active
        if session is None:
            raise RuntimeError("No active session.")
        session.messages.append(Message(role=Role(role), content=content))
        await self._db.append_message(session.id, "session", role, content)
