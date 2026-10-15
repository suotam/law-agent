"""Flattening a parsed document into the stream the packer walks.

The document is treated as a flat sequence of items in reading order, not as a
tree: Docling gives PDF headings no levels, so there is no hierarchy to recurse
into. This is the only module in the package that knows Docling types --
everything downstream works on :class:`Item`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.node import NodeItem
from docling_core.types.doc.items.table.table import TableItem
from docling_core.types.doc.labels import DocItemLabel

# Never embedded: running headers and footers would repeat in every chunk, and a
# picture carries no text -- its caption arrives separately as its own item.
EXCLUDED_LABELS = frozenset(
    {
        DocItemLabel.PAGE_HEADER,
        DocItemLabel.PAGE_FOOTER,
        DocItemLabel.PICTURE,
    }
)

_HEADING_LABELS = frozenset({DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER})


class ItemKind(StrEnum):
    """What an item is, to the extent the chunker cares."""

    HEADING = "heading"
    LIST_ITEM = "list_item"
    TABLE = "table"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class Item:
    """One unit of the stream: a paragraph, a heading, a bullet or a table.

    Deliberately free of Docling types, so serialization and packing can be
    tested without building a parsed document.
    """

    kind: ItemKind

    text: str = ""
    """Plain text; empty for a table, whose content is in :attr:`rows`."""

    rows: tuple[tuple[str, ...], ...] = ()

    header_rows: int = 0
    """How many leading rows are the table's column header; repeated into every
    piece when the table has to be split."""

    pages: tuple[int, ...] = ()
    """Pages this item sits on; empty when the source carries no provenance."""


def iter_items(document: DoclingDocument) -> list[Item]:
    """Flatten ``document`` into items in reading order, dropping the excluded ones."""
    items = (_to_item(node) for node, _level in document.iterate_items())
    return [item for item in items if item is not None]


def _to_item(node: NodeItem) -> Item | None:
    label = getattr(node, "label", None)
    if label in EXCLUDED_LABELS:
        return None

    pages = _pages_of(node)
    if isinstance(node, TableItem):
        rows, header_rows = _rows_of(node)
        if not rows:
            return None
        return Item(kind=ItemKind.TABLE, rows=rows, header_rows=header_rows, pages=pages)

    text = (getattr(node, "text", "") or "").strip()
    if not text:
        return None
    return Item(kind=_kind_of(label), text=text, pages=pages)


def _kind_of(label: DocItemLabel | None) -> ItemKind:
    if label in _HEADING_LABELS:
        return ItemKind.HEADING
    if label is DocItemLabel.LIST_ITEM:
        return ItemKind.LIST_ITEM
    return ItemKind.TEXT


def _rows_of(table: TableItem) -> tuple[tuple[tuple[str, ...], ...], int]:
    """Cell texts row by row, plus the number of leading header rows."""
    grid = table.data.grid
    rows = tuple(tuple((cell.text or "").strip() for cell in row) for row in grid)

    header_rows = 0
    for row in grid:
        if not row or not all(cell.column_header for cell in row):
            break
        header_rows += 1
    return rows, header_rows


def _pages_of(node: NodeItem) -> tuple[int, ...]:
    return tuple(sorted({prov.page_no for prov in getattr(node, "prov", [])}))
