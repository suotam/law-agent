"""Replaying a stored conversation in the shape the FE's useChat expects."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from law_agent.conversations.blocks import text_block, tool_result_block
from law_agent.conversations.models import Role, SourceItem
from law_agent.db import DocumentRepository, MessageRepository, session_scope
from law_agent.documents.models import Namespace

ITEM = SourceItem(ref=1, kind="law", label="§ 1829 obč. zák.", content={"text": "Spotřebitel…"})


def _upload(conversation_id: UUID, filename: str, *, message_id: UUID | None = None) -> UUID:
    """A file in this conversation, bound to a message or still pending."""
    with session_scope() as session:
        document = DocumentRepository(session).create(
            namespace=Namespace.USER_FILES,
            filename=filename,
            mime="application/pdf",
            byte_size=1024,
            blob_sha256=uuid4().hex * 2,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        session.commit()
    return document.id


def _user_message_id(conversation_id: UUID) -> UUID:
    with session_scope() as session:
        messages = MessageRepository(session).list(conversation_id)
    return next(message.id for message in messages if message.role is Role.USER)


@pytest.fixture
def stored_turn(client: TestClient, member_headers: dict[str, str]) -> UUID:
    """One archived turn: question, tool call, tool result, answer -- exactly
    what ``ask`` writes."""
    created = client.post("/conversations", headers=member_headers, json={})
    conversation_id = UUID(created.json()["id"])
    with session_scope() as session:
        messages = MessageRepository(session)
        messages.append(conversation_id, role=Role.USER, blocks=[text_block("Kdy odstoupit?")])
        messages.append(
            conversation_id,
            role=Role.ASSISTANT,
            blocks=[{"type": "tool_use", "id": "call_a1", "name": "search", "args": {}}],
        )
        messages.append(
            conversation_id, role=Role.TOOL, blocks=[tool_result_block("call_a1", [ITEM])]
        )
        messages.append(conversation_id, role=Role.ASSISTANT, blocks=[text_block("Do 14 dnů [1].")])
        session.commit()
    return conversation_id


def test_history_replays_the_question_and_the_answer(
    client: TestClient, member_headers: dict[str, str], stored_turn: UUID
) -> None:
    response = client.get(f"/conversations/{stored_turn}/history", headers=member_headers)

    assert response.status_code == 200
    messages: list[dict[str, Any]] = response.json()
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["parts"] == [{"type": "text", "text": "Kdy odstoupit?"}]
    assert messages[1]["parts"][0] == {"type": "text", "text": "Do 14 dnů [1]."}


def test_the_answers_sources_come_back_as_a_data_part(
    client: TestClient, member_headers: dict[str, str], stored_turn: UUID
) -> None:
    """The same part the live stream sends, so the FE renders citations the one
    way whether the turn is being streamed or replayed."""
    messages = client.get(f"/conversations/{stored_turn}/history", headers=member_headers).json()

    sources = messages[1]["parts"][1]
    assert sources["type"] == "data-sources"
    assert sources["data"]["items"][0]["label"] == "§ 1829 obč. zák."


def test_the_search_round_is_not_replayed_as_a_message(
    client: TestClient, member_headers: dict[str, str], stored_turn: UUID
) -> None:
    """``tool_use`` and ``tool_result`` rows are machinery, not chat."""
    messages = client.get(f"/conversations/{stored_turn}/history", headers=member_headers).json()

    assert len(messages) == 2


def test_an_empty_conversation_has_an_empty_history(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    conversation_id = client.post("/conversations", headers=member_headers, json={}).json()["id"]

    response = client.get(f"/conversations/{conversation_id}/history", headers=member_headers)

    assert response.status_code == 200
    assert response.json() == []


def test_a_question_carries_the_files_it_was_sent_with(
    client: TestClient, member_headers: dict[str, str], stored_turn: UUID
) -> None:
    """What the FE cannot reconstruct after a reload: the upload responses it
    held in component state are gone, so the archive has to say it."""
    message_id = _user_message_id(stored_turn)
    attachment_id = _upload(stored_turn, "smlouva.pdf", message_id=message_id)

    messages = client.get(f"/conversations/{stored_turn}/history", headers=member_headers).json()

    attachments = messages[0]["parts"][0]
    assert attachments["type"] == "data-attachments"
    assert attachments["data"]["items"] == [
        {
            "id": str(attachment_id),
            "filename": "smlouva.pdf",
            "mime": "application/pdf",
            "byte_size": 1024,
        }
    ]
    assert messages[0]["parts"][1] == {"type": "text", "text": "Kdy odstoupit?"}


def test_a_question_sent_without_files_has_no_attachments_part(
    client: TestClient, member_headers: dict[str, str], stored_turn: UUID
) -> None:
    messages = client.get(f"/conversations/{stored_turn}/history", headers=member_headers).json()

    assert messages[0]["parts"] == [{"type": "text", "text": "Kdy odstoupit?"}]


def test_an_attachment_no_message_has_used_stays_out_of_the_history(
    client: TestClient, member_headers: dict[str, str], stored_turn: UUID
) -> None:
    """An upload with no message yet is the state of a draft, not of the
    archive: it belongs to no turn and must not be shown against one."""
    _upload(stored_turn, "rozdelano.pdf")

    messages = client.get(f"/conversations/{stored_turn}/history", headers=member_headers).json()

    assert messages[0]["parts"] == [{"type": "text", "text": "Kdy odstoupit?"}]


def test_someone_elses_history_is_404(
    client: TestClient, member_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    theirs = client.post("/conversations", headers=admin_headers, json={}).json()["id"]

    assert client.get(f"/conversations/{theirs}/history", headers=member_headers).status_code == 404
