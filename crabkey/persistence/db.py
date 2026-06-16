from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite


@dataclass
class SessionRecord:
    id: str
    name: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass
class ThreadRecord:
    id: str
    session_id: str
    name: str
    forked_at: int          # number of session messages when thread was created
    created_at: datetime.datetime
    updated_at: datetime.datetime
    metadata: dict[str, Any]


@dataclass
class MessageRecord:
    id: int
    owner_id: str           # session_id or thread_id
    owner_type: str         # "session" or "thread"
    role: str
    content: str | None
    tool_calls: str | None  # JSON
    created_at: datetime.datetime


@dataclass
class CostRecord:
    thread_id: str
    model: str
    input_tokens: int
    output_tokens: int
    created_at: datetime.datetime


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    name        TEXT NOT NULL,
    forked_at   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id    TEXT NOT NULL,
    owner_type  TEXT NOT NULL CHECK(owner_type IN ('session', 'thread')),
    role        TEXT NOT NULL,
    content     TEXT,
    tool_calls  TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_owner ON messages(owner_id, id);

CREATE TABLE IF NOT EXISTS cost_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id     TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Db:
    """SQLite persistence for sessions, threads, messages, and cost tracking."""

    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as conn:
            await conn.executescript(_SCHEMA)
            await conn.commit()

    # ── Sessions ──────────────────────────────────────────────────────────────

    async def create_session(self, session_id: str, name: str) -> SessionRecord:
        now = _now()
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                "INSERT INTO sessions (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, name, now, now),
            )
            await conn.commit()
        return SessionRecord(
            id=session_id, name=name,
            created_at=datetime.datetime.fromisoformat(now),
            updated_at=datetime.datetime.fromisoformat(now),
        )

    async def get_session(self, session_id: str) -> SessionRecord | None:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return SessionRecord(
            id=row["id"], name=row["name"],
            created_at=datetime.datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.datetime.fromisoformat(row["updated_at"]),
        )

    async def find_session(self, name_or_id: str) -> SessionRecord | None:
        """Look up a session by exact ID or by name (case-insensitive prefix)."""
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM sessions WHERE id = ?", (name_or_id,)) as cur:
                row = await cur.fetchone()
            if row is None:
                async with conn.execute(
                    "SELECT * FROM sessions WHERE lower(name) LIKE lower(?) ORDER BY created_at DESC LIMIT 1",
                    (name_or_id + "%",),
                ) as cur:
                    row = await cur.fetchone()
        if row is None:
            return None
        return SessionRecord(
            id=row["id"], name=row["name"],
            created_at=datetime.datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.datetime.fromisoformat(row["updated_at"]),
        )

    async def list_sessions(self) -> list[SessionRecord]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC") as cur:
                rows = await cur.fetchall()
        return [
            SessionRecord(
                id=r["id"], name=r["name"],
                created_at=datetime.datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.datetime.fromisoformat(r["updated_at"]),
            )
            for r in rows
        ]

    async def touch_session(self, session_id: str) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (_now(), session_id))
            await conn.commit()

    # ── Threads ───────────────────────────────────────────────────────────────

    async def create_thread(
        self, thread_id: str, session_id: str, name: str, forked_at: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> ThreadRecord:
        now = _now()
        meta = json.dumps(metadata or {})
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                "INSERT INTO threads (id, session_id, name, forked_at, created_at, updated_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (thread_id, session_id, name, forked_at, now, now, meta),
            )
            await conn.commit()
        return ThreadRecord(
            id=thread_id, session_id=session_id, name=name, forked_at=forked_at,
            created_at=datetime.datetime.fromisoformat(now),
            updated_at=datetime.datetime.fromisoformat(now),
            metadata=metadata or {},
        )

    async def get_thread(self, thread_id: str) -> ThreadRecord | None:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            id=row["id"], session_id=row["session_id"], name=row["name"],
            forked_at=row["forked_at"],
            created_at=datetime.datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.datetime.fromisoformat(row["updated_at"]),
            metadata=json.loads(row["metadata"]),
        )

    async def list_threads_for_session(self, session_id: str) -> list[ThreadRecord]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM threads WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            ThreadRecord(
                id=r["id"], session_id=r["session_id"], name=r["name"],
                forked_at=r["forked_at"],
                created_at=datetime.datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.datetime.fromisoformat(r["updated_at"]),
                metadata=json.loads(r["metadata"]),
            )
            for r in rows
        ]

    # ── Messages ──────────────────────────────────────────────────────────────

    async def append_message(
        self,
        owner_id: str,
        owner_type: str,     # "session" or "thread"
        role: str,
        content: str | None,
        tool_calls: list | None = None,
    ) -> MessageRecord:
        now = _now()
        tc_json = json.dumps(tool_calls) if tool_calls else None
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(
                "INSERT INTO messages (owner_id, owner_type, role, content, tool_calls, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (owner_id, owner_type, role, content, tc_json, now),
            )
            # Touch the session/thread so updated_at reflects recent activity
            if owner_type == "session":
                await conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, owner_id))
            else:
                await conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, owner_id))
            await conn.commit()
            row_id = cur.lastrowid
        return MessageRecord(
            id=row_id, owner_id=owner_id, owner_type=owner_type,
            role=role, content=content, tool_calls=tc_json,
            created_at=datetime.datetime.fromisoformat(now),
        )

    async def get_messages(self, owner_id: str) -> list[MessageRecord]:
        """Return all messages for a session or thread, oldest first."""
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM messages WHERE owner_id = ? ORDER BY id ASC", (owner_id,)
            ) as cur:
                rows = await cur.fetchall()
        return [
            MessageRecord(
                id=r["id"], owner_id=r["owner_id"], owner_type=r["owner_type"],
                role=r["role"], content=r["content"], tool_calls=r["tool_calls"],
                created_at=datetime.datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    async def count_messages(self, owner_id: str) -> int:
        async with aiosqlite.connect(self.path) as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM messages WHERE owner_id = ?", (owner_id,)
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row else 0

    # ── Cost log ──────────────────────────────────────────────────────────────

    async def log_cost(self, thread_id: str, model: str, input_tokens: int, output_tokens: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                "INSERT INTO cost_log (thread_id, model, input_tokens, output_tokens, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (thread_id, model, input_tokens, output_tokens, _now()),
            )
            await conn.commit()

    async def total_cost_tokens(self, thread_id: str) -> tuple[int, int]:
        async with aiosqlite.connect(self.path) as conn:
            async with conn.execute(
                "SELECT SUM(input_tokens), SUM(output_tokens) FROM cost_log WHERE thread_id = ?",
                (thread_id,),
            ) as cur:
                row = await cur.fetchone()
        return (row[0] or 0, row[1] or 0)
