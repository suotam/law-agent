"""Tests for Qdrant collection schema setup, against an in-memory instance."""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient, models

from law_agent.indexing import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME, ensure_collection

COLLECTION = "chunks"

# The in-memory (":memory:") Qdrant client doesn't support payload indexes and
# warns on creation; the real server used outside tests does support them.
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")


def test_ensure_collection_creates_dense_and_sparse_vectors() -> None:
    client = QdrantClient(":memory:")

    ensure_collection(client, COLLECTION)

    info = client.get_collection(COLLECTION)
    dense = info.config.params.vectors[DENSE_VECTOR_NAME]
    assert dense.size == 1024
    assert dense.distance == models.Distance.COSINE
    assert SPARSE_VECTOR_NAME in info.config.params.sparse_vectors


def test_ensure_collection_is_idempotent() -> None:
    client = QdrantClient(":memory:")

    ensure_collection(client, COLLECTION)
    ensure_collection(client, COLLECTION)  # must not raise

    assert client.collection_exists(COLLECTION)
