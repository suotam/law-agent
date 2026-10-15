"""Tests for the stored block shape and its translation to LangChain messages."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from law_agent.chain.prompt import NOTHING_CITED
from law_agent.conversations import ConversationMeta, Role, SourceItem
from law_agent.conversations.blocks import (
    blocks_from,
    carried_refs,
    offered_items,
    text_block,
    to_langchain,
    tool_result_block,
    turns,
)
from law_agent.conversations.models import Message

CONVERSATION = uuid4()


def _message(seq: int, role: Role, blocks: list[dict]) -> Message:
    return Message(
        id=uuid4(),
        conversation_id=CONVERSATION,
        seq=seq,
        role=role,
        blocks=blocks,
        created_at=datetime.now(UTC),
    )


def _item(ref: int) -> SourceItem:
    return SourceItem(ref=ref, kind="law", label=f"§ {ref}", content={"text": f"text {ref}"})


def _render(items, carried=()) -> str:
    return "\n".join(
        f"[{item.ref}] {item.label} (uvedeno výše)"
        if item.ref in carried
        else f"[{item.ref}] {item.label}\n{item.content['text']}"
        for item in items
    )


def _tool_call_message() -> AIMessage:
    return AIMessage(
        content=[
            {"type": "reasoning", "reasoning": "musím dohledat", "extras": {"signature": "sig"}},
            {"type": "text", "text": "Podívám se do zákona."},
        ],
        tool_calls=[
            {
                "name": "search",
                "args": {"query": "odstoupení"},
                "id": "call_a1",
                "type": "tool_call",
            }
        ],
    )


def test_meta_defaults_to_the_full_scope() -> None:
    """A conversation created without a sidebar selection must still be
    answerable -- an empty scope would retrieve nothing, silently."""
    meta = ConversationMeta()

    assert meta.scope
    assert meta.limit > 0


def test_meta_round_trips_through_a_plain_dict() -> None:
    """It is stored as jsonb; the column is the reason the model exists."""
    meta = ConversationMeta(scope=["laws"], limit=5)

    assert ConversationMeta.model_validate(meta.model_dump()) == meta


def test_a_source_item_keeps_its_kind_specific_content_opaque() -> None:
    """Every tool shapes ``content`` itself; only ref/kind/label are shared."""
    item = SourceItem(
        ref=1,
        kind="law",
        label="§ 1829 obč. zák.",
        content={"law_id": "/eli/x", "anchor": "/eli/x/par_1829", "text": "Spotřebitel…"},
    )

    assert item.model_dump()["content"]["anchor"] == "/eli/x/par_1829"


def test_roles_are_the_three_the_schema_stores() -> None:
    assert {str(role) for role in Role} == {"user", "assistant", "tool"}


def test_a_user_message_becomes_one_text_block() -> None:
    assert blocks_from(HumanMessage("Kdy můžu odstoupit?")) == [
        {"type": "text", "text": "Kdy můžu odstoupit?"}
    ]


def test_an_assistant_message_keeps_block_order_and_the_tool_call() -> None:
    """Extended thinking requires reasoning to come back verbatim and in
    place, which is why the order is part of the stored shape."""
    blocks = blocks_from(_tool_call_message())

    assert [block["type"] for block in blocks] == ["reasoning", "text", "tool_use"]
    assert blocks[0] == {"type": "reasoning", "reasoning": "musím dohledat", "signature": "sig"}
    assert blocks[2] == {
        "type": "tool_use",
        "id": "call_a1",
        "name": "search",
        "args": {"query": "odstoupení"},
    }


def test_an_assistant_message_round_trips() -> None:
    original = _tool_call_message()

    restored = to_langchain([_message(1, Role.ASSISTANT, blocks_from(original))], render=_render)[0]

    assert isinstance(restored, AIMessage)
    assert restored.content_blocks == original.content_blocks


def test_a_tool_result_becomes_a_tool_message_bound_to_its_call() -> None:
    block = tool_result_block("call_a1", [_item(1), _item(2)])

    restored = to_langchain([_message(1, Role.TOOL, [block])], render=_render)[0]

    assert isinstance(restored, ToolMessage)
    assert restored.tool_call_id == "call_a1"
    assert "[2] § 2" in str(restored.text)


def test_turns_start_at_every_user_row() -> None:
    rows = [
        _message(1, Role.USER, [text_block("první")]),
        _message(2, Role.ASSISTANT, blocks_from(_tool_call_message())),
        _message(3, Role.TOOL, [tool_result_block("call_a1", [_item(1)])]),
        _message(4, Role.ASSISTANT, [text_block("odpověď")]),
        _message(5, Role.USER, [text_block("druhý")]),
    ]

    assert [[row.seq for row in turn] for turn in turns(rows)] == [[1, 2, 3, 4], [5]]


def test_offered_items_are_indexed_by_ref() -> None:
    turn = [
        _message(1, Role.USER, [text_block("dotaz")]),
        _message(2, Role.TOOL, [tool_result_block("call_a1", [_item(1), _item(2)])]),
        _message(3, Role.TOOL, [tool_result_block("call_a2", [_item(3)])]),
    ]

    assert sorted(offered_items(turn)) == [1, 2, 3]
    assert offered_items(turn)[3].label == "§ 3"


def test_a_past_turn_replays_its_call_result_and_answer() -> None:
    """The model answering the third question has to see what the first
    retrieved, or it cannot cite it."""
    rows = [
        _message(1, Role.USER, [text_block("první")]),
        _message(2, Role.ASSISTANT, blocks_from(_tool_call_message())),
        _message(3, Role.TOOL, [tool_result_block("call_a1", [_item(1), _item(2)])]),
        _message(4, Role.ASSISTANT, [text_block("první odpověď [1]")]),
        _message(5, Role.USER, [text_block("druhý")]),
    ]

    replayed = to_langchain(rows, render=_render)

    assert [type(message).__name__ for message in replayed] == [
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
        "AIMessage",
        "HumanMessage",
    ]
    assert replayed[1].tool_calls


def test_a_past_turn_keeps_only_the_material_its_answer_cited() -> None:
    rows = [
        _message(1, Role.USER, [text_block("první")]),
        _message(2, Role.ASSISTANT, blocks_from(_tool_call_message())),
        _message(3, Role.TOOL, [tool_result_block("call_a1", [_item(1), _item(2), _item(3)])]),
        _message(4, Role.ASSISTANT, [text_block("odpověď [3] a [1]")]),
        _message(5, Role.USER, [text_block("druhý")]),
    ]

    replayed = to_langchain(rows, render=_render)

    result = str(replayed[2].text)
    assert "[1] § 1" in result
    assert "[3] § 3" in result
    assert "[2]" not in result


def test_a_turn_that_cited_nothing_keeps_a_paired_but_empty_result() -> None:
    """The ToolMessage cannot be dropped -- its AIMessage carries the matching
    tool_call_id and the API rejects one without the other."""
    rows = [
        _message(1, Role.USER, [text_block("první")]),
        _message(2, Role.ASSISTANT, blocks_from(_tool_call_message())),
        _message(3, Role.TOOL, [tool_result_block("call_a1", [_item(1)])]),
        _message(4, Role.ASSISTANT, [text_block("Podklady na to neodpovídají.")]),
        _message(5, Role.USER, [text_block("druhý")]),
    ]

    replayed = to_langchain(rows, render=_render)

    assert isinstance(replayed[2], ToolMessage)
    assert replayed[2].tool_call_id == "call_a1"
    assert str(replayed[2].text) == NOTHING_CITED
    assert "§ 1" not in str(replayed[2].text)


def test_a_source_cited_twice_prints_its_text_only_the_first_time() -> None:
    """What the model saw live and what it sees on replay have to match, or the
    prefix moves and the cache is thrown away."""
    rows = [
        _message(1, Role.USER, [text_block("první")]),
        _message(2, Role.ASSISTANT, blocks_from(_tool_call_message())),
        _message(3, Role.TOOL, [tool_result_block("call_a1", [_item(1)])]),
        _message(4, Role.ASSISTANT, [text_block("první odpověď [1]")]),
        _message(5, Role.USER, [text_block("druhý")]),
        _message(6, Role.ASSISTANT, blocks_from(_tool_call_message())),
        _message(7, Role.TOOL, [tool_result_block("call_a1", [_item(1)])]),
        _message(8, Role.ASSISTANT, [text_block("druhá odpověď [1]")]),
        _message(9, Role.USER, [text_block("třetí")]),
    ]

    replayed = to_langchain(rows, render=_render)

    assert "text 1" in str(replayed[2].text)
    assert "text 1" not in str(replayed[6].text)
    assert "uvedeno výše" in str(replayed[6].text)


def test_carried_refs_are_the_ones_the_answers_used() -> None:
    rows = [
        _message(1, Role.USER, [text_block("první")]),
        _message(2, Role.TOOL, [tool_result_block("call_a1", [_item(1), _item(2)])]),
        _message(3, Role.ASSISTANT, [text_block("odpověď [2]")]),
        _message(4, Role.USER, [text_block("druhý")]),
    ]

    assert carried_refs(rows) == {2}


def test_offered_items_span_the_whole_conversation() -> None:
    """The ref table a new search numbers against."""
    rows = [
        _message(1, Role.USER, [text_block("první")]),
        _message(2, Role.TOOL, [tool_result_block("call_a1", [_item(1)])]),
        _message(3, Role.ASSISTANT, [text_block("odpověď [1]")]),
        _message(4, Role.USER, [text_block("druhý")]),
        _message(5, Role.TOOL, [tool_result_block("call_a2", [_item(2)])]),
        _message(6, Role.ASSISTANT, [text_block("odpověď [2]")]),
    ]

    assert sorted(offered_items(rows)) == [1, 2]


def test_replay_keeps_the_tool_result_of_the_current_turn() -> None:
    """Without it the model has nothing to answer from."""
    rows = [
        _message(1, Role.USER, [text_block("dotaz")]),
        _message(2, Role.ASSISTANT, blocks_from(_tool_call_message())),
        _message(3, Role.TOOL, [tool_result_block("call_a1", [_item(1)])]),
    ]

    replayed = to_langchain(rows, render=_render)

    assert [type(message).__name__ for message in replayed] == [
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
    ]
    assert replayed[1].tool_calls


def test_an_orphaned_question_is_not_replayed() -> None:
    """An interrupted turn leaves a user row with no answer. Sending it would
    put two user messages next to each other."""
    rows = [
        _message(1, Role.USER, [text_block("přerušený dotaz")]),
        _message(2, Role.USER, [text_block("nový dotaz")]),
    ]

    replayed = to_langchain(rows, render=_render)

    assert [str(message.text) for message in replayed] == ["nový dotaz"]
