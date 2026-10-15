"""End-to-end checks against the real law files in the repository.

These are the regression tests that matter: they run the whole pipeline over
laws of very different shape (a 357-fragment act with no chapters, a
3027-fragment code with chapters, divisions, annexes and 122 footnotes) and
assert the invariants that keep retrieval honest.
"""

from __future__ import annotations

from law_agent.ingestion import default_token_counter
from law_agent.ingestion.laws import ChunkingConfig, LawChunker, LawDocument, validate


def test_no_text_is_lost(real_document: LawDocument) -> None:
    config = ChunkingConfig()
    chunks = LawChunker(config=config).chunk(real_document)
    report = validate(real_document, chunks, config)

    assert report.missing_fragments == [], report.describe()
    assert report.coverage == 1.0


def test_chunks_respect_the_token_budget(real_document: LawDocument) -> None:
    config = ChunkingConfig(max_tokens=768)
    chunks = LawChunker(config=config).chunk(real_document)

    oversized = [(c.citation, c.token_count) for c in chunks if c.token_count > config.max_tokens]
    assert oversized == []


def test_chunks_are_unique_non_empty_and_citable(real_document: LawDocument) -> None:
    chunks = LawChunker().chunk(real_document)

    assert chunks
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert len({chunk.point_id for chunk in chunks}) == len(chunks)
    assert all(chunk.body.strip() for chunk in chunks)
    assert all(chunk.citation.strip() for chunk in chunks)
    assert all(chunk.source_fragment_ids for chunk in chunks)


def test_chunking_is_deterministic(real_document: LawDocument) -> None:
    first = LawChunker().chunk(real_document)
    second = LawChunker().chunk(
        LawDocument.from_fragments([n.fragment for n in real_document.root.walk()])
    )

    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert [c.content_hash for c in first] == [c.content_hash for c in second]


def test_smaller_budget_still_covers_everything(real_document: LawDocument) -> None:
    """The budget is a tuning knob, not a correctness assumption."""
    config = ChunkingConfig(max_tokens=256, min_tokens=64)
    chunks = LawChunker(config=config).chunk(real_document)
    report = validate(real_document, chunks, config)

    assert report.ok, report.describe()
    assert all(chunk.token_count <= config.max_tokens for chunk in chunks)


def test_size_distribution_is_healthy(real_document: LawDocument) -> None:
    """Guards the two failure modes that quietly wreck retrieval: chunks that
    carry no real text, and a median so low that chunks lose their context.

    Deliberately no floor at ``min_tokens``: a titled section is never merged
    away, so a one-sentence "§ 22 – Účinnost" legitimately stands alone. Short
    is not a defect when the boundary is a whole citable unit.
    """
    config = ChunkingConfig()
    chunks = LawChunker(config=config).chunk(real_document)
    count_tokens = default_token_counter()
    counts = sorted(chunk.token_count for chunk in chunks)
    empty = [c for c in chunks if count_tokens(c.body) < 10]

    assert not empty, f"chunks with no real body: {[c.citation for c in empty]}"
    assert counts[len(counts) // 2] > config.max_tokens * 0.35


def test_footnotes_are_not_harvested_from_cross_references(real_document: LawDocument) -> None:
    """Every claimed marker must occur as a marker, not inside a longer number."""
    chunks = LawChunker().chunk(real_document)

    for chunk in chunks:
        for marker in chunk.footnotes:
            occurrences = [
                index
                for index in range(1, len(chunk.body))
                if chunk.body.startswith(marker, index)
                and chunk.body[index - 1] not in " ([\t\n"
                and not chunk.body[index - 1].isdigit()
            ]
            assert occurrences, f"{chunk.citation} claims {marker} but never references it"


def test_no_unknown_fragment_types(real_document: LawDocument) -> None:
    """Fails when the API introduces a type worth classifying explicitly."""
    assert real_document.report.unknown_types == {}


def test_chunks_are_in_document_order(real_document: LawDocument) -> None:
    chunks = [c for c in LawChunker().chunk(real_document) if c.part != "poznamkypodcarou"]
    starts = [chunk.position_start for chunk in chunks]

    assert starts == sorted(starts)
