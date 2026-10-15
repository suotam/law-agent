"""The one place that talks to the chat model: two rounds, one turn.

Round one is forced to call ``search`` (``tool_choice="required"``); round two
is forbidden from calling anything (``tool_choice="none"``) and streams the
answer. Dropping those two constraints and wrapping this in a ``while`` is the
whole of the move to an agent loop -- neither the schema nor the stored shape
changes with it.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from law_agent.chain.prompt import SYSTEM_PROMPT
from law_agent.chain.tools import SEARCH_TOOL, SEARCH_TOOL_NAME
from law_agent.core.llm import get_llm


def request_search(
    messages: Sequence[BaseMessage], *, model: BaseChatModel | None = None
) -> AIMessage:
    """Let the model write its own retrieval query.

    Args:
        messages: The conversation so far, ending with the current question.
        model: Injection point for tests; production callers omit it.

    Returns:
        The assistant message carrying the ``search`` call -- and possibly
        reasoning and text alongside it, which are stored as they came.

    Raises:
        ValueError: The model answered instead of searching. Letting that
            through would produce an answer with no material behind it.
    """
    chat = (model or get_llm()).bind_tools(
        [SEARCH_TOOL], tool_choice="required", parallel_tool_calls=False
    )
    message = chat.invoke(_with_system(messages))
    if not any(call["name"] == SEARCH_TOOL_NAME for call in message.tool_calls):
        msg = f"the model returned no {SEARCH_TOOL_NAME} call"
        raise ValueError(msg)
    return message


def stream_answer(
    messages: Sequence[BaseMessage], *, model: BaseChatModel | None = None
) -> Iterator[str]:
    """Stream the answer, grounded in the tool results already in ``messages``.

    Args:
        messages: The conversation including this turn's tool call and its
            result. The material is no longer passed separately -- it reaches
            the model the way it will be replayed.
        model: Injection point for tests; production callers omit it.

    Yields:
        Text pieces, in order.
    """
    chat = (model or get_llm()).bind_tools(
        [SEARCH_TOOL], tool_choice="none", parallel_tool_calls=False
    )
    for piece in chat.stream(_with_system(messages)):
        text = str(piece.text)
        if text:
            yield text


def _with_system(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    return [SystemMessage(SYSTEM_PROMPT), *messages]
