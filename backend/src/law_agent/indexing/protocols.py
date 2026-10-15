"""The contract a chunk must satisfy to be indexed.

Declared here, in the consumer, rather than in ``ingestion``: producers
(``LawChunk`` today, a file-backed chunk later) satisfy it structurally, with
no base class and no import. That keeps ``indexing`` free of any dependency on
a particular ingestion pipeline.

Members are read-only properties rather than bare annotations because the
indexer only ever reads them, and a mutable protocol attribute would reject
frozen producers such as pydantic models with ``frozen=True``.
"""

from __future__ import annotations

from typing import Any, Protocol


class ChunkLike(Protocol):
    """The minimum an indexable chunk exposes."""

    @property
    def point_id(self) -> str:
        """Vector-store point id. Must be deterministic, so that re-indexing a
        source upserts in place instead of duplicating."""
        ...

    @property
    def content_hash(self) -> str:
        """Hash of :attr:`text`; lets indexing skip re-embedding unchanged
        chunks."""
        ...

    @property
    def text(self) -> str:
        """What gets embedded, dense and sparse alike."""
        ...

    def to_payload(self, *, namespace: str) -> dict[str, Any]:
        """Flatten into a vector-store payload.

        Five keys are mandatory, because the indexing and retrieval layers read
        them by name:

        - ``namespace`` -- skip check and query filter
        - ``content_hash`` -- lets indexing skip unchanged chunks
        - ``chunk_id`` -- identity of a retrieval result
        - ``citation`` -- human-readable source reference in the answer
        - ``text`` -- body of a retrieval result

        Anything beyond these five is specific to the source and reaches
        callers through ``RetrievedChunk.payload``.
        """
        ...
