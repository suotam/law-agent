"""Tests for gluing items into chunks: size decides, structure advises."""

from __future__ import annotations

from law_agent.ingestion import HeuristicTokenCounter
from law_agent.ingestion.files.items import Item, ItemKind
from law_agent.ingestion.files.packer import PackedChunk, Packer

_COUNTER = HeuristicTokenCounter()


def _heading(text: str, *, pages: tuple[int, ...] = ()) -> Item:
    return Item(kind=ItemKind.HEADING, text=text, pages=pages)


def _paragraph(text: str, *, pages: tuple[int, ...] = ()) -> Item:
    return Item(kind=ItemKind.TEXT, text=text, pages=pages)


def _prose(words: int) -> str:
    return " ".join(f"slovo{n}" for n in range(words)) + "."


def _pack(items: list[Item], *, budget: int = 100, soft_ratio: float = 0.6) -> list[PackedChunk]:
    return Packer(budget=budget, soft_ratio=soft_ratio, count_tokens=_COUNTER).pack(items)


def test_no_chunk_exceeds_the_budget() -> None:
    items = [_paragraph(_prose(30)) for _ in range(20)]

    chunks = _pack(items, budget=100)

    assert all(_COUNTER(chunk.text) <= 100 for chunk in chunks)


def test_items_that_fit_together_stay_together() -> None:
    chunks = _pack([_paragraph("První odstavec."), _paragraph("Druhý odstavec.")], budget=100)

    assert len(chunks) == 1
    assert chunks[0].text == "První odstavec.\n\nDruhý odstavec."


def test_a_heading_below_the_soft_threshold_does_not_cut() -> None:
    """Cutting there would produce exactly the stub chunks this design removes."""
    items = [_paragraph("Krátký odstavec."), _heading("Nadpis"), _paragraph("Další odstavec.")]

    chunks = _pack(items, budget=200, soft_ratio=0.6)

    assert len(chunks) == 1
    assert "## Nadpis" in chunks[0].text


def test_a_heading_above_the_soft_threshold_cuts() -> None:
    # ~140 tokens under the heuristic counter: past the soft threshold of 120,
    # still inside the budget of 200, so only the heading can close it.
    items = [_paragraph(_prose(60)), _heading("Nadpis"), _paragraph("Další odstavec.")]

    chunks = _pack(items, budget=200, soft_ratio=0.6)

    assert len(chunks) == 2
    assert "Nadpis" not in chunks[0].text
    assert chunks[1].text.startswith("## Nadpis")


def test_a_document_without_headings_fills_the_budget() -> None:
    """Nothing advises a cut, so only the budget does."""
    items = [_paragraph(_prose(20)) for _ in range(30)]

    chunks = _pack(items, budget=200)

    assert len(chunks) > 1
    assert all(_COUNTER(chunk.text) > 100 for chunk in chunks[:-1])


def test_an_oversized_item_leaves_its_tail_open() -> None:
    """Otherwise every big table would be followed by a stub chunk."""
    # ~140 tokens against a budget of 100: two pieces, the second with room left.
    items = [_paragraph(_prose(60)), _paragraph("Navazující odstavec.")]

    chunks = _pack(items, budget=100)

    assert chunks[-1].text.endswith("Navazující odstavec.")
    assert chunks[-1].text.startswith("slovo"), "the tail piece must stay open"


def test_a_chunk_takes_the_last_heading_it_contains() -> None:
    items = [_heading("První"), _paragraph("Text."), _heading("Druhý"), _paragraph("Text.")]

    chunks = _pack(items, budget=500)

    assert len(chunks) == 1
    assert chunks[0].heading == "Druhý"


def test_a_chunk_without_a_heading_inherits_the_previous_one() -> None:
    """A hard cut mid-section must not lose the citation label."""
    items = [_heading("Odstoupení od smlouvy"), *(_paragraph(_prose(30)) for _ in range(10))]

    chunks = _pack(items, budget=100)

    assert len(chunks) > 1
    assert all(chunk.heading == "Odstoupení od smlouvy" for chunk in chunks)


def test_the_heading_is_stored_without_its_markdown_prefix() -> None:
    """It feeds the citation, where '##' would be noise."""
    chunks = _pack([_heading("Nadpis"), _paragraph("Text.")], budget=500)

    assert chunks[0].heading == "Nadpis"
    assert chunks[0].text.startswith("## Nadpis")


def test_pages_are_the_union_of_the_items_pages() -> None:
    items = [_paragraph("A.", pages=(4,)), _paragraph("B.", pages=(5, 4))]

    chunks = _pack(items, budget=500)

    assert chunks[0].pages == (4, 5)


def test_an_empty_document_yields_no_chunks() -> None:
    assert _pack([]) == []
