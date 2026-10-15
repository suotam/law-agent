"""The retrieval unit produced from a generic file.

Named for its source, mirroring ``LawChunk``: the two are independent producers
of the same contract (``law_agent.indexing.protocols.ChunkLike``), which they
satisfy structurally -- there is deliberately no inheritance link and no import
between them.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict

from law_agent.ingestion.identity import make_point_id

NAMESPACE = "org_files"


class FileChunk(BaseModel):
    """A chunk of a parsed document, ready to embed and cite."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    """``<doc_id>#<index>``. Deterministic and content-independent, so that
    re-ingesting an edited document updates rows in place."""

    point_id: str
    """UUID derived from :attr:`chunk_id`, usable directly as a Qdrant point id."""

    content_hash: str
    """Hash of :attr:`text`; lets ingestion skip re-embedding unchanged chunks."""

    text: str
    """What gets embedded: the chunk's items in reading order, headings
    included -- a heading is ordinary text in the body, not a prefix."""

    doc_id: str
    """Identity of the source document -- the uuid of its ``documents`` row.
    Re-ingestion and orphan pruning are scoped by this field, and it is the same
    value in Postgres and in the Qdrant payload."""

    folder_id: str | None = None
    """Folder the document sits in, absent for an in-chat file.

    In the payload rather than a list of roles: authorisation resolves a user's
    roles to a set of allowed folder ids in Postgres and passes that into the
    retrieval filter. With roles here instead, every permission change would
    rewrite the payloads of every affected chunk.
    """

    conversation_id: str | None = None
    """Conversation an in-chat attachment was uploaded into, absent for an org
    file. Retrieval filters on it, and the vector store has no joins -- which is
    why it is here and not only on the ``documents`` row."""

    filename: str
    headings: list[str]
    """The last heading seen at or before this chunk, or empty. One entry at
    most: the input has no heading levels, so there is no trail to build."""

    pages: list[int]
    """Pages the chunk spans; empty when the source carries no provenance."""

    citation: str
    """Human-readable source reference, e.g.
    ``dodatek.pdf, s. 4 – Odstoupení od smlouvy``."""

    chunk_index: int
    chunk_total: int
    token_count: int
    char_count: int

    @classmethod
    def create(
        cls,
        *,
        doc_id: str,
        filename: str,
        text: str,
        headings: list[str],
        pages: list[int],
        chunk_index: int,
        chunk_total: int,
        token_count: int,
        folder_id: str | None = None,
        conversation_id: str | None = None,
    ) -> FileChunk:
        """Build a chunk, deriving identity, content hash and citation."""
        chunk_id = f"{doc_id}#{chunk_index}"
        return cls(
            chunk_id=chunk_id,
            point_id=make_point_id(chunk_id),
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            text=text,
            doc_id=doc_id,
            folder_id=folder_id,
            conversation_id=conversation_id,
            filename=filename,
            headings=headings,
            pages=pages,
            citation=render_citation(filename, pages, headings),
            chunk_index=chunk_index,
            chunk_total=chunk_total,
            token_count=token_count,
            char_count=len(text),
        )

    def to_payload(self, *, namespace: str = NAMESPACE) -> dict[str, Any]:
        """Flatten into a vector-store payload.

        The five keys the indexing and retrieval layers read by name come first;
        everything after them is specific to this source and reaches callers
        through ``RetrievedChunk.payload``.
        """
        payload: dict[str, Any] = {
            "namespace": namespace,
            "content_hash": self.content_hash,
            "chunk_id": self.chunk_id,
            "citation": self.citation,
            "text": self.text,
            "doc_id": self.doc_id,
            "filename": self.filename,
            "headings": self.headings,
            "pages": self.pages,
            "chunk_index": self.chunk_index,
            "chunk_total": self.chunk_total,
            "token_count": self.token_count,
            "char_count": self.char_count,
        }
        # Omitted rather than null for an in-chat file: a MatchValue filter on
        # folder_id should not have to know about a null sentinel.
        if self.folder_id is not None:
            payload["folder_id"] = self.folder_id
        if self.conversation_id is not None:
            payload["conversation_id"] = self.conversation_id
        return payload


def render_citation(filename: str, pages: list[int], headings: list[str]) -> str:
    """``dodatek.pdf, s. 4–6 – Odstoupení od smlouvy``, skipping absent parts.

    The innermost heading is used, because it is the most specific description
    of what the chunk is about.
    """
    citation = filename
    if pages:
        first, last = min(pages), max(pages)
        citation = f"{citation}, s. {first}" if first == last else f"{citation}, s. {first}–{last}"
    if headings:
        citation = f"{citation} – {headings[-1]}"
    return citation
