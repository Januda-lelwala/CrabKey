from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VectorDocument:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None


class VectorStore(ABC):
    @abstractmethod
    async def upsert(self, docs: list[VectorDocument]) -> None: ...

    @abstractmethod
    async def search(self, query_embedding: list[float], top_k: int = 5) -> list[VectorDocument]: ...

    @abstractmethod
    async def delete(self, ids: list[str]) -> None: ...


class InMemoryVectorStore(VectorStore):
    """Simple cosine-similarity in-memory store — swap for Qdrant/Chroma in production."""

    def __init__(self) -> None:
        self._docs: dict[str, VectorDocument] = {}

    async def upsert(self, docs: list[VectorDocument]) -> None:
        for doc in docs:
            self._docs[doc.id] = doc

    async def search(self, query_embedding: list[float], top_k: int = 5) -> list[VectorDocument]:
        import math

        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            if na == 0 or nb == 0:
                return 0.0
            return dot / (na * nb)

        scored = [
            (cosine(query_embedding, doc.embedding or []), doc)
            for doc in self._docs.values()
            if doc.embedding is not None
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]

    async def delete(self, ids: list[str]) -> None:
        for doc_id in ids:
            self._docs.pop(doc_id, None)
