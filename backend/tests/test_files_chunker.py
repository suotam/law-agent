"""Tests for chunking a parsed document into FileChunks."""

from __future__ import annotations

from tests.factories import make_docling_document

from law_agent.ingestion.files.chunker import FileChunker

DOC_ID = "3f1c9a5e-2b4d-4c8a-9e77-1d2f3a4b5c6d"
FILENAME = "dodatek.pdf"
FOLDER_ID = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"


def test_chunker_takes_the_filename_rather_than_deriving_it() -> None:
    """doc_id is a uuid now; the name has to be passed in."""
    chunks = FileChunker().chunk(make_docling_document(), doc_id=DOC_ID, filename=FILENAME)

    assert chunks
    assert all(chunk.doc_id == DOC_ID for chunk in chunks)
    assert all(chunk.filename == FILENAME for chunk in chunks)
    assert all(chunk.citation.startswith(FILENAME) for chunk in chunks)


def test_folder_id_reaches_the_payload_when_given() -> None:
    """Authorisation filters on folder_id, so it has to be in the payload."""
    chunks = FileChunker().chunk(
        make_docling_document(), doc_id=DOC_ID, filename=FILENAME, folder_id=FOLDER_ID
    )

    assert all(chunk.to_payload()["folder_id"] == FOLDER_ID for chunk in chunks)


def test_payload_omits_folder_id_for_an_in_chat_file() -> None:
    chunks = FileChunker().chunk(make_docling_document(), doc_id=DOC_ID, filename=FILENAME)

    assert "folder_id" not in chunks[0].to_payload()


def test_chunk_indices_are_contiguous_and_total_is_consistent() -> None:
    chunks = FileChunker().chunk(make_docling_document(), doc_id=DOC_ID, filename=FILENAME)

    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.chunk_total == len(chunks) for chunk in chunks)


def test_chunking_is_deterministic() -> None:
    document = make_docling_document()

    first = FileChunker().chunk(document, doc_id=DOC_ID, filename=FILENAME)
    second = FileChunker().chunk(document, doc_id=DOC_ID, filename=FILENAME)

    assert [c.point_id for c in first] == [c.point_id for c in second]
    assert [c.content_hash for c in first] == [c.content_hash for c in second]


def test_the_heading_stays_in_the_embedded_text() -> None:
    """It is no longer a prefix -- it is part of the body, where it is embedded."""
    chunks = FileChunker().chunk(make_docling_document(), doc_id=DOC_ID, filename=FILENAME)
    anchored = [c for c in chunks if "odstoupit od této smlouvy" in c.text]

    assert anchored, "expected a chunk containing the first section's body"
    assert "## Odstoupení od smlouvy" in anchored[0].text


def test_headings_are_captured_as_metadata() -> None:
    """A chunk is labelled by the last heading it contains, which is what the
    citation shows -- the whole factory document fits in one chunk."""
    chunks = FileChunker().chunk(make_docling_document(), doc_id=DOC_ID, filename=FILENAME)

    assert chunks[-1].headings == ["Závěrečná ustanovení"]
    assert chunks[-1].citation.endswith("Závěrečná ustanovení")


def test_headings_hold_at_most_the_last_seen_heading() -> None:
    """There is no hierarchy in the input, so there is no trail to build."""
    chunks = FileChunker().chunk(make_docling_document(), doc_id=DOC_ID, filename=FILENAME)

    assert all(len(chunk.headings) <= 1 for chunk in chunks)


def test_token_count_is_reported() -> None:
    chunks = FileChunker().chunk(make_docling_document(), doc_id=DOC_ID, filename=FILENAME)

    assert all(chunk.token_count > 0 for chunk in chunks)


def test_smaller_budget_produces_at_least_as_many_chunks() -> None:
    document = make_docling_document()

    few = FileChunker(max_tokens=768).chunk(document, doc_id=DOC_ID, filename=FILENAME)
    many = FileChunker(max_tokens=16).chunk(document, doc_id=DOC_ID, filename=FILENAME)

    assert len(many) >= len(few)


def test_the_chunker_passes_the_conversation_through() -> None:
    chunks = FileChunker(max_tokens=512).chunk(
        make_docling_document(),
        doc_id="d1",
        filename="priloha.pdf",
        conversation_id="11111111-1111-1111-1111-111111111111",
    )

    assert chunks
    assert all(chunk.conversation_id == "11111111-1111-1111-1111-111111111111" for chunk in chunks)
