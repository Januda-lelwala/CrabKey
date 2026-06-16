"""Tests for MemoryManager."""

import pytest
from pathlib import Path

from crabkey.cognition.memory_manager import MemoryEntry, MemoryKind, MemoryManager
from crabkey.persistence.vector_store import InMemoryVectorStore


async def test_store_episodic_in_memory_list():
    mm = MemoryManager()
    entry = MemoryEntry(id="ep1", kind=MemoryKind.EPISODIC, text="user asked about X")
    await mm.store(entry)
    assert mm.recent_episodic() == [entry]


async def test_episodic_not_in_vector_store():
    store = InMemoryVectorStore()
    mm = MemoryManager(vector_store=store)
    entry = MemoryEntry(id="ep1", kind=MemoryKind.EPISODIC, text="something happened")
    await mm.store(entry)
    # Vector store should be empty — episodic doesn't go there
    results = await store.search([1.0], top_k=5)
    assert results == []


async def test_semantic_stored_in_vector_store():
    mm = MemoryManager()
    entry = MemoryEntry(id="sem1", kind=MemoryKind.SEMANTIC, text="project uses aiosqlite")
    await mm.store(entry, embedding=[0.5, 0.5])
    results = await mm.search([0.5, 0.5], top_k=1)
    assert len(results) == 1
    assert results[0].id == "sem1"
    assert results[0].kind == MemoryKind.SEMANTIC


async def test_procedural_stored_in_vector_store():
    mm = MemoryManager()
    entry = MemoryEntry(id="proc1", kind=MemoryKind.PROCEDURAL, text="how to run tests")
    await mm.store(entry, embedding=[1.0, 0.0])
    results = await mm.search([1.0, 0.0], top_k=1)
    assert results[0].kind == MemoryKind.PROCEDURAL


async def test_search_filters_by_kind():
    mm = MemoryManager()
    await mm.store(MemoryEntry(id="s1", kind=MemoryKind.SEMANTIC, text="fact"), embedding=[1.0, 0.0])
    await mm.store(MemoryEntry(id="p1", kind=MemoryKind.PROCEDURAL, text="howto"), embedding=[0.9, 0.0])

    results = await mm.search([1.0, 0.0], top_k=5, kinds=[MemoryKind.SEMANTIC])
    assert all(r.kind == MemoryKind.SEMANTIC for r in results)


async def test_recent_episodic_limit():
    mm = MemoryManager()
    for i in range(15):
        await mm.store(MemoryEntry(id=str(i), kind=MemoryKind.EPISODIC, text=f"event {i}"))
    recent = mm.recent_episodic(n=5)
    assert len(recent) == 5
    assert recent[-1].id == "14"  # most recent last


async def test_recent_episodic_returns_all_when_fewer_than_n():
    mm = MemoryManager()
    await mm.store(MemoryEntry(id="e1", kind=MemoryKind.EPISODIC, text="only one"))
    assert len(mm.recent_episodic(n=10)) == 1


def test_load_context_file_returns_none_when_no_file():
    mm = MemoryManager(context_file=Path("/nonexistent/CONTEXT.md"))
    assert mm.load_context_file() is None


def test_load_context_file_returns_none_when_not_set():
    mm = MemoryManager()
    assert mm.load_context_file() is None


def test_update_and_load_context_file(tmp_path):
    ctx_file = tmp_path / "CONTEXT.md"
    mm = MemoryManager(context_file=ctx_file)
    mm.update_context_file("# Project\nUse Python 3.11+")
    assert ctx_file.read_text() == "# Project\nUse Python 3.11+"
    assert mm.load_context_file() == "# Project\nUse Python 3.11+"


def test_update_context_file_creates_parent_dirs(tmp_path):
    ctx_file = tmp_path / "deep" / "nested" / "CONTEXT.md"
    mm = MemoryManager(context_file=ctx_file)
    mm.update_context_file("content")
    assert ctx_file.exists()
