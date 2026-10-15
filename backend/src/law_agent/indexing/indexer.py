"""Upsert chunks into Qdrant, skipping ones whose content is unchanged."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient, models

from law_agent.indexing.protocols import ChunkLike
from law_agent.indexing.qdrant_store import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME
from law_agent.indexing.sparse import Bm25SparseEmbedder


@dataclass(frozen=True, slots=True)
class IndexStats:
    total: int
    embedded: int
    skipped: int


def index_chunks(
    client: QdrantClient,
    chunks: Sequence[ChunkLike],
    *,
    collection_name: str,
    embeddings: Embeddings,
    sparse_embedder: Bm25SparseEmbedder,
    namespace: str = "laws",
    batch_size: int = 64,
) -> IndexStats:
    existing = _fetch_existing(client, collection_name, chunks)
    to_embed = [
        chunk for chunk in chunks if existing.get(chunk.point_id) != (chunk.content_hash, namespace)
    ]

    for start in range(0, len(to_embed), batch_size):
        batch = to_embed[start : start + batch_size]
        _upsert_batch(client, collection_name, batch, embeddings, sparse_embedder, namespace)

    return IndexStats(
        total=len(chunks), embedded=len(to_embed), skipped=len(chunks) - len(to_embed)
    )


def _upsert_batch(
    client: QdrantClient,
    collection_name: str,
    batch: Sequence[ChunkLike],
    embeddings: Embeddings,
    sparse_embedder: Bm25SparseEmbedder,
    namespace: str,
) -> None:
    texts = [chunk.text for chunk in batch]
    dense_vectors = embeddings.embed_documents(texts)
    sparse_vectors = sparse_embedder.embed_documents(texts)

    points = [
        models.PointStruct(
            id=chunk.point_id,
            vector={
                DENSE_VECTOR_NAME: dense,
                SPARSE_VECTOR_NAME: models.SparseVector(
                    indices=sparse.indices, values=sparse.values
                ),
            },
            payload=chunk.to_payload(namespace=namespace),
        )
        for chunk, dense, sparse in zip(batch, dense_vectors, sparse_vectors, strict=True)
    ]
    client.upsert(collection_name=collection_name, points=points)


def prune_orphans(
    client: QdrantClient,
    collection_name: str,
    *,
    scope: dict[str, str],
    keep: Sequence[str],
) -> int:
    """Delete points matching ``scope`` that are not in ``keep``.

    Re-indexing a source upserts its chunks in place, but a shorter new version
    produces fewer of them; without this, the leftovers would keep being
    retrieved as if they were still part of the document.

    Deliberately generic: it filters on payload keys the caller names, so the
    same function scopes a file (``{"namespace": ..., "doc_id": ...}``) or a law
    (``{"law_id": ...}``). Called after :func:`index_chunks` rather than from
    inside it, so that indexing itself stays purely additive.

    Args:
        client: Qdrant client.
        collection_name: Collection to prune.
        scope: Payload keys that must all match for a point to be in scope.
        keep: Point ids to preserve -- typically every point just upserted.

    Returns:
        Number of points deleted.
    """
    if not client.collection_exists(collection_name):
        return 0

    selector = models.Filter(
        must=[
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in scope.items()
        ],
        must_not=[models.HasIdCondition(has_id=list(keep))] if keep else None,
    )

    stale = client.count(collection_name, count_filter=selector, exact=True).count
    if stale:
        client.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(filter=selector),
            wait=True,
        )
    return stale


def retag_conversation(
    client: QdrantClient,
    collection_name: str,
    *,
    doc_id: str | UUID,
    conversation_id: str | UUID,
) -> None:
    """Add ``conversation_id`` to every point of ``doc_id``'s chunks.

    Payload-only: an unbound draft is indexed with no ``conversation_id`` key
    at all, which is what keeps it out of every conversation-scoped search.
    This is the one write that makes it reachable -- no embedding is touched.
    """
    if not client.collection_exists(collection_name):
        return
    selector = models.Filter(
        must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=str(doc_id)))]
    )
    client.set_payload(
        collection_name=collection_name,
        payload={"conversation_id": str(conversation_id)},
        points=selector,
        wait=True,
    )


def _fetch_existing(
    client: QdrantClient, collection_name: str, chunks: Sequence[ChunkLike]
) -> dict[str, tuple[str, str]]:
    """Point id -> (content_hash, namespace) currently stored in Qdrant.

    Compared against a chunk's own (content_hash, namespace) to decide
    whether it needs re-embedding — catches both a text change and a
    namespace change (e.g. re-indexing the same chunk into ``org_files``).
    """
    if not chunks or not client.collection_exists(collection_name):
        return {}

    records = client.retrieve(
        collection_name=collection_name,
        ids=[chunk.point_id for chunk in chunks],
        with_payload=["content_hash", "namespace"],
    )
    return {
        str(record.id): (record.payload["content_hash"], record.payload["namespace"])
        for record in records
        if record.payload
    }
