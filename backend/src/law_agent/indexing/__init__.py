"""Indexing pipeline: chunks -> dense + sparse vectors -> Qdrant upserts."""

from law_agent.indexing.indexer import IndexStats, index_chunks, prune_orphans, retag_conversation
from law_agent.indexing.protocols import ChunkLike
from law_agent.indexing.qdrant_store import (
    DENSE_SIZE,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    ensure_collection,
    get_qdrant_client,
)
from law_agent.indexing.sparse import Bm25SparseEmbedder, SparseVector, get_sparse_embedder

__all__ = [
    "DENSE_SIZE",
    "DENSE_VECTOR_NAME",
    "SPARSE_VECTOR_NAME",
    "Bm25SparseEmbedder",
    "ChunkLike",
    "IndexStats",
    "SparseVector",
    "ensure_collection",
    "get_qdrant_client",
    "get_sparse_embedder",
    "index_chunks",
    "prune_orphans",
    "retag_conversation",
]
