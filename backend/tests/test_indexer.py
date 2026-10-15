"""Tests for upsert-with-content-hash-skip indexing, against in-memory Qdrant."""

from __future__ import annotations

import pytest
from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient
from tests.factories import make_chunk, make_file_like_chunk

from law_agent.indexing import (
    Bm25SparseEmbedder,
    IndexStats,
    ensure_collection,
    index_chunks,
    prune_orphans,
    retag_conversation,
)

COLLECTION = "chunks"

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")


class CountingFakeEmbeddings(Embeddings):
    """Stub for OpenRouterEmbeddings that counts calls instead of hitting the network."""

    def __init__(self) -> None:
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [[float(len(text)), 0.0, 0.0, 0.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def _setup() -> tuple[QdrantClient, CountingFakeEmbeddings, Bm25SparseEmbedder]:
    client = QdrantClient(":memory:")
    # CountingFakeEmbeddings returns 4-dim vectors; match the collection to it
    # instead of the real 1024-dim OpenRouter size, which these tests never use.
    ensure_collection(client, COLLECTION, dense_size=4)
    return client, CountingFakeEmbeddings(), Bm25SparseEmbedder()


def test_first_index_embeds_all_chunks() -> None:
    client, embeddings, sparse = _setup()
    chunks = [make_chunk("c1", "první text"), make_chunk("c2", "druhý text")]

    stats = index_chunks(
        client, chunks, collection_name=COLLECTION, embeddings=embeddings, sparse_embedder=sparse
    )

    assert stats == IndexStats(total=2, embedded=2, skipped=0)
    assert embeddings.calls == 2
    assert client.count(COLLECTION).count == 2


def test_reindexing_unchanged_chunks_skips_embedding() -> None:
    client, embeddings, sparse = _setup()
    chunks = [make_chunk("c1", "první text"), make_chunk("c2", "druhý text")]
    index_chunks(
        client, chunks, collection_name=COLLECTION, embeddings=embeddings, sparse_embedder=sparse
    )
    calls_after_first_run = embeddings.calls

    stats = index_chunks(
        client, chunks, collection_name=COLLECTION, embeddings=embeddings, sparse_embedder=sparse
    )

    assert stats == IndexStats(total=2, embedded=0, skipped=2)
    assert embeddings.calls == calls_after_first_run


def test_changed_chunk_text_triggers_reembedding_of_only_that_chunk() -> None:
    client, embeddings, sparse = _setup()
    chunks = [make_chunk("c1", "první text"), make_chunk("c2", "druhý text")]
    index_chunks(
        client, chunks, collection_name=COLLECTION, embeddings=embeddings, sparse_embedder=sparse
    )
    changed = [make_chunk("c1", "první text ZMĚNĚN"), chunks[1]]

    stats = index_chunks(
        client, changed, collection_name=COLLECTION, embeddings=embeddings, sparse_embedder=sparse
    )

    assert stats == IndexStats(total=2, embedded=1, skipped=1)
    assert client.count(COLLECTION).count == 2


def test_indexes_a_chunk_from_a_source_that_is_not_a_law() -> None:
    client, embeddings, sparse = _setup()
    chunks = [make_file_like_chunk("f1", "interní směrnice o cestovních náhradách")]

    stats = index_chunks(
        client,
        chunks,
        collection_name=COLLECTION,
        embeddings=embeddings,
        sparse_embedder=sparse,
        namespace="org_files",
    )

    assert stats == IndexStats(total=1, embedded=1, skipped=0)
    assert client.count(COLLECTION).count == 1


def test_skip_check_works_for_a_source_that_is_not_a_law() -> None:
    client, embeddings, sparse = _setup()
    chunks = [make_file_like_chunk("f1", "interní směrnice o cestovních náhradách")]
    index_chunks(
        client,
        chunks,
        collection_name=COLLECTION,
        embeddings=embeddings,
        sparse_embedder=sparse,
        namespace="org_files",
    )
    calls_after_first_run = embeddings.calls

    stats = index_chunks(
        client,
        chunks,
        collection_name=COLLECTION,
        embeddings=embeddings,
        sparse_embedder=sparse,
        namespace="org_files",
    )

    assert stats == IndexStats(total=1, embedded=0, skipped=1)
    assert embeddings.calls == calls_after_first_run


def _index_files(
    client: QdrantClient,
    embeddings: CountingFakeEmbeddings,
    sparse: Bm25SparseEmbedder,
    chunks: list,
) -> None:
    index_chunks(
        client,
        chunks,
        collection_name=COLLECTION,
        embeddings=embeddings,
        sparse_embedder=sparse,
        namespace="org_files",
    )


def test_prune_orphans_removes_points_outside_keep() -> None:
    """A shorter new version of a document must not leave its old tail behind."""
    client, embeddings, sparse = _setup()
    chunks = [
        make_file_like_chunk("f1", "první", doc_id="smlouva.pdf"),
        make_file_like_chunk("f2", "druhý", doc_id="smlouva.pdf"),
        make_file_like_chunk("f3", "třetí", doc_id="smlouva.pdf"),
    ]
    _index_files(client, embeddings, sparse, chunks)

    removed = prune_orphans(
        client,
        COLLECTION,
        scope={"namespace": "org_files", "doc_id": "smlouva.pdf"},
        keep=[chunks[0].point_id, chunks[1].point_id],
    )

    assert removed == 1
    assert client.count(COLLECTION).count == 2


def test_prune_orphans_leaves_other_documents_alone() -> None:
    client, embeddings, sparse = _setup()
    mine = [make_file_like_chunk("a1", "můj", doc_id="smlouva.pdf")]
    theirs = [make_file_like_chunk("b1", "cizí", doc_id="faktura.pdf")]
    _index_files(client, embeddings, sparse, mine)
    _index_files(client, embeddings, sparse, theirs)

    removed = prune_orphans(
        client,
        COLLECTION,
        scope={"namespace": "org_files", "doc_id": "smlouva.pdf"},
        keep=[],
    )

    assert removed == 1
    assert client.count(COLLECTION).count == 1


def test_prune_orphans_leaves_other_namespaces_alone() -> None:
    client, embeddings, sparse = _setup()
    index_chunks(
        client,
        [make_chunk("c1", "zákonný text")],
        collection_name=COLLECTION,
        embeddings=embeddings,
        sparse_embedder=sparse,
    )

    removed = prune_orphans(client, COLLECTION, scope={"namespace": "org_files"}, keep=[])

    assert removed == 0
    assert client.count(COLLECTION).count == 1


def test_prune_orphans_keeps_everything_when_nothing_is_stale() -> None:
    client, embeddings, sparse = _setup()
    chunks = [make_file_like_chunk("f1", "první", doc_id="smlouva.pdf")]
    _index_files(client, embeddings, sparse, chunks)

    removed = prune_orphans(
        client,
        COLLECTION,
        scope={"namespace": "org_files", "doc_id": "smlouva.pdf"},
        keep=[chunks[0].point_id],
    )

    assert removed == 0
    assert client.count(COLLECTION).count == 1


def test_prune_orphans_on_missing_collection_is_a_noop() -> None:
    client = QdrantClient(":memory:")

    assert prune_orphans(client, "nope", scope={"namespace": "org_files"}, keep=[]) == 0


def test_retag_conversation_adds_the_key_to_every_point_of_the_document() -> None:
    client, embeddings, sparse = _setup()
    chunks = [
        make_file_like_chunk("f1", "první", doc_id="draft.pdf"),
        make_file_like_chunk("f2", "druhý", doc_id="draft.pdf"),
    ]
    _index_files(client, embeddings, sparse, chunks)

    retag_conversation(client, COLLECTION, doc_id="draft.pdf", conversation_id="conv-1")

    records = client.retrieve(
        COLLECTION, ids=[chunk.point_id for chunk in chunks], with_payload=True
    )
    assert all(record.payload["conversation_id"] == "conv-1" for record in records)


def test_retag_conversation_leaves_other_documents_alone() -> None:
    client, embeddings, sparse = _setup()
    mine = [make_file_like_chunk("a1", "můj", doc_id="draft.pdf")]
    theirs = [make_file_like_chunk("b1", "cizí", doc_id="jiny.pdf")]
    _index_files(client, embeddings, sparse, mine)
    _index_files(client, embeddings, sparse, theirs)

    retag_conversation(client, COLLECTION, doc_id="draft.pdf", conversation_id="conv-1")

    other = client.retrieve(COLLECTION, ids=[theirs[0].point_id], with_payload=True)[0]
    assert "conversation_id" not in other.payload


def test_retag_conversation_on_missing_collection_is_a_noop() -> None:
    client = QdrantClient(":memory:")

    retag_conversation(client, "nope", doc_id="draft.pdf", conversation_id="conv-1")  # no error
