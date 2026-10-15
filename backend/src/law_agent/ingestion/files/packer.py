"""Gluing items into chunks: size decides, structure only advises.

A chunk is closed when the next item would overflow the budget, or early at a
heading once the chunk is already past a soft threshold -- the one boundary
worth cutting on before the budget says so. Because items are paragraphs, every
cut between them already falls on a paragraph boundary, so no other boundary
needs weighing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from law_agent.ingestion.files.items import Item, ItemKind
from law_agent.ingestion.files.serialization import serialize, split_item
from law_agent.ingestion.tokenizer import TokenCounter, default_token_counter

DEFAULT_SOFT_RATIO = 0.6
"""Share of the budget above which a heading is allowed to close a chunk."""

_SEPARATOR = "\n\n"


@dataclass(frozen=True, slots=True)
class PackedChunk:
    """A finished chunk, before it is given an identity and a citation."""

    text: str
    pages: tuple[int, ...] = ()

    heading: str | None = None
    """The last heading seen at or before this chunk; feeds the citation."""


@dataclass(slots=True)
class _Open:
    """The chunk currently being filled."""

    parts: list[str] = field(default_factory=list)
    pages: set[int] = field(default_factory=set)

    def add(self, text: str, pages: tuple[int, ...]) -> None:
        self.parts.append(text)
        self.pages.update(pages)

    def start(self, text: str, pages: tuple[int, ...]) -> None:
        self.parts = [text]
        self.pages = set(pages)

    def clear(self) -> None:
        self.parts = []
        self.pages = set()

    @property
    def text(self) -> str:
        return _SEPARATOR.join(self.parts)


class Packer:
    """Turns an item stream into chunks that respect a token budget."""

    def __init__(
        self,
        *,
        budget: int,
        soft_ratio: float = DEFAULT_SOFT_RATIO,
        count_tokens: TokenCounter | None = None,
    ) -> None:
        self._budget = budget
        self._soft = int(budget * soft_ratio)
        self._count = count_tokens or default_token_counter()

    def pack(self, items: list[Item]) -> list[PackedChunk]:
        """Chunks in document order."""
        chunks: list[PackedChunk] = []
        open_chunk = _Open()
        heading: str | None = None

        def close() -> None:
            if not open_chunk.parts:
                return
            chunks.append(
                PackedChunk(
                    text=open_chunk.text,
                    pages=tuple(sorted(open_chunk.pages)),
                    heading=heading,
                )
            )
            open_chunk.clear()

        for item in items:
            text = serialize(item)
            if not text:
                continue

            # Closed before the heading variable moves: the chunk being closed
            # belongs to the previous heading, not to the one closing it.
            if item.kind is ItemKind.HEADING:
                if self._count(open_chunk.text) >= self._soft:
                    close()
                heading = item.text

            if not open_chunk.parts:
                if self._count(text) <= self._budget:
                    open_chunk.start(text, item.pages)
                    continue
            elif self._count(_SEPARATOR.join([*open_chunk.parts, text])) <= self._budget:
                open_chunk.add(text, item.pages)
                continue

            if self._count(text) <= self._budget:
                close()
                open_chunk.start(text, item.pages)
                continue

            # Too big to fit anywhere: cut it up, ship the full pieces and keep
            # the tail open so the next items land in it instead of a stub.
            close()
            pieces = split_item(item, budget=self._budget, count_tokens=self._count)
            for piece in pieces[:-1]:
                chunks.append(
                    PackedChunk(text=piece, pages=tuple(sorted(item.pages)), heading=heading)
                )
            if pieces:
                open_chunk.start(pieces[-1], item.pages)

        close()
        return chunks
