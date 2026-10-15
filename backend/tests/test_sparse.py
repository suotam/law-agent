"""Tests for the local BM25 sparse embedder (no network, no mocking)."""

from __future__ import annotations

from law_agent.indexing import Bm25SparseEmbedder, SparseVector


def test_embed_documents_returns_nonempty_sparse_vectors() -> None:
    embedder = Bm25SparseEmbedder()
    [vector] = embedder.embed_documents(["zaměstnavatel musí zaměstnance převést na jinou práci"])
    assert isinstance(vector, SparseVector)
    assert vector.indices
    assert len(vector.indices) == len(vector.values)
    assert all(value > 0 for value in vector.values)


def test_embed_query_matches_single_document_embedding() -> None:
    embedder = Bm25SparseEmbedder()
    text = "§ 41 odstavec 1"
    assert embedder.embed_query(text) == embedder.embed_documents([text])[0]


def test_different_texts_yield_different_vectors() -> None:
    embedder = Bm25SparseEmbedder()
    a, b = embedder.embed_documents(["§ 41 převedení na jinou práci", "právo na informace"])
    assert a != b
