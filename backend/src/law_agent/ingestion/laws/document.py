"""Parsing a flat fragment list into a queryable :class:`LawDocument`."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from law_agent.ingestion.laws.models import BreadcrumbEntry, Fragment, LawMetadata, Node
from law_agent.ingestion.laws.taxonomy import Role, classify, is_known_type

# Trailing footnote markers such as the "1)" in "předpisy Evropské unie1)".
# The look-behind requires a non-opening, non-space character so that list
# markers ("a)") and paragraph designations ("(1)") are not mistaken for them.
# A digit is excluded too, otherwise the tail of a cross-reference is misread as
# a marker: "(§ 283 až 285)" would match "85)", which is a real footnote in the
# table and so would survive the resolution filter.
_FOOTNOTE_REF = re.compile(r"(?<=[^\s(\[\d])(\d{1,3}[a-z]?\))")

# fragment_id path segment prefix -> citation label.
_SEGMENT_LABELS: dict[str, str] = {
    "cast": "část",
    "hlava": "hlava",
    "dil": "díl",
    "oddil": "oddíl",
    "par": "§",
    "clanek": "čl.",
    "odst": "odst.",
    "pism": "písm.",
    "bod": "bod",
    "priloha": "příloha",
    "ppc": "pozn.",
}

_DOC_META_FIELDS = {
    "Prefix_Number": "number",
    "Prefix_Type": "kind",
    "Prefix_Date": "enacted_on",
    "Prefix_Title": "title",
}

_ELI_VERSION_RE = re.compile(r"/eli/[^/]+/[^/]+/(?P<year>\d{4})/(?P<number>[^/]+)/(?P<date>[^/]+)")


@dataclass(slots=True)
class ParseReport:
    """Diagnostics from parsing -- surfaced by the CLI and asserted in tests."""

    fragment_count: int = 0
    node_count: int = 0
    dropped_repealed: int = 0
    unknown_types: dict[str, int] = field(default_factory=dict)
    depth_gaps: int = 0
    """Number of fragments whose ``depth`` jumped by more than one, which the
    tree builder had to clamp."""


class LawDocument:
    """A parsed law: the fragment tree plus derived context.

    Holds everything the chunker needs that is *not* a chunking policy:
    metadata, structural breadcrumbs, heading attribution and footnotes.
    """

    def __init__(
        self,
        root: Node,
        *,
        metadata: LawMetadata,
        report: ParseReport,
    ) -> None:
        self.root = root
        self.metadata = metadata
        self.report = report
        self._nodes: dict[str, Node] = {n.fragment_id: n for n in root.walk()}
        self._own_headings: dict[str, list[Node]] = {}
        self._group_heading: dict[str, Node] = {}
        self._attribute_headings(root)
        self.footnotes: dict[str, str] = self._collect_footnotes()

    # ------------------------------------------------------------------ build

    @classmethod
    def from_fragments(
        cls,
        fragments: list[Fragment] | list[dict[str, Any]],
        *,
        include_repealed: bool = False,
    ) -> LawDocument:
        """Parse raw fragments (models or plain dicts) into a document."""
        parsed = [f if isinstance(f, Fragment) else Fragment.model_validate(f) for f in fragments]
        root, report = build_tree(parsed, include_repealed=include_repealed)
        return cls(root, metadata=extract_metadata(root), report=report)

    @classmethod
    def from_json(cls, path: str | Path, *, include_repealed: bool = False) -> LawDocument:
        """Parse a JSON file containing the fragment array."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, dict):  # tolerate {"data": [...]} envelopes
            raw = raw.get("data", raw.get("fragments", []))
        return cls.from_fragments(raw, include_repealed=include_repealed)

    # ------------------------------------------------------------- navigation

    def get(self, fragment_id: str) -> Node | None:
        return self._nodes.get(fragment_id)

    def own_headings(self, node: Node) -> list[Node]:
        """Heading children that title ``node`` itself.

        These are the leading heading children -- ``Nadpis_pod`` directly under
        a ``Paragraf`` or a ``Hlava``. They belong in the chunk header, not in
        the body, so the chunker excludes them from rendered text.
        """
        return self._own_headings.get(node.fragment_id, [])

    def heading_text(self, node: Node) -> str | None:
        """The joined text of ``node``'s own headings, if any."""
        parts = [
            h.heading or h.content for h in self.own_headings(node) if (h.heading or h.content)
        ]
        return " – ".join(parts) or None

    def group_heading(self, node: Node) -> str | None:
        """Heading that spans ``node`` and preceding siblings.

        ``Nadpis_nad`` appears *between* sections and titles the sections that
        follow it (e.g. "Převedení na jinou práci, pracovní cesta a přeložení"
        over §§ 41-43). It is context, not a parent, so it is tracked separately
        from the breadcrumb.
        """
        heading = self._group_heading.get(node.fragment_id)
        if heading is None:
            return None
        return heading.heading or heading.content or None

    def breadcrumb(self, node: Node) -> list[BreadcrumbEntry]:
        """Structural context above ``node``, outermost first.

        Skips the document root and transparent containers (``Virtual_*``,
        ``Block_*``) that carry neither designation nor heading.
        """
        chain: list[BreadcrumbEntry] = []
        current = node.parent
        while current is not None:
            if current.role is Role.CONTAINER:
                designation = current.designation or (
                    current.content
                    if current.content and current.content == current.designation
                    else None
                )
                heading = self.heading_text(current)
                if designation or heading:
                    chain.append(
                        BreadcrumbEntry(
                            type=current.type,
                            designation=designation or (current.content or None),
                            heading=heading,
                        )
                    )
            current = current.parent
        chain.reverse()
        return chain

    def part_of(self, node: Node) -> str:
        """Top-level division of a node: ``norma``, ``zaver``, ``prilohy``, ...

        Derived from the ``fragment_id`` path so it is independent of how many
        container levels a particular law happens to use.
        """
        segments = node.fragment_id.strip("/").split("/")
        try:
            index = segments.index("dokument")
        except ValueError:
            return "norma"
        return segments[index + 1] if index + 1 < len(segments) else "dokument"

    # ------------------------------------------------------------- citations

    def unit_label(self, node: Node) -> str:
        """``§ 41``, ``odst. 1``, ``písm. a)``.

        The *kind* comes from the ``fragment_id`` path segment and the *number*
        from ``designation``, because designations alone are ambiguous: ``(1)``
        is a paragraph, ``a)`` a letter and ``1.`` a point, but only the path
        says which is which.
        """
        kind = self._segment_kind(node.fragment_id)
        designation = (node.designation or "").strip()

        if kind in {"§", "čl."}:
            return designation or kind  # designation already reads "§ 41"
        if not designation:
            # Unnumbered units (annex headers) are named by their own text.
            return node.content if kind else ""
        if kind is None:
            return designation
        if kind == "odst.":
            return f"odst. {designation.strip('()')}"
        return f"{kind} {designation}"

    @staticmethod
    def _segment_kind(fragment_id: str) -> str | None:
        segment = fragment_id.rstrip("/").rsplit("/", 1)[-1]
        prefix = segment.split("_", 1)[0]
        return _SEGMENT_LABELS.get(prefix)

    # ------------------------------------------------------------- footnotes

    def footnote_refs(self, text: str) -> dict[str, str]:
        """Footnote markers occurring in ``text``, resolved to their content.

        Only markers present in the document's footnote table are returned,
        which filters out false positives from the reference regex.
        """
        if not self.footnotes:
            return {}
        found = {match.group(1) for match in _FOOTNOTE_REF.finditer(text)}
        return {
            marker: self.footnotes[marker] for marker in sorted(found) if marker in self.footnotes
        }

    def _collect_footnotes(self) -> dict[str, str]:
        table: dict[str, str] = {}
        for node in self.root.walk():
            if node.role is not Role.FOOTNOTE:
                continue
            marker = (node.designation or "").strip()
            if not marker:
                continue
            body = node.content
            # Footnote bodies repeat their own marker; drop the duplicate.
            if body.startswith(marker):
                body = body[len(marker) :].strip()
            table[marker] = body
        return table

    # -------------------------------------------------------------- headings

    def _attribute_headings(self, node: Node) -> None:
        """Split heading children into "own title" vs "titles what follows".

        A heading with children of its own is *not* a title but a structural
        level (annexes nest their body text under ``Nadpis`` nodes), so it stays
        in the body -- otherwise excluding the title would drop its subtree.
        """
        own: list[Node] = []
        pending: Node | None = None
        seen_content = False

        for child in node.children:
            if child.role is Role.HEADING and not child.children:
                if seen_content:
                    pending = child  # titles the following siblings
                else:
                    own.append(child)  # titles this node
                continue
            seen_content = True
            if pending is not None:
                self._group_heading[child.fragment_id] = pending

        if own:
            self._own_headings[node.fragment_id] = own
        for child in node.children:
            self._attribute_headings(child)


