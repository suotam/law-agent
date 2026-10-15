"""The Vercel AI SDK data stream protocol.

The data stream protocol rather than the plain text one: the chain already
produces numbered ``SourceItem`` citations, and this way they reach the FE as a
structured part instead of ``[n]`` markers it would have to parse back out of
the text.

Encoded by hand -- the format is a handful of JSON objects over SSE, and pulling
in a dependency to write ``data: {...}`` would not earn its keep.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from typing import Any

from law_agent.conversations.models import SourceItem
from law_agent.conversations.service import Answer
from law_agent.documents.models import Document

logger = logging.getLogger(__name__)

UI_MESSAGE_STREAM_HEADERS = {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    "connection": "keep-alive",
    # How the SDK's transport recognises this protocol. Without it the client
    # refuses the response.
    "x-vercel-ai-ui-message-stream": "v1",
    "x-accel-buffering": "no",
}

_TEXT_ID = "answer"
"""One text part per turn, so a fixed id is enough."""

_ERROR_TEXT = "Odpověď se nepodařilo dokončit."
"""Shown in the chat, so Czech -- and deliberately says nothing about why."""


def sources_part(items: Sequence[SourceItem]) -> dict[str, Any]:
    """The turn's citations as a custom data part.

    ``data-sources`` rather than the protocol's ``source-document``: that part
    carries a title and a media type, while what the FE resolves a ``[n]`` mark
    against is our ``ref``, ``kind`` and ``content``.
    """
    return {"type": "data-sources", "data": {"items": [item.model_dump() for item in items]}}


def attachments_part(documents: Sequence[Document]) -> dict[str, Any]:
    """The files a question was sent with.

    Only ever part of a replayed question, never of the stream: a ``data-*``
    frame lands on the message being streamed, which is the answer, while these
    belong to the message that asked. The FE builds the same part itself for a
    live turn, out of what the upload calls returned.
    """
    return {
        "type": "data-attachments",
        "data": {
            "items": [
                {
                    "id": str(document.id),
                    "filename": document.filename,
                    "mime": document.mime,
                    "byte_size": document.byte_size,
                }
                for document in documents
            ]
        },
    }


def ui_message_stream(answer: Answer, *, message_id: str) -> Iterator[str]:
    """One turn as SSE frames.

    A failure partway through is an error *part*: the headers went out with the
    first frame, so the HTTP status can no longer say anything.
    """
    yield _frame({"type": "start", "messageId": message_id})
    yield _frame(sources_part(answer.items))
    yield _frame({"type": "text-start", "id": _TEXT_ID})

    failed = False
    try:
        for piece in answer:
            yield _frame({"type": "text-delta", "id": _TEXT_ID, "delta": piece})
    except Exception:
        logger.exception("answer stream failed for message %s", message_id)
        failed = True

    # Closed even on failure: the client keeps the part in a streaming state
    # otherwise, and the partial text should settle as what was received.
    yield _frame({"type": "text-end", "id": _TEXT_ID})
    if failed:
        yield _frame({"type": "error", "errorText": _ERROR_TEXT})
    yield _frame({"type": "finish"})
    yield "data: [DONE]\n\n"


def _frame(part: dict[str, Any]) -> str:
    # ensure_ascii=False: the answers are Czech, and escaping them to \uXXXX
    # triples the bytes on the wire for no reader's benefit.
    return f"data: {json.dumps(part, ensure_ascii=False, separators=(',', ':'))}\n\n"
