"""Tests for hybrid (dense + sparse, RRF-fused) retrieval, against in-memory Qdrant."""

from __future__ import annotations

import dataclasses
from typing import ClassVar

import pytest
from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient, models
from tests.factories import make_chunk, make_file_like_chunk

from law_agent.indexing import Bm25SparseEmbedder, ensure_collection, index_chunks
from law_agent.ingestion import make_point_id
from law_agent.retrieval import RetrievedChunk, query_chunks
from law_agent.retrieval.retriever import _to_retrieved_chunk

COLLECTION = "chunks"

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")


class KeywordFakeEmbeddings(Embeddings):
    """Deterministic stand-in for OpenRouterEmbeddings.

    Maps any text containing one of a fixed set of keywords to that
    keyword's basis vector, and everything else to a shared default vector.
    This lets a test simulate "semantically related, lexically different"
    text pairs (real dense embedders would place them close together)
    without a real model or network access.
    """

    _BASIS: ClassVar[dict[str, list[float]]] = {
        "jinou práci": [1.0, 0.0, 0.0, 0.0],
        "výkonu jiné práce": [1.0, 0.0, 0.0, 0.0],
        "informace": [0.0, 1.0, 0.0, 0.0],
    }
    _DEFAULT: ClassVar[list[float]] = [0.0, 0.0, 1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        for keyword, vector in self._BASIS.items():
            if keyword in text:
                return vector
        return self._DEFAULT


def _indexed_client(chunks, *, namespace: str = "laws") -> QdrantClient:
    client = QdrantClient(":memory:")
    ensure_collection(client, COLLECTION, dense_size=4)
    index_chunks(
        client,
        chunks,
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace=namespace,
    )
    return client


def test_literal_query_finds_expected_chunk_via_sparse_branch() -> None:
    target = make_chunk("c1", "§ 41 odst. 1 upravuje převedení na jinou práci", citation="§ 41")
    other = make_chunk("c2", "§ 110 upravuje mzdu za práci přesčas", citation="§ 110")
    client = _indexed_client([target, other])

    results = query_chunks(
        client,
        "§ 41",
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
    )

    assert results
    assert results[0].chunk_id == "c1"


def test_semantic_query_finds_expected_chunk_via_dense_branch() -> None:
    target = make_chunk("c1", "zaměstnavatel je povinen umožnit výkonu jiné práce", citation="§ 41")
    other = make_chunk("c2", "právo na informace podle zákona", citation="§ 3")
    client = _indexed_client([target, other])

    results = query_chunks(
        client,
        "kdy musí zaměstnavatel převést zaměstnance na jinou práci",
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
    )

    assert results
    assert results[0].chunk_id == "c1"


def test_namespace_filter_restricts_results() -> None:
    laws_chunk = make_chunk("c1", "§ 41 převedení na jinou práci", citation="§ 41")
    org_chunk = make_chunk(
        "c2", "§ 41 převedení na jinou práci - interní směrnice", citation="§ 41"
    )
    client = QdrantClient(":memory:")
    ensure_collection(client, COLLECTION, dense_size=4)
    index_chunks(
        client,
        [laws_chunk],
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="laws",
    )
    index_chunks(
        client,
        [org_chunk],
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="org_files",
    )

    results = query_chunks(
        client,
        "§ 41",
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="laws",
    )

    assert {result.chunk_id for result in results} == {"c1"}


def test_sequence_namespace_matches_any_of_them() -> None:
    laws_chunk = make_chunk("c1", "§ 41 převedení na jinou práci", citation="§ 41")
    files_chunk = make_file_like_chunk("f1", "směrnice o převedení na jinou práci")
    other_chunk = make_file_like_chunk("f2", "právo na informace podle zákona")
    client = QdrantClient(":memory:")
    ensure_collection(client, COLLECTION, dense_size=4)
    index_chunks(
        client,
        [laws_chunk],
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="laws",
    )
    index_chunks(
        client,
        [files_chunk],
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="org_files",
    )
    index_chunks(
        client,
        [other_chunk],
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="user_files",
    )

    results = query_chunks(
        client,
        "převedení na jinou práci",
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace=["laws", "org_files"],
    )

    assert {result.chunk_id for result in results} == {"c1", "f1"}


def test_single_namespace_still_takes_a_plain_string() -> None:
    """A str is itself a Sequence[str] -- the string branch must win, or
    "laws" would be read as five one-character namespaces."""
    laws_chunk = make_chunk("c1", "§ 41 převedení na jinou práci", citation="§ 41")
    client = _indexed_client([laws_chunk], namespace="laws")

    results = query_chunks(
        client,
        "§ 41",
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="laws",
    )

    assert {result.chunk_id for result in results} == {"c1"}


def test_a_point_missing_a_required_payload_key_is_skipped_not_raised() -> None:
    """A partial upsert or a crash mid-batch can leave one bad point in
    Qdrant -- that point must not take the whole query down with it."""
    point = models.ScoredPoint(
        id="p1", version=1, score=0.9, payload={"chunk_id": "c1", "citation": "§ 1"}
    )

    assert _to_retrieved_chunk(point) is None


def test_query_chunks_skips_a_malformed_point_and_keeps_the_rest() -> None:
    good = make_chunk("c1", "§ 41 převedení na jinou práci", citation="§ 41")
    client = _indexed_client([good])
    client.delete_payload(collection_name=COLLECTION, keys=["text"], points=[make_point_id("c1")])

    results = query_chunks(
        client,
        "§ 41",
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
    )

    assert results == []


def test_retrieved_chunk_carries_no_source_specific_fields() -> None:
    """The result type must stay usable for laws and files alike -- a field
    only one source can fill does not belong on it."""
    names = {field.name for field in dataclasses.fields(RetrievedChunk)}

    assert names == {"score", "chunk_id", "citation", "text", "payload"}


def test_query_returns_a_result_from_a_source_that_is_not_a_law() -> None:
    chunk = make_file_like_chunk("f1", "směrnice o cestovních náhradách")
    client = _indexed_client([chunk], namespace="org_files")

    results = query_chunks(
        client,
        "cestovní náhrady",
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="org_files",
    )

    assert results
    assert results[0].chunk_id == "f1"
    assert results[0].citation == "smernice.pdf, s. 1"
    # Source-specific metadata still reaches the caller, just via the payload.
    assert results[0].payload["file_name"] == "smernice.pdf"


def test_scoped_filter_restricts_one_namespace_inside_a_combined_query() -> None:
    laws_chunk = make_chunk("c1", "§ 41 převedení na jinou práci", citation="§ 41")
    allowed_chunk = make_file_like_chunk(
        "f1", "převedení na jinou práci", folder_id="11111111-1111-1111-1111-111111111111"
    )
    blocked_chunk = make_file_like_chunk(
        "f2", "převedení na jinou práci", folder_id="22222222-2222-2222-2222-222222222222"
    )
    client = QdrantClient(":memory:")
    ensure_collection(client, COLLECTION, dense_size=4)
    index_chunks(
        client,
        [laws_chunk],
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="laws",
    )
    index_chunks(
        client,
        [allowed_chunk, blocked_chunk],
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="org_files",
    )
    condition = models.FieldCondition(
        key="folder_id", match=models.MatchAny(any=["11111111-1111-1111-1111-111111111111"])
    )

    results = query_chunks(
        client,
        "převedení na jinou práci",
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace=["laws", "org_files"],
        scoped_filter=("org_files", condition),
    )

    assert {result.chunk_id for result in results} == {"c1", "f1"}


def test_scoped_filter_on_a_single_matching_namespace_still_restricts_it() -> None:
    allowed_chunk = make_file_like_chunk(
        "f1", "převedení na jinou práci", folder_id="11111111-1111-1111-1111-111111111111"
    )
    blocked_chunk = make_file_like_chunk(
        "f2", "převedení na jinou práci", folder_id="22222222-2222-2222-2222-222222222222"
    )
    client = QdrantClient(":memory:")
    ensure_collection(client, COLLECTION, dense_size=4)
    index_chunks(
        client,
        [allowed_chunk, blocked_chunk],
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="org_files",
    )
    condition = models.FieldCondition(
        key="folder_id", match=models.MatchAny(any=["11111111-1111-1111-1111-111111111111"])
    )

    results = query_chunks(
        client,
        "převedení na jinou práci",
        collection_name=COLLECTION,
        embeddings=KeywordFakeEmbeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace="org_files",
        scoped_filter=("org_files", condition),
    )

    assert {result.chunk_id for result in results} == {"f1"}
