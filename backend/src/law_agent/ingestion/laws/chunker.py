"""Structure-aware chunking of Czech laws for retrieval.

Strategy, in one paragraph: the section (``§``) is the anchor, because it is the
unit lawyers cite. A section that fits the token budget becomes exactly one
chunk, so the common case keeps its full context. A section that does not fit is
split along its own structure -- paragraphs (``odstavce``), then letters, then
points -- and every split repeats the enclosing lead-in text, because
"a) pozbyl-li zaměstnanec..." is meaningless without "(1) Zaměstnavatel je
povinen převést zaměstnance na jinou práci". Only when a single leaf is still
too large does the text get split by sentences, with overlap. Very short
untitled sections are packed together, but a heading always starts a new chunk,
because a titled section is a self-contained topic. Every chunk is prefixed with
a contextual header (law, breadcrumb, section heading) which is embedded
together with the body.

The algorithm never hard-codes the law's shape: it recurses on whatever nesting
the document happens to have, so it works for a 350-fragment law and a
3000-fragment code alike.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field

from law_agent.ingestion.identity import make_point_id
from law_agent.ingestion.laws.document import LawDocument
from law_agent.ingestion.laws.models import LawChunk, Node
from law_agent.ingestion.laws.taxonomy import Role
from law_agent.ingestion.text import hard_wrap, split_sentences
from law_agent.ingestion.tokenizer import TokenCounter, default_token_counter

# Room reserved in the budget for the per-chunk header suffix (unit range and
# "(část i/n)" marker), which is only known after planning.
_HEADER_SUFFIX_ALLOWANCE = 24

# Never plan against a body budget smaller than this; below it, repeated lead-in
# context is trimmed instead of shrinking the body to nothing.
_MIN_BODY_BUDGET = 48

# Fraction of the budget the repeated lead-in may occupy before it is trimmed.
_MAX_LEAD_SHARE = 0.6

# Fraction of the budget above which the header drops its breadcrumb line.
_MAX_HEADER_SHARE = 0.4


class FootnoteMode(StrEnum):
    """How footnotes (``PPC``) enter the index."""

    METADATA = "metadata"
    """Attach resolved footnotes to referencing chunks as metadata (default)."""

    INLINE = "inline"
    """Additionally append footnote texts to the chunk body."""

    SEPARATE = "separate"
    """Emit footnotes as their own chunks."""

    IGNORE = "ignore"
    """Drop footnotes entirely."""


class ChunkingConfig(BaseModel):
    """Chunking policy. Every knob is safe to tune per deployment."""

    max_tokens: int = Field(default=768, ge=64)
    """Upper bound on a chunk, header included. 768 keeps roughly 90% of
    sections whole while staying in the range where dense retrieval performs
    best."""

    min_tokens: int = Field(default=120, ge=0)
    """Chunks below this are candidates for merging with an adjacent section."""

    hard_max_tokens: int = Field(default=8192, ge=64)
    """Embedding model context limit; validation flags anything above it."""

    merge_small_sections: bool = True
    """Pack adjacent short sections sharing a parent into one chunk."""

    include_frontmatter: bool = False
    """Index the preamble and signature blocks (rarely useful for retrieval)."""

    include_annexes: bool = True
    footnote_mode: FootnoteMode = FootnoteMode.METADATA

    overlap_sentences: int = Field(default=1, ge=0)
    """Sentences repeated between consecutive pieces of a forced text split.
    Structural splits use repeated lead-in context instead, which is stronger."""

    include_breadcrumb_header: bool = True
    namespace: str = "laws"

    # Document divisions never indexed as body text.
    excluded_parts: tuple[str, ...] = ("postfix",)


@dataclass(slots=True)
class _Piece:
    """A planned chunk, before rendering."""

    lead: list[Node]
    """Ancestor chain inside the anchor whose own text is repeated as context."""

    body: list[Node]
    """Sibling nodes rendered in full (own text plus descendants)."""

    text: str | None = None
    """Set only for forced sentence-level splits, replacing the rendered body."""


@dataclass(slots=True)
class _SectionPlan:
    anchors: list[Node]
    pieces: list[_Piece]
    header_context: str
    header_tokens: int


@dataclass(slots=True)
class ChunkingStats:
    """Aggregate counters, for tests, CLI output and regression tracking."""

    chunks: int = 0
    sections: int = 0
    merged_sections: int = 0
    forced_text_splits: int = 0
    oversized: int = 0
    token_counts: list[int] = field(default_factory=list)

    def summary(self) -> dict[str, float | int]:
        counts = sorted(self.token_counts)
        if not counts:
            return {"chunks": 0}

        def pct(fraction: float) -> int:
            return counts[min(len(counts) - 1, int(len(counts) * fraction))]

        return {
            "chunks": self.chunks,
            "sections": self.sections,
            "merged_sections": self.merged_sections,
            "forced_text_splits": self.forced_text_splits,
            "oversized": self.oversized,
            "tokens_min": counts[0],
            "tokens_p50": pct(0.50),
            "tokens_p90": pct(0.90),
            "tokens_p99": pct(0.99),
            "tokens_max": counts[-1],
            "tokens_mean": round(sum(counts) / len(counts), 1),
        }


class LawChunker:
    """Turns a :class:`LawDocument` into :class:`LawChunk` objects.

    Stateless with respect to documents -- one instance can chunk many laws.
    """

    def __init__(
        self,
        config: ChunkingConfig | None = None,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self.config = config or ChunkingConfig()
        self.count_tokens = token_counter or default_token_counter()

    # ------------------------------------------------------------------ public

    def chunk(self, document: LawDocument) -> list[LawChunk]:
        """Chunk ``document``; see :meth:`chunk_with_stats` for counters."""
        chunks, _ = self.chunk_with_stats(document)
        return chunks

    def chunk_with_stats(self, document: LawDocument) -> tuple[list[LawChunk], ChunkingStats]:
        stats = ChunkingStats()
        self._subtree_cache: dict[str, str] = {}
        self._document = document

        plans = [self._plan_section(document, anchor) for anchor in self._iter_anchors(document)]
        stats.sections = len(plans)

        if self.config.merge_small_sections:
            plans = self._merge_small(document, plans, stats)

        chunks: list[LawChunk] = []
        for plan in plans:
            chunks.extend(self._render(document, plan, stats))

        if self.config.footnote_mode is FootnoteMode.SEPARATE:
            chunks.extend(self._render_footnotes(document, stats))

        stats.chunks = len(chunks)
        return chunks, stats

    # ------------------------------------------------------------- anchoring

    def _iter_anchors(self, document: LawDocument) -> Iterator[Node]:
        """Yield the nodes that anchor chunks, in document order.

        A ``SECTION`` is atomic. Containers are descended into while they still
        contain sections; a container holding text but no sections (a preamble,
        an annex body) becomes its own anchor, so no text is ever dropped.
        """
        yield from self._iter_anchors_in(document, document.root)

    def _iter_anchors_in(self, document: LawDocument, node: Node) -> Iterator[Node]:
        if not self._is_included(document, node):
            return
        if node.role is Role.SECTION:
            yield node
            return
        # A leaf heading is a pure label: its text already reaches the index
        # through the header and breadcrumb of the sections it titles, so
        # anchoring it would only add a near-empty duplicate chunk. Headings
        # that nest content (annexes) still anchor.
        if node.role is Role.HEADING and not node.children:
            return
        if self._has_section_descendant(node):
            for child in node.children:
                yield from self._iter_anchors_in(document, child)
            return
        if self._subtree_text(document, node).strip():
            yield node

    def _is_included(self, document: LawDocument, node: Node) -> bool:
        config = self.config
        part = document.part_of(node)
        if part in config.excluded_parts:
            return False
        if part == "poznamkypodcarou":
            return False  # handled by footnote_mode
        if part in {"prefix", "postfix"} and not config.include_frontmatter:
            return False
        if part == "prilohy" and not config.include_annexes:
            return False
        return node.role not in {Role.SKIP, Role.FOOTNOTE, Role.DOC_META}

    @staticmethod
    def _has_section_descendant(node: Node) -> bool:
        return any(
            child.role is Role.SECTION or LawChunker._has_section_descendant(child)
            for child in node.children
        )

    # -------------------------------------------------------------- rendering

    def _own_text(self, node: Node) -> str:
        """Text contributed by ``node`` itself, excluding descendants."""
        if node.role is Role.TEXT:
            return node.content
        if node.role is Role.HEADING:
            return (node.heading or node.content).strip()
        return ""  # containers and sections are labels, rendered in the header

    def _body_children(self, document: LawDocument, node: Node) -> list[Node]:
        """Children contributing body text, excluding ``node``'s own headings."""
        own = {h.fragment_id for h in document.own_headings(node)}
        return [
            child
            for child in node.children
            if child.fragment_id not in own
            and child.role not in {Role.SKIP, Role.FOOTNOTE, Role.DOC_META}
            and self._is_included(document, child)
        ]

    def _subtree_text(self, document: LawDocument, node: Node) -> str:
        cached = self._subtree_cache.get(node.fragment_id)
        if cached is not None:
            return cached
        parts = [self._own_text(node)]
        parts.extend(
            self._subtree_text(document, child) for child in self._body_children(document, node)
        )
        rendered = "\n".join(p for p in parts if p)
        self._subtree_cache[node.fragment_id] = rendered
        return rendered

    def _lead_text(self, lead: list[Node]) -> list[str]:
        return [text for node in lead if (text := self._own_text(node))]

    # ---------------------------------------------------------------- planning

    def _plan_section(self, document: LawDocument, anchor: Node) -> _SectionPlan:
        header_context, header_tokens = self._build_header(document, anchor, anchor.designation)
        budget = max(_MIN_BODY_BUDGET, self.config.max_tokens - header_tokens)
        pieces = self._plan_node(document, anchor, lead=[], budget=budget)
        return _SectionPlan(
            anchors=[anchor],
            pieces=pieces,
            header_context=header_context,
            header_tokens=header_tokens,
        )

    def _build_header(
        self,
        document: LawDocument,
        anchor: Node,
        section_label: str | None,
    ) -> tuple[str, int]:
        """Render the header and its token cost, shrinking it if it is too fat.

        At small budgets a deep breadcrumb crowds out the body; the law and
        section lines are the part that must survive.
        """
        context = self._header_context(document, anchor, section_label)
        tokens = self.count_tokens(context) + _HEADER_SUFFIX_ALLOWANCE
        if tokens > self.config.max_tokens * _MAX_HEADER_SHARE:
            context = self._header_context(document, anchor, section_label, breadcrumb=False)
            tokens = self.count_tokens(context) + _HEADER_SUFFIX_ALLOWANCE
        return context, tokens

    def _plan_node(
        self,
        document: LawDocument,
        node: Node,
        *,
        lead: list[Node],
        budget: int,
    ) -> list[_Piece]:
        """Recursively split ``node`` so each piece fits ``budget``.

        ``lead`` is the chain of enclosing nodes whose own text is repeated into
        every piece, which is what keeps split fragments legally readable.
        """
        lead = self._trim_lead(lead, budget)
        lead_texts = self._lead_text(lead)

        if self._fits([*lead_texts, self._subtree_text(document, node)], budget):
            return [_Piece(lead=lead, body=[node])]

        children = self._body_children(document, node)
        if not children:
            return self._split_text(document, node, lead=lead, budget=budget)

        inner_lead = self._trim_lead([*lead, node], budget)
        inner_texts = self._lead_text(inner_lead)
        pieces: list[_Piece] = []
        buffer: list[Node] = []

        # If this node's own lead-in text was too large to repeat and got
        # trimmed away, it still has to be indexed somewhere -- emit it as its
        # own piece rather than losing it.
        own_text = self._own_text(node)
        if own_text and not any(n is node for n in inner_lead):
            pieces.extend(
                self._split_text(document, node, lead=inner_lead, budget=budget, text=own_text)
            )

        def flush() -> None:
            nonlocal buffer
            if buffer:
                pieces.append(_Piece(lead=inner_lead, body=buffer))
                buffer = []

        for child in children:
            child_text = self._subtree_text(document, child)
            candidate = [
                *inner_texts,
                *(self._subtree_text(document, b) for b in buffer),
                child_text,
            ]
            if buffer and self._fits(candidate, budget):
                buffer.append(child)
                continue
            if not buffer and self._fits([*inner_texts, child_text], budget):
                buffer.append(child)
                continue
            flush()
            if self._fits([*inner_texts, child_text], budget):
                buffer.append(child)
            else:
                pieces.extend(self._plan_node(document, child, lead=inner_lead, budget=budget))
        flush()
        return pieces or [_Piece(lead=lead, body=[node])]

    def _trim_lead(self, lead: list[Node], budget: int) -> list[Node]:
        """Drop outer lead-in context when repeating it would starve the body.

        Trims all the way to nothing if it must: a lead-in longer than the
        budget cannot be repeated, and the chunk header still carries the
        citation that identifies where the text sits.
        """
        while (
            lead and self.count_tokens("\n".join(self._lead_text(lead))) > budget * _MAX_LEAD_SHARE
        ):
            lead = lead[1:]
        return lead

    def _fits(self, parts: list[str], budget: int) -> bool:
        return self.count_tokens("\n".join(p for p in parts if p)) <= budget

    def _split_text(
        self,
        document: LawDocument,
        node: Node,
        *,
        lead: list[Node],
        budget: int,
        text: str | None = None,
    ) -> list[_Piece]:
        """Last resort: split one node's text on sentence boundaries.

        ``text`` defaults to the node's whole rendered subtree; callers pass it
        explicitly to split just the node's own lead-in text.
        """
        text = text if text is not None else self._subtree_text(document, node)
        lead_texts = self._lead_text(lead)
        available = max(_MIN_BODY_BUDGET, budget - self.count_tokens("\n".join(lead_texts)))

        sentences = split_sentences(text)
        groups: list[list[str]] = []
        current: list[str] = []
        for sentence in sentences:
            candidate = [*current, sentence]
            if current and self.count_tokens(" ".join(candidate)) > available:
                groups.append(current)
                overlap = (
                    current[-self.config.overlap_sentences :]
                    if self.config.overlap_sentences
                    else []
                )
                # Overlap is a nicety; drop it rather than blow the budget.
                if overlap and self.count_tokens(" ".join([*overlap, sentence])) > available:
                    overlap = []
                current = [*overlap, sentence]
            else:
                current = candidate
        if current:
            groups.append(current)

        # A single sentence longer than the budget must still be broken up.
        expanded: list[str] = []
        for group in groups:
            joined = " ".join(group)
            if self.count_tokens(joined) <= available:
                expanded.append(joined)
            else:
                expanded.extend(hard_wrap(joined, available, self.count_tokens))

        return [_Piece(lead=lead, body=[node], text=chunk_text) for chunk_text in expanded]

    # ----------------------------------------------------------------- merging

    def _merge_small(
        self,
        document: LawDocument,
        plans: list[_SectionPlan],
        stats: ChunkingStats,
    ) -> list[_SectionPlan]:
        """Pack adjacent single-piece sections that are too small to stand alone.

        Only untitled sections sharing a parent container (hence the same
        breadcrumb) are merged, so the citation stays a contiguous, meaningful
        range and no section loses its own heading.
        """
        merged: list[_SectionPlan] = []
        for plan in plans:
            previous = merged[-1] if merged else None
            if previous is not None and self._can_merge(document, previous, plan):
                previous.anchors.extend(plan.anchors)
                previous.pieces[0].body.extend(plan.pieces[0].body)
                previous.header_context, previous.header_tokens = self._build_header(
                    document,
                    previous.anchors[0],
                    self._range_label([a.designation or "" for a in previous.anchors]),
                )
                stats.merged_sections += 1
                continue
            merged.append(plan)
        return merged

    def _can_merge(self, document: LawDocument, left: _SectionPlan, right: _SectionPlan) -> bool:
        if len(left.pieces) != 1 or len(right.pieces) != 1:
            return False
        if left.pieces[0].text is not None or right.pieces[0].text is not None:
            return False
        # Only true sections merge: a range citation over anything else would
        # not name a unit a reader can look up.
        if not all(a.role is Role.SECTION for a in (*left.anchors, *right.anchors)):
            return False
        if left.anchors[-1].parent is not right.anchors[0].parent:
            return False
        if document.part_of(left.anchors[0]) != document.part_of(right.anchors[0]):
            return False
        if document.group_heading(left.anchors[-1]) != document.group_heading(right.anchors[0]):
            return False
        # A titled section starts a new chunk. Its heading names a self-contained
        # topic, and the merged header is built from the first anchor alone --
        # so merging would either bury the title or stretch one section's title
        # over its untitled neighbours.
        if any(document.heading_text(a) for a in (*left.anchors, *right.anchors)):
            return False

        if (
            min(
                self._piece_tokens(document, left.pieces[0]),
                self._piece_tokens(document, right.pieces[0]),
            )
            >= self.config.min_tokens
        ):
            return False

        # Measure the real merged body: merging adds inline section labels that
        # an estimate from the two halves would miss.
        candidate = _Piece(lead=[], body=[*left.pieces[0].body, *right.pieces[0].body])
        header = max(left.header_tokens, right.header_tokens)
        return self._piece_tokens(document, candidate) + header <= self.config.max_tokens

    def _piece_tokens(self, document: LawDocument, piece: _Piece) -> int:
        return self.count_tokens(self._piece_body(document, piece))

    # --------------------------------------------------------------- rendering

    def _piece_body(self, document: LawDocument, piece: _Piece) -> str:
        if piece.text is not None:
            return "\n".join([*self._lead_text(piece.lead), piece.text])

        # When several sections share a chunk their designations are no longer
        # implied by the header, so each one is labelled inline.
        label_sections = sum(node.role is Role.SECTION for node in piece.body) > 1
        parts = list(self._lead_text([n for n in piece.lead if n.role is not Role.SECTION]))
        for node in piece.body:
            rendered = self._subtree_text(document, node)
            if not rendered:
                continue
            if label_sections and node.role is Role.SECTION:
                heading = document.heading_text(node)
                label = f"{node.label} – {heading}" if heading else node.label
                rendered = f"{label}\n{rendered}"
            parts.append(rendered)
        return "\n".join(p for p in parts if p)

    def _render(
        self,
        document: LawDocument,
        plan: _SectionPlan,
        stats: ChunkingStats,
    ) -> list[LawChunk]:
        anchor = plan.anchors[0]
        part = document.part_of(anchor)
        breadcrumb = document.breadcrumb(anchor)
        group_heading = document.group_heading(anchor)
        section = self._range_label([a.designation or a.label for a in plan.anchors]) or None
        total = len(plan.pieces)
        chunks: list[LawChunk] = []

        for index, piece in enumerate(plan.pieces, start=1):
            if piece.text is not None:
                stats.forced_text_splits += 1

            body = self._piece_body(document, piece)
            if not body.strip():
                continue

            unit_suffix = self._unit_suffix(document, plan, piece)
            header = plan.header_context
            if unit_suffix:
                header = f"{header}, {unit_suffix}"
            if total > 1:
                header = f"{header} (část {index}/{total})"

            footnotes = (
                document.footnote_refs(body)
                if self.config.footnote_mode is not FootnoteMode.IGNORE
                else {}
            )
            if footnotes and self.config.footnote_mode is FootnoteMode.INLINE:
                notes = "\n".join(f"{marker} {text}" for marker, text in footnotes.items())
                body = f"{body}\n\nPoznámky pod čarou:\n{notes}"

            text = f"{header}\n\n{body}"
            token_count = self.count_tokens(text)
            if token_count > self.config.max_tokens:
                stats.oversized += 1
            stats.token_counts.append(token_count)

            source_nodes = self._source_nodes(document, piece)
            source_ids = [n.fragment_id for n in source_nodes]
            positions = [n.position for n in source_nodes] or [anchor.position]
            citation = self._citation(document, plan, unit_suffix)

            chunk_id = _chunk_id(
                document.metadata.law_id, part, anchor.fragment_id, source_ids, index
            )
            chunks.append(
                LawChunk(
                    chunk_id=chunk_id,
                    point_id=make_point_id(chunk_id),
                    content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:32],
                    text=text,
                    header=header,
                    body=body,
                    law=document.metadata,
                    part=part,
                    citation=citation,
                    section=section,
                    anchor_fragment_id=anchor.fragment_id,
                    breadcrumb=breadcrumb,
                    group_heading=group_heading,
                    source_fragment_ids=source_ids,
                    position_start=min(positions),
                    position_end=max(positions),
                    chunk_index=index,
                    chunk_total=total,
                    token_count=token_count,
                    char_count=len(text),
                    is_effective=all(n.fragment.is_effective for n in source_nodes)
                    if source_nodes
                    else True,
                    is_repealed=any(n.fragment.is_repealed for n in source_nodes),
                    is_amended=any(n.fragment.is_amended for n in source_nodes),
                    footnotes=footnotes
                    if self.config.footnote_mode is FootnoteMode.METADATA
                    else {},
                )
            )
        return chunks

    def _source_nodes(self, document: LawDocument, piece: _Piece) -> list[Node]:
        """Fragments whose text is genuinely present in this piece.

        For text-replaced pieces only the node itself is claimed -- its
        descendants are rendered in sibling pieces, and over-claiming here would
        make the coverage check blind to lost content.
        """
        seen: dict[str, Node] = {node.fragment_id: node for node in piece.lead}
        for node in piece.body:
            if piece.text is not None:
                seen[node.fragment_id] = node
                continue
            for descendant in node.walk():
                if self._is_included(document, descendant):
                    seen[descendant.fragment_id] = descendant
        return sorted(seen.values(), key=lambda n: n.position)

    def _header_context(
        self,
        document: LawDocument,
        anchor: Node,
        section_label: str | None,
        *,
        breadcrumb: bool = True,
    ) -> str:
        lines = [document.metadata.render_header()]
        if breadcrumb and self.config.include_breadcrumb_header:
            trail = [entry.render() for entry in document.breadcrumb(anchor)]
            group = document.group_heading(anchor)
            if group:
                trail.append(group)
            if trail:
                lines.append(" > ".join(trail))

        section_line = section_label or anchor.label
        heading = document.heading_text(anchor)
        if heading:
            section_line = f"{section_line} – {heading}"
        lines.append(section_line)
        return "\n".join(lines)

    def _unit_suffix(self, document: LawDocument, plan: _SectionPlan, piece: _Piece) -> str:
        """``odst. 1 až 3`` -- which sub-units of the section this chunk holds."""
        if len(plan.pieces) == 1 and piece.text is None and piece.body == plan.anchors:
            return ""

        path = [document.unit_label(n) for n in piece.lead if n.role is not Role.SECTION]
        body_labels = [label for n in piece.body if (label := document.unit_label(n))]
        parts = [*[p for p in path if p], self._range_label(body_labels)]
        return " ".join(p for p in parts if p)

    def _citation(self, document: LawDocument, plan: _SectionPlan, unit_suffix: str) -> str:
        anchor_labels = [document.unit_label(a) or a.label for a in plan.anchors]
        base = self._range_label(anchor_labels)
        law = document.metadata.citation_label
        reference = " ".join(p for p in (base, unit_suffix) if p)
        if not reference:
            return law
        # Annex headers already spell out the law ("Příloha k zákonu č. 262/2006 Sb.").
        # Match on the number, because the wording around it is inflected.
        metadata = document.metadata
        if metadata.number and metadata.year and f"{metadata.number}/{metadata.year}" in reference:
            return reference
        return f"{reference} {law}"

    @staticmethod
    def _range_label(labels: list[str]) -> str:
        """``["odst. 1", "odst. 2", "odst. 3"]`` -> ``odst. 1 až 3``."""
        clean = [label for label in labels if label]
        if not clean:
            return ""
        if len(clean) == 1:
            return clean[0]
        first, last = clean[0], clean[-1]
        kind = first.rsplit(" ", 1)[0] if " " in first else ""
        if kind and last.startswith(f"{kind} "):
            last = last[len(kind) + 1 :]
        return f"{first} až {last}"

    def _render_footnotes(self, document: LawDocument, stats: ChunkingStats) -> list[LawChunk]:
        chunks: list[LawChunk] = []
        law = document.metadata
        for order, (marker, text) in enumerate(document.footnotes.items(), start=1):
            header = f"{law.render_header()}\npoznámka pod čarou {marker}"
            full = f"{header}\n\n{text}"
            token_count = self.count_tokens(full)
            stats.token_counts.append(token_count)
            chunk_id = _chunk_id(law.law_id, "poznamkypodcarou", f"ppc/{marker}", [marker], order)
            chunks.append(
                LawChunk(
                    chunk_id=chunk_id,
                    point_id=make_point_id(chunk_id),
                    content_hash=hashlib.sha256(full.encode("utf-8")).hexdigest()[:32],
                    text=full,
                    header=header,
                    body=text,
                    law=law,
                    part="poznamkypodcarou",
                    citation=f"pozn. pod čarou {marker} {law.citation_label}",
                    section=None,
                    anchor_fragment_id=f"{law.law_id}/dokument/poznamkypodcarou/{marker}",
                    breadcrumb=[],
                    source_fragment_ids=[marker],
                    position_start=order,
                    position_end=order,
                    chunk_index=1,
                    chunk_total=1,
                    token_count=token_count,
                    char_count=len(full),
                )
            )
        return chunks


# ------------------------------------------------------------------- utilities


def _chunk_id(law_id: str, part: str, anchor: str, source_ids: list[str], index: int) -> str:
    """Deterministic, content-independent chunk identity.

    Stable across runs and across content edits, so re-ingesting an amended law
    updates the same rows instead of duplicating them. Content changes are
    detected via :attr:`LawChunk.content_hash`.
    """
    first = source_ids[0] if source_ids else anchor
    last = source_ids[-1] if source_ids else anchor
    key = f"{law_id}|{part}|{anchor}|{first}|{last}|{index}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def chunk_law(
    source: str | LawDocument,
    *,
    config: ChunkingConfig | None = None,
    token_counter: TokenCounter | None = None,
) -> list[LawChunk]:
    """Convenience entry point: chunk a law from a JSON path or a parsed document."""
    document = LawDocument.from_json(source) if isinstance(source, str) else source
    return LawChunker(config=config, token_counter=token_counter).chunk(document)
