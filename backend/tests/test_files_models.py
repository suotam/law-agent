"""Tests for FileChunk: identity, citation and the payload contract."""

from __future__ import annotations

from typing import Any

from law_agent.ingestion.files.models import FileChunk

# The keys the indexing and retrieval layers read by name; see
# ``law_agent.indexing.protocols.ChunkLike.to_payload``.
_REQUIRED_PAYLOAD_KEYS = {"namespace", "content_hash", "chunk_id", "citation", "text"}


def _chunk(**overrides: Any) -> FileChunk:
    defaults: dict[str, Any] = {
        "doc_id": "smlouvy/dodatek.pdf",
        "filename": "dodatek.pdf",
        "text": "## Odstoupení od smlouvy\n\nSmluvní strany se dohodly...",
        "headings": ["Odstoupení od smlouvy"],
        "pages": [4],
        "chunk_index": 0,
        "chunk_total": 3,
        "token_count": 12,
    }
    return FileChunk.create(**{**defaults, **overrides})


def test_chunk_id_is_doc_id_and_index() -> None:
    assert _chunk().chunk_id == "smlouvy/dodatek.pdf#0"


def test_identity_is_deterministic() -> None:
    assert _chunk().point_id == _chunk().point_id


def test_different_index_yields_different_point_id() -> None:
    assert _chunk(chunk_index=0).point_id != _chunk(chunk_index=1).point_id


def test_content_hash_follows_text() -> None:
    assert _chunk().content_hash != _chunk(text="jiný text").content_hash


def test_content_hash_ignores_metadata() -> None:
    """Only the embedded text decides whether re-embedding is needed."""
    assert _chunk().content_hash == _chunk(pages=[9], token_count=99).content_hash


def test_citation_names_file_page_and_heading() -> None:
    citation = _chunk().citation

    assert "dodatek.pdf" in citation
    assert "s. 4" in citation
    assert "Odstoupení od smlouvy" in citation


def test_citation_without_pages_or_headings() -> None:
    assert _chunk(pages=[], headings=[]).citation == "dodatek.pdf"


def test_citation_spanning_pages() -> None:
    assert "s. 4–6" in _chunk(pages=[4, 5, 6]).citation


def test_citation_uses_the_innermost_heading() -> None:
    citation = _chunk(headings=["Smlouva", "Odstoupení od smlouvy"]).citation

    assert citation.endswith("Odstoupení od smlouvy")


def test_payload_has_every_required_key() -> None:
    payload = _chunk().to_payload(namespace="org_files")

    assert _REQUIRED_PAYLOAD_KEYS <= set(payload)
    assert payload["namespace"] == "org_files"


def test_payload_carries_source_specific_fields() -> None:
    payload = _chunk().to_payload(namespace="org_files")

    assert payload["doc_id"] == "smlouvy/dodatek.pdf"
    assert payload["pages"] == [4]
    assert payload["headings"] == ["Odstoupení od smlouvy"]


def test_payload_values_are_scalars_or_lists() -> None:
    """Any vector store must be able to index and filter on the payload."""
    for key, value in _chunk().to_payload(namespace="org_files").items():
        assert isinstance(value, str | int | float | bool | list | type(None)), key


def test_file_chunk_satisfies_chunk_like() -> None:
    """Static proof that the indexer accepts FileChunk without importing it."""
    from law_agent.indexing.protocols import ChunkLike

    chunk: ChunkLike = _chunk()

    assert chunk.point_id


def test_payload_carries_folder_id_when_present() -> None:
    """The key the authorisation filter will match on."""
    folder_id = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"

    payload = _chunk(folder_id=folder_id).to_payload(namespace="org_files")

    assert payload["folder_id"] == folder_id


def test_an_in_chat_chunk_carries_its_conversation() -> None:
    """The retrieval filter runs in Qdrant, which has no joins -- so the
    conversation has to be in the payload, not one hop away in Postgres."""
    chunk = FileChunk.create(
        doc_id="d1",
        filename="priloha.pdf",
        text="Text přílohy.",
        headings=[],
        pages=[],
        chunk_index=0,
        chunk_total=1,
        token_count=3,
        conversation_id="11111111-1111-1111-1111-111111111111",
    )

    payload = chunk.to_payload(namespace="user_files")

    assert payload["conversation_id"] == "11111111-1111-1111-1111-111111111111"


def test_an_org_chunk_has_no_conversation_key_at_all() -> None:
    """Omitted rather than null, for the same reason as ``folder_id``: a
    MatchValue filter should not have to know about a sentinel."""
    chunk = FileChunk.create(
        doc_id="d1",
        filename="smlouva.pdf",
        text="Text.",
        headings=[],
        pages=[],
        chunk_index=0,
        chunk_total=1,
        token_count=2,
        folder_id="22222222-2222-2222-2222-222222222222",
    )

    assert "conversation_id" not in chunk.to_payload()


def test_payload_has_no_body_key() -> None:
    """It would only repeat ``text``, and nothing reads it."""
    assert "body" not in _chunk().to_payload()
