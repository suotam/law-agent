"""Turning an item into embeddable text, and cutting it up when it is too big.

A heading keeps its markdown prefix because it stays in the chunk body: that is
what makes the chunk retrievable without a separate header field, and what makes
a misdetected heading harmless -- at worst it moves a cut by one paragraph.
"""

from __future__ import annotations

from collections.abc import Sequence

from law_agent.ingestion.files.items import Item, ItemKind
from law_agent.ingestion.text import hard_wrap, split_sentences
from law_agent.ingestion.tokenizer import TokenCounter

_HEADING_PREFIX = "## "
"""One level, always: Docling gives PDF headings no levels to mirror."""


def serialize(item: Item) -> str:
    """The text this item contributes to a chunk."""
    if item.kind is ItemKind.HEADING:
        return f"{_HEADING_PREFIX}{item.text}"
    if item.kind is ItemKind.LIST_ITEM:
        return f"- {item.text}"
    if item.kind is ItemKind.TABLE:
        return "\n".join([*_header_lines(item), *_body_lines(item)])
    return item.text


def split_item(item: Item, *, budget: int, count_tokens: TokenCounter) -> list[str]:
    """Cut an item that does not fit into pieces that do.

    Tables split by rows with the column header repeated; everything else splits
    on sentence boundaries. The pieces are not chunks -- the packer keeps the
    last one open so that the tail of a big table does not become a stub chunk.
    """
    if item.kind is ItemKind.TABLE:
        return _split_table(item, budget=budget, count_tokens=count_tokens)
    return _split_text(serialize(item), budget=budget, count_tokens=count_tokens)


def _header_lines(item: Item) -> list[str]:
    """The column header plus the markdown separator, repeated into every piece."""
    head = item.rows[: item.header_rows or 1]
    width = len(item.rows[0]) if item.rows else 0
    return [*(_row(row) for row in head), _row(["---"] * width)]


def _body_lines(item: Item) -> list[str]:
    return [_row(row) for row in item.rows[item.header_rows or 1 :]]


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _split_table(item: Item, *, budget: int, count_tokens: TokenCounter) -> list[str]:
    header = "\n".join(_header_lines(item))
    pieces: list[str] = []
    current: list[str] = []

    for line in _body_lines(item):
        # A row that does not fit even next to the header: cut the row itself
        # rather than emit a piece over the budget.
        if count_tokens(f"{header}\n{line}") > budget:
            if current:
                pieces.append("\n".join([header, *current]))
                current = []
            pieces.extend(_split_text(line, budget=budget, count_tokens=count_tokens))
            continue
        if current and count_tokens("\n".join([header, *current, line])) > budget:
            pieces.append("\n".join([header, *current]))
            current = [line]
        else:
            current.append(line)

    if current:
        pieces.append("\n".join([header, *current]))
    return pieces


def _split_text(text: str, *, budget: int, count_tokens: TokenCounter) -> list[str]:
    sentences = split_sentences(text) or [text]

    pieces: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        candidate = [*current, sentence]
        if current and count_tokens(" ".join(candidate)) > budget:
            pieces.append(" ".join(current))
            current = [sentence]
        else:
            current = candidate
    if current:
        pieces.append(" ".join(current))

    # A single sentence can still be longer than the budget.
    wrapped: list[str] = []
    for piece in pieces:
        if count_tokens(piece) <= budget:
            wrapped.append(piece)
        else:
            wrapped.extend(hard_wrap(piece, budget, count_tokens))
    return wrapped
