"""The Vercel AI SDK data stream protocol, encoded by hand.

Hand-encoded because the FE's SDK is the only consumer and the format is small;
these tests are the contract, since a wrong part type fails silently in the
browser rather than loudly here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from law_agent.api.streaming import (
    UI_MESSAGE_STREAM_HEADERS,
    sources_part,
    ui_message_stream,
)
from law_agent.conversations.models import SourceItem
from law_agent.conversations.service import Answer

ITEM = SourceItem(ref=1, kind="law", label="§ 1829 obč. zák.", content={"text": "Spotřebitel…"})


def _parts(chunks: Iterator[str]) -> list[Any]:
    """Every SSE frame decoded; ``[DONE]`` kept as the literal string."""
    decoded: list[Any] = []
    for chunk in chunks:
        assert chunk.startswith("data: ")
        assert chunk.endswith("\n\n")
        payload = chunk[len("data: ") : -2]
        decoded.append(payload if payload == "[DONE]" else json.loads(payload))
    return decoded


def _answer(pieces: Iterator[str]) -> Answer:
    return Answer(items=[ITEM], _pieces=pieces)


def test_the_protocol_header_is_the_one_the_sdk_negotiates_on() -> None:
    assert UI_MESSAGE_STREAM_HEADERS["x-vercel-ai-ui-message-stream"] == "v1"
    assert UI_MESSAGE_STREAM_HEADERS["content-type"] == "text/event-stream"


def test_a_whole_answer_streams_start_sources_text_finish() -> None:
    parts = _parts(ui_message_stream(_answer(iter(["Do 14 ", "dnů [1]."])), message_id="m1"))

    assert parts[0] == {"type": "start", "messageId": "m1"}
    assert parts[1] == sources_part([ITEM])
    assert parts[2] == {"type": "text-start", "id": "answer"}
    assert parts[3] == {"type": "text-delta", "id": "answer", "delta": "Do 14 "}
    assert parts[4] == {"type": "text-delta", "id": "answer", "delta": "dnů [1]."}
    assert parts[5] == {"type": "text-end", "id": "answer"}
    assert parts[6] == {"type": "finish"}
    assert parts[7] == "[DONE]"


def test_the_sources_arrive_before_the_first_token() -> None:
    """The FE renders the source panel above the answer, so the citations have
    to be in the stream before any text."""
    parts = _parts(ui_message_stream(_answer(iter(["text"])), message_id="m1"))

    assert parts[1]["type"] == "data-sources"
    assert parts[1]["data"]["items"][0]["label"] == "§ 1829 obč. zák."


def test_a_failure_mid_stream_becomes_an_error_part_not_an_exception() -> None:
    """By the time generation dies the headers are long gone, so the status can
    no longer change; the protocol's own error part is the only channel left."""

    def dying() -> Iterator[str]:
        yield "Do 14 "
        msg = "upstream died"
        raise RuntimeError(msg)

    parts = _parts(ui_message_stream(_answer(dying()), message_id="m1"))

    assert parts[3] == {"type": "text-delta", "id": "answer", "delta": "Do 14 "}
    assert parts[4] == {"type": "text-end", "id": "answer"}
    assert parts[5]["type"] == "error"
    assert "upstream died" not in parts[5]["errorText"]
    assert parts[6] == {"type": "finish"}
    assert parts[7] == "[DONE]"


def test_czech_text_is_not_escaped_into_ascii() -> None:
    chunk = next(iter(ui_message_stream(_answer(iter(["příliš"])), message_id="m1")))

    assert "\\u" not in chunk
