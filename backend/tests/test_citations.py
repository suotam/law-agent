"""Tests for resolving the [n] marks in an answer against what was offered."""

from __future__ import annotations

import pytest

from law_agent.chain import Numbering, used_refs
from law_agent.conversations import SourceItem


def _offered(*refs: int) -> dict[int, SourceItem]:
    return {
        ref: SourceItem(
            ref=ref, kind="law", label=f"§ {ref}", content={"chunk_id": f"c{ref}", "text": "t"}
        )
        for ref in refs
    }


@pytest.mark.parametrize(
    ("text", "offered", "expected"),
    [
        ("Tvrzení [1] a další [2].", {1, 2, 3}, [1, 2]),
        ("Opakovaná značka [2] a zase [2].", {1, 2, 3}, [2]),
        ("Pořadí prvního výskytu [3] pak [1].", {1, 2, 3}, [3, 1]),
        ("Vymyšlená značka [12] z deseti.", set(range(1, 11)), []),
        ("Nula neexistuje [0].", {1, 2, 3}, []),
        ("Bez značek.", {1, 2, 3}, []),
        ("Nic nebylo nabídnuto [1].", set(), []),
    ],
)
def test_used_refs(text: str, offered: set[int], expected: list[int]) -> None:
    assert used_refs(text, offered) == expected


def test_an_empty_conversation_starts_at_one() -> None:
    numbering = Numbering.of({})

    assert numbering.ref_for("c1") == 1
    assert numbering.ref_for("c2") == 2


def test_a_known_chunk_keeps_the_ref_it_already_has() -> None:
    """The model has the old number in front of it; a second number for the
    same material would let one answer make the same claim twice."""
    numbering = Numbering.of(_offered(1, 2, 3))

    assert numbering.ref_for("c2") == 2


def test_numbering_continues_past_uncited_material() -> None:
    """Refs are unique across everything offered, not across what was cited --
    the FE accumulates its map from every item the API sent it, so a reissued
    number would resolve to the earlier source."""
    numbering = Numbering.of(_offered(1, 2, 3))

    assert numbering.ref_for("nova") == 4


def test_a_repeat_within_one_call_consumes_no_number() -> None:
    numbering = Numbering.of({})

    assert [numbering.ref_for("c1"), numbering.ref_for("c1"), numbering.ref_for("c2")] == [1, 1, 2]


def test_numbering_advances_across_searches_in_one_turn() -> None:
    """A future agent loop searches twice before anything is stored; the second
    search has to continue where the first stopped."""
    numbering = Numbering.of(_offered(1))

    first = numbering.ref_for("a")
    second = numbering.ref_for("b")

    assert (first, second) == (2, 3)


def test_an_item_without_a_chunk_id_does_not_reserve_a_mapping() -> None:
    """``content`` is opaque; a tool that stores no chunk id simply cannot be
    deduplicated, and must not map every such item onto one key."""
    offered = {1: SourceItem(ref=1, kind="law", label="§ 1", content={"text": "t"})}

    numbering = Numbering.of(offered)

    assert numbering.ref_for("c9") == 2
