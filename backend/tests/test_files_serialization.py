"""Tests for turning an item into text and splitting it when it overflows."""

from __future__ import annotations

from law_agent.ingestion import HeuristicTokenCounter
from law_agent.ingestion.files.items import Item, ItemKind
from law_agent.ingestion.files.serialization import serialize, split_item

_COUNTER = HeuristicTokenCounter()

_TABLE = Item(
    kind=ItemKind.TABLE,
    rows=(("Sloupec", "Hodnota"), ("a", "1"), ("b", "2")),
    header_rows=1,
)


def test_a_heading_carries_its_markdown_prefix() -> None:
    """It stays in the body, so it has to be recognisable as a heading there."""
    item = Item(kind=ItemKind.HEADING, text="Odstoupení od smlouvy")

    assert serialize(item) == "## Odstoupení od smlouvy"


def test_a_bullet_carries_its_marker() -> None:
    assert serialize(Item(kind=ItemKind.LIST_ITEM, text="první bod")) == "- první bod"


def test_a_paragraph_is_its_own_text() -> None:
    assert serialize(Item(kind=ItemKind.TEXT, text="Odstavec.")) == "Odstavec."


def test_a_table_renders_as_markdown_with_a_separator() -> None:
    assert serialize(_TABLE) == "| Sloupec | Hodnota |\n| --- | --- |\n| a | 1 |\n| b | 2 |"


def test_a_table_without_marked_header_rows_still_renders() -> None:
    """Markdown needs a header row, so the first row stands in for one."""
    item = Item(kind=ItemKind.TABLE, rows=(("a", "1"), ("b", "2")), header_rows=0)

    assert serialize(item) == "| a | 1 |\n| --- | --- |\n| b | 2 |"


def test_an_oversized_paragraph_splits_on_sentences() -> None:
    text = " ".join(f"Věta číslo {n} má nějaký obsah." for n in range(40))
    item = Item(kind=ItemKind.TEXT, text=text)

    pieces = split_item(item, budget=40, count_tokens=_COUNTER)

    assert len(pieces) > 1
    assert all(_COUNTER(piece) <= 40 for piece in pieces)
    assert all(piece.endswith(".") for piece in pieces)


def test_every_piece_of_a_split_table_starts_with_the_header() -> None:
    """Without it the second piece is bare rows with no column meaning."""
    rows = (("Sloupec", "Hodnota"), *((f"řádek {n}", str(n)) for n in range(40)))
    item = Item(kind=ItemKind.TABLE, rows=rows, header_rows=1)

    pieces = split_item(item, budget=40, count_tokens=_COUNTER)

    assert len(pieces) > 1
    assert all(piece.startswith("| Sloupec | Hodnota |\n| --- | --- |") for piece in pieces)
    assert all(_COUNTER(piece) <= 40 for piece in pieces)


def test_splitting_keeps_every_row() -> None:
    rows = (("Sloupec", "Hodnota"), *((f"řádek {n}", str(n)) for n in range(40)))
    item = Item(kind=ItemKind.TABLE, rows=rows, header_rows=1)

    pieces = split_item(item, budget=40, count_tokens=_COUNTER)

    for n in range(40):
        assert any(f"| řádek {n} | {n} |" in piece for piece in pieces)


def test_a_single_sentence_longer_than_the_budget_is_wrapped() -> None:
    item = Item(kind=ItemKind.TEXT, text="slovo " * 200)

    pieces = split_item(item, budget=20, count_tokens=_COUNTER)

    assert all(_COUNTER(piece) <= 20 for piece in pieces)


def test_an_item_that_fits_is_returned_whole() -> None:
    item = Item(kind=ItemKind.TEXT, text="Krátký odstavec.")

    assert split_item(item, budget=100, count_tokens=_COUNTER) == ["Krátký odstavec."]
