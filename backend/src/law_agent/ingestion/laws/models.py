"""Data models for law ingestion: raw fragments, the parsed tree, and chunks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from law_agent.ingestion.laws.taxonomy import Role

NAMESPACE = "laws"


class Fragment(BaseModel):
    """One raw fragment as returned by the ceskezakony.cz fragments endpoint.

    ``extra="allow"`` keeps forward compatibility with new API fields, and
    ``frozen=True`` lets fragments be shared freely across the tree.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    id: int
    fragment_id: str
    position: int
    type: str
    depth: int
    designation: str | None = None
    heading: str | None = None
    content: str | None = None
    is_repealed: bool = False
    is_effective: bool = True
    is_amended: bool = False
    parent_fragment_id: str | None = None


@dataclass(slots=True, eq=False)
class Node:
    """A fragment placed in the document tree.

    Compared by identity (``eq=False``): a generated ``__eq__`` would recurse
    through ``parent`` and ``children``.

    The API always returns ``parent_fragment_id = null``, so parentage is
    reconstructed from ``depth`` + ``position`` (see
    :func:`law_agent.ingestion.laws.document.build_tree`).
    """

    fragment: Fragment
    role: Role
    parent: Node | None = field(default=None, repr=False)
    children: list[Node] = field(default_factory=list)

    @property
    def fragment_id(self) -> str:
        return self.fragment.fragment_id

    @property
    def type(self) -> str:
        return self.fragment.type

    @property
    def position(self) -> int:
        return self.fragment.position

    @property
    def designation(self) -> str | None:
        return self.fragment.designation

    @property
    def heading(self) -> str | None:
        return self.fragment.heading

    @property
    def content(self) -> str:
        return (self.fragment.content or "").strip()

    @property
    def label(self) -> str:
        """Short human label: designation, else heading, else content, else type."""
        return (self.designation or self.heading or self.content or self.type).strip()

    def walk(self) -> list[Node]:
        """This node followed by all descendants, in document order."""
        out: list[Node] = [self]
        for child in self.children:
            out.extend(child.walk())
        return out


class BreadcrumbEntry(BaseModel):
    """One level of structural context above a chunk (part, chapter, ...)."""

    model_config = ConfigDict(frozen=True)

    type: str
    designation: str | None = None
    heading: str | None = None

    def render(self) -> str:
        parts = [p for p in (self.designation, self.heading) if p]
        return " – ".join(parts) or self.type


class LawMetadata(BaseModel):
    """Document-level metadata, extracted from the ELI id and the front matter."""

    model_config = ConfigDict(frozen=True)

    law_id: str
    """ELI identifier of this consolidated version, e.g.
    ``/eli/cz/sb/2006/262/2026-01-01``."""

    number: str | None = None
    year: int | None = None
    version_date: str | None = None
    kind: str | None = None
    title: str | None = None
    enacted_on: str | None = None

    @property
    def citation_label(self) -> str:
        """``zákon č. 262/2006 Sb.``-style label used in chunk headers."""
        kind = (self.kind or "zákon").lower()
        if self.number and self.year:
            return f"{kind} č. {self.number}/{self.year} Sb."
        return kind

    def render_header(self) -> str:
        line = self.citation_label
        if self.title:
            line = f"{line} – {self.title}"
        if self.version_date:
            line = f"{line} (znění k {self.version_date})"
        return line


class LawChunk(BaseModel):
    """A retrieval unit from a law: embeddable text plus everything needed to
    cite it.

    Named for its source, because other sources (org and user files) produce
    differently shaped chunks. What every indexable chunk must expose is
    declared by ``law_agent.indexing.protocols.ChunkLike``, which this class
    satisfies structurally -- there is deliberately no inheritance link.
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    """Deterministic, content-independent identity. Stable across re-ingestion
    so that an amended law updates rows in place."""

    point_id: str
    """UUID derived from :attr:`chunk_id`, usable directly as a Qdrant point id."""

    content_hash: str
    """Hash of :attr:`text`; lets ingestion skip re-embedding unchanged chunks."""

    text: str
    """What gets embedded: contextual header + body."""

    header: str
    body: str

    law: LawMetadata
    part: str
    """Top-level document division: ``norma``, ``zaver``, ``prilohy``, ..."""

    citation: str
    """Human-readable legal citation, e.g. ``§ 41 odst. 1 písm. a) až c)``."""

    section: str | None
    """Designation of the anchoring section, e.g. ``§ 41``."""

    anchor_fragment_id: str
    breadcrumb: list[BreadcrumbEntry]
    group_heading: str | None = None

    source_fragment_ids: list[str]
    """Every fragment whose text is present in :attr:`body` (provenance and
    coverage checks)."""

    position_start: int
    position_end: int
    """Source ``position`` range; used for ordering and neighbour expansion."""

    chunk_index: int
    chunk_total: int
    """Position within the anchoring section, 1-based."""

    token_count: int
    char_count: int

    is_effective: bool = True
    is_repealed: bool = False
    is_amended: bool = False

    footnotes: dict[str, str] = {}
    """Footnote marker -> text, for markers referenced from this chunk."""

    def to_payload(
        self, *, namespace: str = NAMESPACE, include_footnotes: bool = True
    ) -> dict[str, Any]:
        """Flatten into a vector-store payload.

        Nested objects are flattened to scalars and lists so that any vector
        database can index and filter on them.
        """
        payload: dict[str, Any] = {
            "namespace": namespace,
            "chunk_id": self.chunk_id,
            "content_hash": self.content_hash,
            "text": self.text,
            "body": self.body,
            "law_id": self.law.law_id,
            "law_number": self.law.number,
            "law_year": self.law.year,
            "law_title": self.law.title,
            "law_version_date": self.law.version_date,
            "law_citation": self.law.citation_label,
            "part": self.part,
            "citation": self.citation,
            "section": self.section,
            "anchor_fragment_id": self.anchor_fragment_id,
            "breadcrumb": [entry.render() for entry in self.breadcrumb],
            "group_heading": self.group_heading,
            "source_fragment_ids": self.source_fragment_ids,
            "position_start": self.position_start,
            "position_end": self.position_end,
            "chunk_index": self.chunk_index,
            "chunk_total": self.chunk_total,
            "token_count": self.token_count,
            "char_count": self.char_count,
            "is_effective": self.is_effective,
            "is_repealed": self.is_repealed,
            "is_amended": self.is_amended,
        }
        if include_footnotes and self.footnotes:
            payload["footnote_markers"] = sorted(self.footnotes)
            payload["footnotes"] = self.footnotes
        return payload
