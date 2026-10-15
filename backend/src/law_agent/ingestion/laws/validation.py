"""Invariant checks over a chunked law.

The same report powers the test suite and the CLI, so a regression shows up
identically in CI and when a new law is ingested by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from law_agent.ingestion.laws.chunker import ChunkingConfig
from law_agent.ingestion.laws.document import LawDocument
from law_agent.ingestion.laws.models import LawChunk
from law_agent.ingestion.laws.taxonomy import Role


@dataclass(slots=True)
class ValidationReport:
    """Outcome of :func:`validate`. Falsy issue lists mean the chunking is sound."""

    total_chunks: int = 0
    covered_fragments: int = 0
    expected_fragments: int = 0

    missing_fragments: list[str] = field(default_factory=list)
    """Text-bearing fragments absent from every chunk -- i.e. lost content."""

    oversized_chunks: list[tuple[str, int]] = field(default_factory=list)
    empty_chunks: list[str] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    unknown_types: dict[str, int] = field(default_factory=dict)

    @property
    def coverage(self) -> float:
        if not self.expected_fragments:
            return 1.0
        return self.covered_fragments / self.expected_fragments

    @property
    def ok(self) -> bool:
        return not (
            self.missing_fragments
            or self.oversized_chunks
            or self.empty_chunks
            or self.duplicate_ids
        )

    def describe(self) -> str:
        lines = [
            f"chunks={self.total_chunks}",
            f"coverage={self.coverage:.4%} ({self.covered_fragments}/{self.expected_fragments})",
        ]
        if self.missing_fragments:
            lines.append(f"MISSING {len(self.missing_fragments)}: {self.missing_fragments[:5]}")
        if self.oversized_chunks:
            lines.append(f"OVERSIZED {len(self.oversized_chunks)}: {self.oversized_chunks[:5]}")
        if self.empty_chunks:
            lines.append(f"EMPTY {len(self.empty_chunks)}")
        if self.duplicate_ids:
            lines.append(f"DUPLICATE IDS {len(self.duplicate_ids)}: {self.duplicate_ids[:5]}")
        if self.unknown_types:
            lines.append(f"unknown types: {self.unknown_types}")
        return " | ".join(lines)


def validate(
    document: LawDocument,
    chunks: list[LawChunk],
    config: ChunkingConfig | None = None,
) -> ValidationReport:
    """Check the invariants that matter for retrieval quality.

    * **Coverage** -- every text-bearing fragment that the configuration says to
      index appears in at least one chunk. This is the check that catches a new
      law shape silently dropping content.
    * **Size** -- no chunk exceeds the embedding model's hard limit.
    * **Identity** -- ``chunk_id`` values are unique.
    * **Non-emptiness** -- no chunk is header-only.
    """
    config = config or ChunkingConfig()
    report = ValidationReport(
        total_chunks=len(chunks), unknown_types=dict(document.report.unknown_types)
    )

    covered = {fragment_id for chunk in chunks for fragment_id in chunk.source_fragment_ids}
    expected = _expected_fragment_ids(document, config)
    report.expected_fragments = len(expected)
    report.covered_fragments = len(expected & covered)
    report.missing_fragments = sorted(expected - covered)

    seen: set[str] = set()
    for chunk in chunks:
        if chunk.token_count > config.hard_max_tokens:
            report.oversized_chunks.append((chunk.citation, chunk.token_count))
        if not chunk.body.strip():
            report.empty_chunks.append(chunk.chunk_id)
        if chunk.chunk_id in seen:
            report.duplicate_ids.append(chunk.chunk_id)
        seen.add(chunk.chunk_id)

    return report


def _expected_fragment_ids(document: LawDocument, config: ChunkingConfig) -> set[str]:
    """Fragments that must end up in some chunk under ``config``."""
    excluded_parts = set(config.excluded_parts) | {"poznamkypodcarou"}
    if not config.include_frontmatter:
        excluded_parts |= {"prefix", "postfix"}
    if not config.include_annexes:
        excluded_parts.add("prilohy")

    expected: set[str] = set()
    for node in document.root.walk():
        if node.role is not Role.TEXT or not node.content:
            continue
        if document.part_of(node) in excluded_parts:
            continue
        expected.add(node.fragment_id)
    return expected
