"""Tests for persistence layer — InMemoryVectorStore."""

import pytest

from crabkey.persistence.vector_store import InMemoryVectorStore, VectorDocument


async def test_upsert_and_search():
    store = InMemoryVectorStore()
    doc = VectorDocument(id="1", text="hello world", embedding=[1.0, 0.0])
    await store.upsert([doc])
    results = await store.search([1.0, 0.0], top_k=1)
    assert len(results) == 1
    assert results[0].id == "1"


async def test_search_returns_most_similar_first():
    store = InMemoryVectorStore()
    await store.upsert([
        VectorDocument(id="close", text="close", embedding=[1.0, 0.0]),
        VectorDocument(id="far", text="far", embedding=[0.0, 1.0]),
    ])
    results = await store.search([1.0, 0.01], top_k=2)
    assert results[0].id == "close"
    assert results[1].id == "far"


async def test_upsert_overwrites_by_id():
    store = InMemoryVectorStore()
    await store.upsert([VectorDocument(id="1", text="original", embedding=[1.0, 0.0])])
    await store.upsert([VectorDocument(id="1", text="updated", embedding=[1.0, 0.0])])
    results = await store.search([1.0, 0.0], top_k=1)
    assert results[0].text == "updated"


async def test_search_top_k_limit():
    store = InMemoryVectorStore()
    await store.upsert([
        VectorDocument(id=str(i), text=f"doc {i}", embedding=[float(i), 0.0])
        for i in range(1, 6)
    ])
    results = await store.search([5.0, 0.0], top_k=2)
    assert len(results) == 2


async def test_delete_removes_document():
    store = InMemoryVectorStore()
    await store.upsert([VectorDocument(id="1", text="to delete", embedding=[1.0, 0.0])])
    await store.delete(["1"])
    results = await store.search([1.0, 0.0], top_k=5)
    assert all(r.id != "1" for r in results)


async def test_delete_nonexistent_is_noop():
    store = InMemoryVectorStore()
    await store.delete(["ghost"])  # should not raise


async def test_search_skips_docs_without_embeddings():
    store = InMemoryVectorStore()
    await store.upsert([
        VectorDocument(id="no-embed", text="no embedding"),   # embedding=None
        VectorDocument(id="has-embed", text="has embedding", embedding=[1.0, 0.0]),
    ])
    results = await store.search([1.0, 0.0], top_k=5)
    ids = {r.id for r in results}
    assert "has-embed" in ids
    assert "no-embed" not in ids


async def test_cosine_similarity_zero_vector_handled():
    store = InMemoryVectorStore()
    await store.upsert([VectorDocument(id="1", text="x", embedding=[0.0, 0.0])])
    results = await store.search([1.0, 0.0], top_k=1)
    # Zero-vector has cosine = 0, so it may appear but shouldn't crash
    assert isinstance(results, list)
