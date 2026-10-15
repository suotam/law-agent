"""The only module that knows what a LangChain message looks like.

A serialized LangChain message is deliberately *not* what gets stored. It
looks like a zero-cost translation, but it ties the schema to a library format
that moves between versions and leaves the database unreadable without
LangChain. The stored shape is ours; this module is the seam.

Recording and replay are also not the same thing. A past turn replays whole --
its ``tool_use``, its ``tool_result`` and its answer -- but the result is cut
down to the items that turn's answer actually cited. Everything else was
offered and ignored, and carrying it forward would fill the context with
material no answer stands on.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from law_agent.chain.citations import used_refs
from law_agent.chain.prompt import NOTHING_CITED
from law_agent.conversations.models import Message, Role, SourceItem

TEXT = "text"
REASONING = "reasoning"
TOOL_USE = "tool_use"
TOOL_RESULT = "tool_result"

# What langchain-core 1.5.2 calls the same thing. The two names are the whole
# reason this translation exists; keeping ours means a library rename is a
# change here and nowhere else.
_LC_TOOL_CALL = "tool_call"

Renderer = Callable[[Sequence[SourceItem], Collection[int]], str]
"""Renders a tool result: the items to show, and the refs already in context."""


def text_block(text: str) -> dict[str, Any]:
    return {"type": TEXT, "text": text}


def tool_result_block(tool_call_id: str, items: Sequence[SourceItem]) -> dict[str, Any]:
    """The stored result of one tool call.

    ``tool_call_id`` sits inside the block rather than in a column: nothing
    joins on it, because pairing a call with its result is only needed inside
    the running turn, which the orchestration holds in memory.
    """
    return {
        "type": TOOL_RESULT,
        "tool_call_id": tool_call_id,
        "items": [item.model_dump() for item in items],
    }


def blocks_from(message: BaseMessage) -> list[dict[str, Any]]:
    """Stored blocks for a message the model produced or the user typed.

    Tool results are not built from a ``ToolMessage``: the message only carries
    the rendered text, while the archive stores the items behind it. Use
    :func:`tool_result_block` for those.
    """
    blocks: list[dict[str, Any]] = []
    for block in message.content_blocks:
        kind = block.get("type")
        if kind == TEXT:
            blocks.append(text_block(str(block.get("text", ""))))
        elif kind == REASONING:
            extras = block.get("extras") or {}
            blocks.append(
                {
                    "type": REASONING,
                    "reasoning": str(block.get("reasoning", "")),
                    "signature": str(extras.get("signature", "")),
                }
            )
        elif kind == _LC_TOOL_CALL:
            blocks.append(
                {
                    "type": TOOL_USE,
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "args": block.get("args") or {},
                }
            )
    return blocks


def turns(messages: Sequence[Message]) -> list[list[Message]]:
    """Split a conversation at every user row.

    A turn is one question and everything produced in answer to it.
    """
    grouped: list[list[Message]] = []
    for message in messages:
        if message.role is Role.USER or not grouped:
            grouped.append([])
        grouped[-1].append(message)
    return grouped


def offered_items(messages: Sequence[Message]) -> dict[int, SourceItem]:
    """Everything the tools offered in these messages, indexed by ``ref``."""
    items: dict[int, SourceItem] = {}
    for message in messages:
        if message.role is not Role.TOOL:
            continue
        for block in message.blocks:
            if block.get("type") != TOOL_RESULT:
                continue
            for raw in block.get("items", []):
                item = SourceItem.model_validate(raw)
                items[item.ref] = item
    return items


def carried_refs(messages: Sequence[Message]) -> set[int]:
    """Refs whose text is live in the replayed context.

    A ref is live once some answer cited it: that is exactly what survives the
    filtering below, so a new search finding the same chunk need only point at
    it rather than print it again.
    """
    offered = set(offered_items(messages))
    return {ref for turn in turns(messages) for ref in _cited_in(turn, offered)}


def to_langchain(messages: Sequence[Message], *, render: Renderer) -> list[BaseMessage]:
    """The conversation as the model should see it.

    Args:
        messages: The stored rows, in ``seq`` order.
        render: Turns a turn's items into the text of a tool message. Passed in
            so this module stays free of prompt formatting.
    """
    grouped = turns(messages)
    offered = set(offered_items(messages))
    replayed: list[BaseMessage] = []
    carried: set[int] = set()
    for index, turn in enumerate(grouped):
        is_current = index == len(grouped) - 1
        # A turn that never got past the question is the residue of an
        # interrupted request; only the one being asked right now may look
        # like that.
        if len(turn) == 1 and turn[0].role is Role.USER and not is_current:
            continue
        cited = _cited_in(turn, offered)
        # The current turn is not cut down: its answer is what is being written
        # right now, so nothing has cited anything yet.
        replayed.extend(
            _replay_turn(turn, render=render, carried=carried, keep=None if is_current else cited)
        )
        carried |= cited
    return replayed


def _cited_in(turn: Sequence[Message], offered: Collection[int]) -> set[int]:
    """Refs the assistant used in this turn, hallucinated ones dropped."""
    return {
        ref
        for message in turn
        if message.role is Role.ASSISTANT
        for ref in used_refs(_text_of(message), offered)
    }


def _replay_turn(
    turn: Sequence[Message],
    *,
    render: Renderer,
    carried: Collection[int],
    keep: Collection[int] | None,
) -> list[BaseMessage]:
    replayed: list[BaseMessage] = []
    for message in turn:
        if message.role is Role.USER:
            replayed.append(HumanMessage(_text_of(message)))
        elif message.role is Role.ASSISTANT:
            replayed.append(_assistant(message))
        else:
            replayed.extend(_tool_messages(message, render=render, carried=carried, keep=keep))
    return replayed


def _assistant(message: Message) -> AIMessage:
    # Spelled as LangChain declares the parameter: ``list`` is invariant, so a
    # narrower list[dict[...]] would not be assignable to it.
    content: list[str | dict[Any, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    for block in message.blocks:
        if block.get("type") == TEXT:
            content.append({"type": TEXT, "text": block.get("text", "")})
        elif block.get("type") == REASONING:
            content.append(
                {
                    "type": REASONING,
                    "reasoning": block.get("reasoning", ""),
                    "extras": {"signature": block.get("signature", "")},
                }
            )
        elif block.get("type") == TOOL_USE:
            tool_calls.append(
                {
                    "type": _LC_TOOL_CALL,
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "args": block.get("args") or {},
                }
            )
    return AIMessage(content=content, tool_calls=tool_calls)


def _tool_messages(
    message: Message,
    *,
    render: Renderer,
    carried: Collection[int],
    keep: Collection[int] | None,
) -> list[ToolMessage]:
    replayed: list[ToolMessage] = []
    for block in message.blocks:
        if block.get("type") != TOOL_RESULT:
            continue
        items = [SourceItem.model_validate(raw) for raw in block.get("items", [])]
        shown = items if keep is None else [item for item in items if item.ref in keep]
        # An empty result cannot be dropped: its tool_call_id is answered here
        # or the paired assistant message is rejected.
        content = NOTHING_CITED if items and not shown else render(shown, carried)
        replayed.append(ToolMessage(content=content, tool_call_id=str(block.get("tool_call_id"))))
    return replayed


def _text_of(message: Message) -> str:
    return "\n".join(
        str(block.get("text", "")) for block in message.blocks if block.get("type") == TEXT
    )
