from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite


@dataclass
class ThreadRecord:
    id: str
    name: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    metadata: dict[str, Any]


@dataclass
class MessageRecord:
    id: int
    thread_id: str
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
CREATE TABLE IF NOT EXISTS threads (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id   TEXT NOT NULL REFERENCES threads(id),
    role        TEXT NOT NULL,
    content     TEXT,
    tool_calls  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id     TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
"""


class Db:
    """SQLite persistence for threads, messages, and cost tracking."""

    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as conn:
            await conn.executescript(_SCHEMA)
            await conn.commit()

    async def create_thread(self, thread_id: str, name: str, metadata: dict[str, Any] | None = None) -> ThreadRecord:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        meta = json.dumps(metadata or {})
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                "INSERT INTO threads (id, name, created_at, updated_at, metadata) VALUES (?, ?, ?, ?, ?)",
                (thread_id, name, now, now, meta),
            )
            await conn.commit()
        return ThreadRecord(id=thread_id, name=name, created_at=datetime.datetime.fromisoformat(now),
                            updated_at=datetime.datetime.fromisoformat(now), metadata=metadata or {})

    async def get_thread(self, thread_id: str) -> ThreadRecord | None:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return ThreadRecord(
            id=row["id"], name=row["name"],
            created_at=datetime.datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.datetime.fromisoformat(row["updated_at"]),
            metadata=json.loads(row["metadata"]),
        )

    async def append_message(self, thread_id: str, role: str, content: str | None, tool_calls: list | None = None) -> MessageRecord:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        tc_json = json.dumps(tool_calls) if tool_calls else None
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(
                "INSERT INTO messages (thread_id, role, content, tool_calls, created_at) VALUES (?, ?, ?, ?, ?)",
                (thread_id, role, content, tc_json, now),
            )
            await conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))
            await conn.commit()
            row_id = cur.lastrowid
        return MessageRecord(id=row_id, thread_id=thread_id, role=role, content=content,
                             tool_calls=tc_json, created_at=datetime.datetime.fromisoformat(now))

    async def get_messages(self, thread_id: str) -> list[MessageRecord]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM messages WHERE thread_id = ? ORDER BY id ASC", (thread_id,)
            ) as cur:
                rows = await cur.fetchall()
        return [
            MessageRecord(id=r["id"], thread_id=r["thread_id"], role=r["role"],
                          content=r["content"], tool_calls=r["tool_calls"],
                          created_at=datetime.datetime.fromisoformat(r["created_at"]))
            for r in rows
        ]

    async def log_cost(self, thread_id: str, model: str, input_tokens: int, output_tokens: int) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                "INSERT INTO cost_log (thread_id, model, input_tokens, output_tokens, created_at) VALUES (?, ?, ?, ?, ?)",
                (thread_id, model, input_tokens, output_tokens, now),
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
