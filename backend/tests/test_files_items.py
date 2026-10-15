"""Tests for flattening a DoclingDocument into the chunker's item stream."""

from __future__ import annotations

from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.table.table_data import TableCell, TableData
from docling_core.types.doc.labels import DocItemLabel

from law_agent.ingestion.files.items import ItemKind, iter_items


def _table_data(rows: list[list[str]], *, header_rows: int = 1) -> TableData:
    cells = [
        TableCell(
            text=text,
            start_row_offset_idx=r,
            end_row_offset_idx=r + 1,
            start_col_offset_idx=c,
            end_col_offset_idx=c + 1,
            column_header=r < header_rows,
        )
        for r, row in enumerate(rows)
        for c, text in enumerate(row)
    ]
    return TableData(num_rows=len(rows), num_cols=len(rows[0]), table_cells=cells)


def test_running_headers_and_footers_are_dropped() -> None:
    """They would repeat in every chunk and blur the embedding."""
    document = DoclingDocument(name="x")
    document.add_text(label=DocItemLabel.PAGE_HEADER, text="Smlouva o dílo")
    document.add_text(label=DocItemLabel.TEXT, text="Skutečný odstavec.")
    document.add_text(label=DocItemLabel.PAGE_FOOTER, text="strana 1")

    assert [item.text for item in iter_items(document)] == ["Skutečný odstavec."]


def test_pictures_are_dropped_but_their_captions_survive() -> None:
    """A caption is its own item in reading order, so the picture itself adds nothing."""
    document = DoclingDocument(name="x")
    caption = document.add_text(label=DocItemLabel.CAPTION, text="Obr. 1 – schéma")
    document.add_picture(caption=caption)
    document.add_picture()

    assert [item.text for item in iter_items(document)] == ["Obr. 1 – schéma"]


def test_items_keep_reading_order() -> None:
    document = DoclingDocument(name="x")
    document.add_heading(text="Nadpis")
    document.add_text(label=DocItemLabel.TEXT, text="První.")
    document.add_text(label=DocItemLabel.TEXT, text="Druhý.")

    assert [item.text for item in iter_items(document)] == ["Nadpis", "První.", "Druhý."]


def test_a_heading_is_marked_as_one() -> None:
    document = DoclingDocument(name="x")
    document.add_heading(text="Odstoupení od smlouvy")
    document.add_text(label=DocItemLabel.TEXT, text="Text.")

    kinds = [item.kind for item in iter_items(document)]

    assert kinds == [ItemKind.HEADING, ItemKind.TEXT]


def test_a_list_becomes_one_item_per_bullet() -> None:
    """Bullets are separate items, so a list splits sensibly without its own logic."""
    document = DoclingDocument(name="x")
    group = document.add_list_group()
    document.add_list_item(text="první bod", parent=group)
    document.add_list_item(text="druhý bod", parent=group)

    items = iter_items(document)

    assert [item.kind for item in items] == [ItemKind.LIST_ITEM, ItemKind.LIST_ITEM]
    assert [item.text for item in items] == ["první bod", "druhý bod"]


def test_a_table_arrives_as_rows_with_a_header_count() -> None:
    document = DoclingDocument(name="x")
    document.add_table(data=_table_data([["Sloupec", "Hodnota"], ["a", "1"], ["b", "2"]]))

    item = iter_items(document)[0]

    assert item.kind is ItemKind.TABLE
    assert item.rows == (("Sloupec", "Hodnota"), ("a", "1"), ("b", "2"))
    assert item.header_rows == 1


def test_empty_items_are_dropped() -> None:
    """Whitespace-only text has nothing to embed and would only add separators."""
    document = DoclingDocument(name="x")
    document.add_text(label=DocItemLabel.TEXT, text="   ")
    document.add_text(label=DocItemLabel.TEXT, text="Text.")

    assert [item.text for item in iter_items(document)] == ["Text."]
