"""Tests for the two model calls of one turn, against a scripted fake model."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from law_agent.chain.answer import request_search, stream_answer


class ScriptedChatModel(BaseChatModel):
    """A fake model that hands back prepared messages and records the input.

    ``GenericFakeChatModel`` cannot be used here: its ``bind_tools`` raises
    ``NotImplementedError``, and binding the tool is exactly what is under
    test. ``bind_tools`` returns ``self`` so that the recorded state survives
    the binding.
    """

    responses: list[AIMessage]
    received: list[list[BaseMessage]] = Field(default_factory=list)
    tool_choices: list[Any] = Field(default_factory=list)
    tools: list[Any] = Field(default_factory=list)
    bind_kwargs: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(  # type: ignore[override]
        self,
        tools: Sequence[Any],
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> ScriptedChatModel:
        self.tools.append(list(tools))
        self.tool_choices.append(tool_choice)
        self.bind_kwargs.append(kwargs)
        return self

    def _next(self, messages: Sequence[BaseMessage]) -> AIMessage:
        self.received.append(list(messages))
        return self.responses.pop(0)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Any = None,  # noqa: ARG002
        run_manager: Any = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Any = None,  # noqa: ARG002
        run_manager: Any = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> Iterator[ChatGenerationChunk]:
        message = self._next(messages)
        for word in str(message.text).split(" "):
            yield ChatGenerationChunk(message=AIMessageChunk(content=word + " "))


def _tool_call(query: str = "odstoupení od smlouvy spotřebitel") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "search", "args": {"query": query}, "id": "call_a1", "type": "tool_call"}
        ],
    )


def test_the_search_round_is_forced_and_returns_the_tool_call() -> None:
    """Without ``required`` the model answers from memory whenever it feels
    confident, which is the one thing this assistant must not do."""
    model = ScriptedChatModel(responses=[_tool_call()])

    message = request_search([HumanMessage("Kdy můžu odstoupit?")], model=model)

    assert message.tool_calls[0]["args"]["query"] == "odstoupení od smlouvy spotřebitel"
    assert model.tool_choices == ["required"]
    assert model.tools[0][0]["function"]["name"] == "search"


def test_the_search_round_disallows_parallel_tool_calls() -> None:
    """A model that returns two ``search`` calls in one turn breaks the
    archive replay: only the first gets a matching ToolMessage. Forcing
    ``parallel_tool_calls=False`` keeps that from happening."""
    model = ScriptedChatModel(responses=[_tool_call()])

    request_search([HumanMessage("dotaz")], model=model)

    assert model.bind_kwargs[0]["parallel_tool_calls"] is False


def test_the_answer_round_disallows_parallel_tool_calls() -> None:
    model = ScriptedChatModel(responses=[AIMessage("odpověď")])
    history = [
        HumanMessage("dotaz"),
        _tool_call(),
        ToolMessage(content="[1] § 1829", tool_call_id="call_a1"),
    ]

    list(stream_answer(history, model=model))

    assert model.bind_kwargs[0]["parallel_tool_calls"] is False


def test_the_search_round_is_prefixed_with_the_system_prompt() -> None:
    model = ScriptedChatModel(responses=[_tool_call()])

    request_search([HumanMessage("dotaz")], model=model)

    assert isinstance(model.received[0][0], SystemMessage)


def test_a_model_that_refuses_to_search_is_an_error() -> None:
    """Answering without material would produce uncited claims; failing loudly
    leaves the question in the archive and nothing else."""
    model = ScriptedChatModel(responses=[AIMessage("Podle mě do 14 dnů.")])

    with pytest.raises(ValueError, match="search"):
        request_search([HumanMessage("dotaz")], model=model)


def test_the_answer_round_streams_and_may_not_call_tools_again() -> None:
    model = ScriptedChatModel(responses=[AIMessage("Do 14 dnů [1].")])
    history = [
        HumanMessage("Kdy můžu odstoupit?"),
        _tool_call(),
        ToolMessage(content="[1] § 1829\nSpotřebitel…", tool_call_id="call_a1"),
    ]

    pieces = list(stream_answer(history, model=model))

    assert len(pieces) > 1
    assert "".join(pieces).strip() == "Do 14 dnů [1]."
    assert model.tool_choices == ["none"]


def test_the_answer_round_sees_the_tool_result() -> None:
    model = ScriptedChatModel(responses=[AIMessage("odpověď")])
    history = [
        HumanMessage("dotaz"),
        _tool_call(),
        ToolMessage(content="[1] § 1829\nSpotřebitel má právo…", tool_call_id="call_a1"),
    ]

    list(stream_answer(history, model=model))

    sent = model.received[0]
    assert isinstance(sent[0], SystemMessage)
    assert sent[1:] == history
