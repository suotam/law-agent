"""Ingestion pipeline for Czech laws: fragments -> document tree -> RAG chunks.

    >>> from law_agent.ingestion.laws import LawDocument, LawChunker
    >>> document = LawDocument.from_json("zakon.json")  # doctest: +SKIP
    >>> chunks = LawChunker().chunk(document)  # doctest: +SKIP

See ``docs/CHUNKING.md`` for the design rationale and tuning guidance.
"""

from law_agent.ingestion.identity import make_point_id
from law_agent.ingestion.laws.chunker import (
    ChunkingConfig,
    ChunkingStats,
    FootnoteMode,
    LawChunker,
    chunk_law,
)
from law_agent.ingestion.laws.document import (
    LawDocument,
    ParseReport,
    build_tree,
    extract_metadata,
)
from law_agent.ingestion.laws.models import (
    NAMESPACE,
    BreadcrumbEntry,
    Fragment,
    LawChunk,
    LawMetadata,
    Node,
)
from law_agent.ingestion.laws.taxonomy import Role
from law_agent.ingestion.laws.validation import ValidationReport, validate

__all__ = [
    "NAMESPACE",
    "BreadcrumbEntry",
    "ChunkingConfig",
    "ChunkingStats",
    "FootnoteMode",
    "Fragment",
    "LawChunk",
    "LawChunker",
    "LawDocument",
    "LawMetadata",
    "Node",
    "ParseReport",
    "Role",
    "ValidationReport",
    "build_tree",
    "chunk_law",
    "extract_metadata",
    "make_point_id",
    "validate",
]
