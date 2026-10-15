"""The chat turn over HTTP.

``ask`` is stubbed: what the turn itself does is already covered in
``tests/test_conversations.py``, and what only HTTP can get wrong is the status
codes around the stream and the frames inside it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from law_agent.conversations.models import AttachmentNotFoundError, SourceItem
from law_agent.conversations.service import Answer

ITEM = SourceItem(ref=1, kind="law", label="§ 1829 obč. zák.", content={"text": "Spotřebitel…"})


@pytest.fixture
def stub_ask(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_ask(conversation_id: Any, question: str, **kwargs: Any) -> Answer:
        calls.append({"conversation_id": conversation_id, "question": question, **kwargs})
        return Answer(items=[ITEM], _pieces=iter(["Do 14 ", "dnů [1]."]))

    monkeypatch.setattr("law_agent.api.routers.conversations.ask", fake_ask)
    return calls


def _create(client: TestClient, headers: dict[str, str]) -> str:
    return client.post("/conversations", headers=headers, json={}).json()["id"]


def test_the_answer_streams_as_the_data_stream_protocol(
    client: TestClient, member_headers: dict[str, str], stub_ask: list[dict[str, Any]]
) -> None:
    conversation_id = _create(client, member_headers)

    response = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=member_headers,
        json={"question": "Kdy můžu odstoupit?"},
    )

    assert response.status_code == 200
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert '"type":"data-sources"' in body
    assert '"delta":"Do 14 "' in body
    assert body.rstrip().endswith("data: [DONE]")
    assert stub_ask[0]["question"] == "Kdy můžu odstoupit?"


def test_attachment_ids_are_passed_through(
    client: TestClient, member_headers: dict[str, str], stub_ask: list[dict[str, Any]]
) -> None:
    conversation_id = _create(client, member_headers)
    attachment_id = uuid4()

    client.post(
        f"/conversations/{conversation_id}/messages",
        headers=member_headers,
        json={"question": "Co je ve smlouvě?", "attachment_ids": [str(attachment_id)]},
    )

    assert stub_ask[0]["attachment_ids"] == [attachment_id]


def test_an_unknown_attachment_is_404_before_the_stream_starts(
    client: TestClient, member_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure happens while the status can still be set -- ``ask`` resolves
    its attachments before the first token."""

    def failing_ask(*args: Any, **kwargs: Any) -> Answer:  # noqa: ARG001
        msg = "no pending attachment"
        raise AttachmentNotFoundError(msg)

    monkeypatch.setattr("law_agent.api.routers.conversations.ask", failing_ask)
    conversation_id = _create(client, member_headers)

    response = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=member_headers,
        json={"question": "dotaz", "attachment_ids": [str(uuid4())]},
    )

    assert response.status_code == 404


def test_a_failure_mid_stream_is_a_200_with_an_error_part(
    client: TestClient, member_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def dying() -> Iterator[str]:
        yield "Do 14 "
        msg = "upstream died"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        "law_agent.api.routers.conversations.ask",
        lambda *args, **kwargs: Answer(items=[ITEM], _pieces=dying()),  # noqa: ARG005
    )
    conversation_id = _create(client, member_headers)

    response = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=member_headers,
        json={"question": "dotaz"},
    )

    assert response.status_code == 200
    assert '"type":"error"' in response.text
    assert "upstream died" not in response.text


def test_an_empty_question_is_422(
    client: TestClient, member_headers: dict[str, str], stub_ask: list[dict[str, Any]]
) -> None:
    conversation_id = _create(client, member_headers)

    response = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=member_headers,
        json={"question": ""},
    )

    assert response.status_code == 422
    assert stub_ask == []


def test_posting_into_someone_elses_conversation_is_404(
    client: TestClient,
    member_headers: dict[str, str],
    admin_headers: dict[str, str],
    stub_ask: list[dict[str, Any]],
) -> None:
    theirs = _create(client, admin_headers)

    response = client.post(
        f"/conversations/{theirs}/messages", headers=member_headers, json={"question": "dotaz"}
    )

    assert response.status_code == 404
    assert stub_ask == []


def test_user_id_is_threaded_to_ask(
    client: TestClient, member: Any, member_headers: dict[str, str], stub_ask: list[dict[str, Any]]
) -> None:
    conversation_id = _create(client, member_headers)

    client.post(
        f"/conversations/{conversation_id}/messages",
        headers=member_headers,
        json={"question": "dotaz"},
    )

    assert stub_ask[0]["user_id"] == member.id
