"""Hybrid retrieval: one Qdrant Query API call, dense + sparse, RRF-fused."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient, models

from law_agent.indexing import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME, Bm25SparseEmbedder
from law_agent.ingestion.laws import NAMESPACE


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    score: float
    chunk_id: str
    citation: str
    text: str
    payload: dict[str, object]


def query_chunks(
    client: QdrantClient,
    query: str,
    *,
    collection_name: str,
    embeddings: Embeddings,
    sparse_embedder: Bm25SparseEmbedder,
    namespace: str | Sequence[str] = NAMESPACE,
    limit: int = 10,
    prefetch_limit: int = 50,
    extra_filter: Mapping[str, models.ValueVariants] | None = None,
    scoped_filter: tuple[str, models.Condition] | None = None,
) -> list[RetrievedChunk]:
    query_filter = _build_filter(namespace, extra_filter, scoped_filter)
    dense_vector = embeddings.embed_query(query)
    sparse_vector = sparse_embedder.embed_query(query)

    result = client.query_points(
        collection_name=collection_name,
        prefetch=[
            models.Prefetch(
                query=dense_vector,
                using=DENSE_VECTOR_NAME,
                filter=query_filter,
                limit=prefetch_limit,
            ),
            models.Prefetch(
                query=models.SparseVector(
                    indices=sparse_vector.indices, values=sparse_vector.values
                ),
                using=SPARSE_VECTOR_NAME,
                filter=query_filter,
                limit=prefetch_limit,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
    )

    chunks = (_to_retrieved_chunk(point) for point in result.points)
    return [chunk for chunk in chunks if chunk is not None]


def _to_retrieved_chunk(point: models.ScoredPoint) -> RetrievedChunk | None:
    """``None`` for a point whose payload is missing a required key.

    A partial upsert or a crash mid-batch can leave one bad point behind;
    that point must not take the whole query down with it.
    """
    payload = point.payload or {}
    if any(key not in payload for key in ("chunk_id", "citation", "text")):
        return None
    return RetrievedChunk(
        score=point.score,
        chunk_id=payload["chunk_id"],
        citation=payload["citation"],
        text=payload["text"],
        payload=payload,
    )


def _build_filter(
    namespace: str | Sequence[str],
    extra_filter: Mapping[str, models.ValueVariants] | None,
    scoped_filter: tuple[str, models.Condition] | None = None,
) -> models.Filter:
    conditions: list[models.Condition] = []
    if scoped_filter is not None and not isinstance(namespace, str):
        # A restriction on one namespace inside a multi-namespace call must not
        # leak onto the others -- folded into a flat `must` it would apply to
        # every namespace in the call, silently dropping unrelated hits (the
        # same mistake `_attachment_hits` is a separate call to avoid).
        target_namespace, target_condition = scoped_filter
        others = [value for value in namespace if value != target_namespace]
        should: list[models.Condition] = [
            models.Filter(
                must=[
                    models.FieldCondition(
                        key="namespace", match=models.MatchValue(value=target_namespace)
                    ),
                    target_condition,
                ]
            )
        ]
        if others:
            should.append(
                models.Filter(
                    must=[models.FieldCondition(key="namespace", match=_namespace_match(others))]
                )
            )
        conditions.append(models.Filter(should=should))
    else:
        conditions.append(models.FieldCondition(key="namespace", match=_namespace_match(namespace)))
        if scoped_filter is not None:
            conditions.append(scoped_filter[1])
    for key, value in (extra_filter or {}).items():
        conditions.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
    return models.Filter(must=conditions)


def _namespace_match(namespace: str | Sequence[str]) -> models.Match:
    # A str is a Sequence[str], so it has to be ruled out before the sequence
    # branch -- otherwise "laws" would be read as five one-character namespaces.
    if isinstance(namespace, str):
        return models.MatchValue(value=namespace)
    return models.MatchAny(any=list(namespace))
