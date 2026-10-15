"""Qdrant client factory and the `chunks` collection schema.

One collection, shared across namespaces (``laws``, ``org_files``,
``user_files``) — namespace is a filtered payload field, not a separate
collection. See ``docs/superpowers/specs/2026-08-04-hybrid-retrieval-design.md``.
"""

from __future__ import annotations

from functools import lru_cache

from qdrant_client import QdrantClient, models

from law_agent.config import settings

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
DENSE_SIZE = 1024


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    # Cached: the client keeps an HTTP connection pool, and ingestion used to
    # build a fresh one per call for no benefit.
    return QdrantClient(url=settings.qdrant_url)


_PAYLOAD_INDEXES = ("namespace", "conversation_id")


def ensure_collection(
    client: QdrantClient, collection_name: str, *, dense_size: int = DENSE_SIZE
) -> None:
    """Create the collection if missing, and its payload indexes if missing.

    The index check runs on every call, not only at creation: a filtered field
    added after the collection already existed would otherwise never get one,
    and Qdrant would fall back to a full scan.
    """
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=dense_size, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )

    existing = client.get_collection(collection_name).payload_schema or {}
    for field_name in _PAYLOAD_INDEXES:
        if field_name not in existing:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
