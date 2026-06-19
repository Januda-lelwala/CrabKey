from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..persistence.vector_store import InMemoryVectorStore, VectorDocument, VectorStore
from .context_files import load_context


class MemoryKind(str, Enum):
    EPISODIC = "episodic"       # what happened in past turns/sessions
    PROCEDURAL = "procedural"   # how-to knowledge (from CONTEXT.md)
    SEMANTIC = "semantic"       # facts about the project/codebase


@dataclass
class MemoryEntry:
    id: str
    kind: MemoryKind
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryManager:
    """
    Stores and retrieves memories across three kinds.
    Episodic memories are kept in-process; procedural/semantic use the vector store.
    """

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        context_file: Path | None = None,
        global_context_file: Path | None = None,
        extra_context_files: list[Path] | None = None,
    ) -> None:
        self._vector_store = vector_store or InMemoryVectorStore()
        self._context_file = context_file
        self._global_context_file = global_context_file
        self._extra_context_files = extra_context_files or []
        self._episodic: list[MemoryEntry] = []

    async def store(self, entry: MemoryEntry, embedding: list[float] | None = None) -> None:
        if entry.kind == MemoryKind.EPISODIC:
            self._episodic.append(entry)
        else:
            doc = VectorDocument(id=entry.id, text=entry.text, metadata={"kind": entry.kind, **entry.metadata}, embedding=embedding)
            await self._vector_store.upsert([doc])

    async def search(self, query_embedding: list[float], top_k: int = 5, kinds: list[MemoryKind] | None = None) -> list[MemoryEntry]:
        docs = await self._vector_store.search(query_embedding, top_k=top_k)
        results = []
        for doc in docs:
            kind_val = doc.metadata.get("kind", MemoryKind.SEMANTIC)
            kind = MemoryKind(kind_val) if isinstance(kind_val, str) else kind_val
            if kinds and kind not in kinds:
                continue
            results.append(MemoryEntry(id=doc.id, kind=kind, text=doc.text, metadata=doc.metadata))
        return results

    def recent_episodic(self, n: int = 10) -> list[MemoryEntry]:
        return self._episodic[-n:]

    def load_context_file(self) -> str | None:
        """Load the merged context document: global context first, then project,
        with @imports resolved. Returns None if no context files exist."""
        files: list[Path] = []
        if self._global_context_file:
            files.append(self._global_context_file)
        files.extend(self._extra_context_files)  # e.g. extension contexts
        if self._context_file:
            files.append(self._context_file)  # project context is most specific
        return load_context(files)

    def update_context_file(self, content: str) -> None:
        if self._context_file:
            self._context_file.parent.mkdir(parents=True, exist_ok=True)
            self._context_file.write_text(content, encoding="utf-8")
