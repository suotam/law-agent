"""Shared test factories for the objects real ingestion is expensive to produce.

LawChunk carries a lot of provenance/citation fields that real ingestion fills
in from the document tree; tests that only care about indexing/retrieval
behavior don't need real fragments, just a valid LawChunk with sensible
defaults. The same applies to a parsed DoclingDocument, which would otherwise
require a running container.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel

from law_agent.ingestion import make_point_id
from law_agent.ingestion.laws.models import BreadcrumbEntry, LawChunk, LawMetadata


@dataclass(frozen=True, slots=True)
class FileLikeChunk:
    """A chunk from a source that knows nothing about laws.

    Stands in for the future file-backed chunk (org_files / user_files). It
    exists to prove that indexing and retrieval accept a chunk they cannot
    import and that carries no law metadata -- which is the whole point of
    ``ChunkLike``.
    """

    point_id: str
    content_hash: str
    text: str
    chunk_id: str
    file_name: str
    doc_id: str = "smernice.pdf"
    """Identity of the source document; what orphan pruning is scoped by."""
    folder_id: str | None = None

    def to_payload(self, *, namespace: str) -> dict[str, Any]:
        payload = {
            "namespace": namespace,
            "content_hash": self.content_hash,
            "chunk_id": self.chunk_id,
            "citation": f"{self.file_name}, s. 1",
            "text": self.text,
            "file_name": self.file_name,
            "doc_id": self.doc_id,
        }
        if self.folder_id is not None:
            payload["folder_id"] = self.folder_id
        return payload


def make_file_like_chunk(
    chunk_id: str,
    text: str,
    *,
    file_name: str = "smernice.pdf",
    doc_id: str = "smernice.pdf",
    folder_id: str | None = None,
) -> FileLikeChunk:
    return FileLikeChunk(
        point_id=make_point_id(chunk_id),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:32],
        text=text,
        chunk_id=chunk_id,
        file_name=file_name,
        doc_id=doc_id,
        folder_id=folder_id,
    )


_LAW = LawMetadata(
    law_id="/eli/cz/sb/2006/262/2026-01-01",
    number="262",
    year=2006,
    title="zákoník práce",
    version_date="2026-01-01",
)


def make_chunk(
    chunk_id: str,
    text: str,
    *,
    citation: str = "§ 1",
    section: str = "§ 1",
    law: LawMetadata = _LAW,
) -> LawChunk:
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
    return LawChunk(
        chunk_id=chunk_id,
        point_id=make_point_id(chunk_id),
        content_hash=content_hash,
        text=text,
        header=law.render_header(),
        body=text,
        law=law,
        part="norma",
        citation=citation,
        section=section,
        anchor_fragment_id=f"{law.law_id}/{chunk_id}",
        breadcrumb=[BreadcrumbEntry(type="Cast", designation="Část první")],
        source_fragment_ids=[f"{law.law_id}/{chunk_id}"],
        position_start=0,
        position_end=0,
        chunk_index=1,
        chunk_total=1,
        token_count=max(1, len(text.split())),
        char_count=len(text),
    )


def make_docling_document(name: str = "dodatek") -> DoclingDocument:
    """A tiny parsed document with two headed sections.

    Built programmatically rather than captured from docling-serve, so chunker
    tests need neither a running container nor a binary fixture. Items carry no
    provenance, which is why chunks built from it have no page numbers.
    """
    document = DoclingDocument(name=name)

    document.add_heading(text="Odstoupení od smlouvy")
    document.add_text(
        label=DocItemLabel.TEXT,
        text=(
            "Smluvní strany se dohodly na možnosti odstoupit od této smlouvy "
            "písemným oznámením doručeným druhé straně."
        ),
    )

    document.add_heading(text="Závěrečná ustanovení")
    document.add_text(
        label=DocItemLabel.TEXT,
        text="Tato smlouva nabývá účinnosti dnem podpisu oběma smluvními stranami.",
    )

    return document