# ------------------------------------------------------------------ builders


def build_tree(
    fragments: list[Fragment],
    *,
    include_repealed: bool = False,
) -> tuple[Node, ParseReport]:
    """Reconstruct the document tree from a flat fragment list.

    Parentage comes from ``depth`` + ``position``, not from ``fragment_id``:
    the API returns ``parent_fragment_id = null`` everywhere, and transparent
    ``Block_*`` wrappers are *not* path prefixes of the fragments they wrap
    (``.../par_396/frag_123`` wraps ``.../par_396/odst_1``). ``depth`` does
    model that nesting correctly, so a depth stack is the faithful reading.

    Args:
        fragments: Fragments in any order; sorted by ``position`` internally.
        include_repealed: Keep repealed fragments (and their subtrees) instead
            of dropping them.

    Returns:
        The root node and a :class:`ParseReport`.
    """
    if not fragments:
        msg = "cannot build a document tree from zero fragments"
        raise ValueError(msg)

    ordered = sorted(fragments, key=lambda f: f.position)
    report = ParseReport(fragment_count=len(ordered))

    # Group children by depth first so classification knows about descendants.
    child_counts: dict[int, int] = {}
    stack_probe: list[int] = []
    for fragment in ordered:
        while len(stack_probe) > fragment.depth:
            stack_probe.pop()
        if stack_probe:
            child_counts[stack_probe[-1]] = child_counts.get(stack_probe[-1], 0) + 1
        stack_probe.append(fragment.id)

    root_fragment = ordered[0]
    root = Node(
        fragment=root_fragment,
        role=classify(root_fragment, has_children=child_counts.get(root_fragment.id, 0) > 0),
    )
    stack: list[Node] = [root]
    dropped_at_depth: int | None = None

    for fragment in ordered[1:]:
        if not is_known_type(fragment.type):
            report.unknown_types[fragment.type] = report.unknown_types.get(fragment.type, 0) + 1

        # Anything nested under a dropped fragment goes with it. Tested against
        # the raw depth: the clamp below assumes an open parent, which a dropped
        # subtree no longer has.
        if dropped_at_depth is not None:
            if fragment.depth > dropped_at_depth:
                continue
            dropped_at_depth = None

        depth = fragment.depth
        if depth > len(stack):
            report.depth_gaps += 1
            depth = len(stack)  # clamp: attach as a child of the deepest open node

        if fragment.is_repealed and not include_repealed:
            report.dropped_repealed += 1
            dropped_at_depth = depth
            continue

        del stack[depth:]
        parent = stack[-1]
        node = Node(
            fragment=fragment,
            role=classify(fragment, has_children=child_counts.get(fragment.id, 0) > 0),
            parent=parent,
        )
        parent.children.append(node)
        stack.append(node)

    report.node_count = len(root.walk())
    return root, report


def extract_metadata(root: Node) -> LawMetadata:
    """Derive law metadata from the ELI identifier and ``Prefix_*`` fragments."""
    values: dict[str, str] = {}
    for node in root.walk():
        if node.role is Role.DOC_META:
            key = _DOC_META_FIELDS.get(node.type)
            if key and node.content:
                values[key] = node.content

    law_id = root.fragment_id.rsplit("/dokument", 1)[0]
    match = _ELI_VERSION_RE.match(root.fragment_id)
    year = int(match.group("year")) if match else None
    number = values.get("number") or (match.group("number") if match else None)
    version_date = match.group("date") if match else None

    kind = values.get("kind")
    return LawMetadata(
        law_id=law_id,
        number=number,
        year=year,
        version_date=version_date,
        kind=kind.title() if kind and kind.isupper() else kind,
        title=values.get("title"),
        enacted_on=values.get("enacted_on"),
    )
