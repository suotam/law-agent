"""Uploading and removing a freestanding attachment.

``add_attachment``/``remove_attachment`` are stubbed at the router boundary: a
real upload needs docling-serve and Qdrant, and what HTTP can get wrong is
multipart handling, ownership and status codes. Conversation creation with
``title``/``attachment_ids`` runs against the real service and test database.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from law_agent.conversations.models import AttachmentNotFoundError
from law_agent.db import DocumentRepository, session_scope
from law_agent.documents.models import Document, Namespace


def _store(filename: str, data: bytes, *, conversation_id: UUID | None = None) -> Document:
    with session_scope() as session:
        document = DocumentRepository(session).create(
            namespace=Namespace.USER_FILES,
            filename=filename,
            mime="application/pdf",
            byte_size=len(data),
            blob_sha256=uuid4().hex * 2,
            conversation_id=conversation_id,
        )
        session.commit()
    return document


@pytest.fixture
def stub_add(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_add(data: bytes, **kwargs: Any) -> Document:
        calls.append({"data": data, **kwargs})
        return _store(str(kwargs["filename"]), data, conversation_id=kwargs.get("conversation_id"))

    monkeypatch.setattr("law_agent.api.routers.attachments.add_attachment", fake_add)
    return calls


def _create(client: TestClient, headers: dict[str, str]) -> str:
    return client.post("/conversations", headers=headers, json={}).json()["id"]


def test_an_upload_with_no_conversation_returns_an_unbound_document(
    client: TestClient, member_headers: dict[str, str], stub_add: list[dict[str, Any]]
) -> None:
    response = client.post(
        "/attachments",
        headers=member_headers,
        files={"file": ("smlouva.pdf", b"pdf-bytes", "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "smlouva.pdf"
    assert body["byte_size"] == len(b"pdf-bytes")
    assert body["mime"] == "application/pdf"
    assert stub_add[0]["data"] == b"pdf-bytes"
    assert stub_add[0].get("conversation_id") is None


def test_an_upload_with_a_conversation_binds_it_immediately(
    client: TestClient, member_headers: dict[str, str], stub_add: list[dict[str, Any]]
) -> None:
    conversation_id = _create(client, member_headers)

    response = client.post(
        "/attachments",
        headers=member_headers,
        data={"conversation_id": conversation_id},
        files={"file": ("smlouva.pdf", b"pdf-bytes", "application/pdf")},
    )

    assert response.status_code == 201
    assert stub_add[0]["conversation_id"] == UUID(conversation_id)


def test_the_uploader_is_recorded(
    client: TestClient, member_headers: dict[str, str], member: Any, stub_add: list[dict[str, Any]]
) -> None:
    client.post(
        "/attachments",
        headers=member_headers,
        files={"file": ("smlouva.pdf", b"pdf", "application/pdf")},
    )

    assert stub_add[0]["uploaded_by"] == str(member.id)


def test_uploading_with_someone_elses_conversation_id_is_404(
    client: TestClient,
    member_headers: dict[str, str],
    admin_headers: dict[str, str],
    stub_add: list[dict[str, Any]],
) -> None:
    theirs = _create(client, admin_headers)

    response = client.post(
        "/attachments",
        headers=member_headers,
        data={"conversation_id": theirs},
        files={"file": ("x.pdf", b"pdf", "application/pdf")},
    )

    assert response.status_code == 404
    assert stub_add == []


def test_an_attachment_is_removed(
    client: TestClient, member_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    removed: list[tuple[UUID, str]] = []
    monkeypatch.setattr(
        "law_agent.api.routers.attachments.remove_attachment",
        lambda document_id, *, owner: removed.append((document_id, owner)),
    )
    attachment_id = uuid4()

    response = client.delete(f"/attachments/{attachment_id}", headers=member_headers)

    assert response.status_code == 204
    assert len(removed) == 1
    assert removed[0][0] == attachment_id


def test_removing_an_unknown_attachment_is_404(
    client: TestClient, member_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        msg = "no pending attachment"
        raise AttachmentNotFoundError(msg)

    monkeypatch.setattr("law_agent.api.routers.attachments.remove_attachment", failing)

    response = client.delete(f"/attachments/{uuid4()}", headers=member_headers)

    assert response.status_code == 404


def test_a_multimedia_upload_is_415(
    client: TestClient, member_headers: dict[str, str], stub_add: list[dict[str, Any]]
) -> None:
    for filename, mime in (("zaznam.mp4", "video/mp4"), ("diktat.mp3", "audio/mpeg")):
        response = client.post(
            "/attachments",
            headers=member_headers,
            files={"file": (filename, b"media-bytes", mime)},
        )
        assert response.status_code == 415

    assert stub_add == []


def test_an_oversized_upload_is_413(
    client: TestClient,
    member_headers: dict[str, str],
    stub_add: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("law_agent.api.uploads.MAX_UPLOAD_BYTES", 8)

    response = client.post(
        "/attachments",
        headers=member_headers,
        files={"file": ("smlouva.pdf", b"x" * 9, "application/pdf")},
    )

    assert response.status_code == 413
    assert stub_add == []


def test_a_conversation_limit_above_twenty_is_422(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    response = client.post("/conversations", headers=member_headers, json={"limit": 100})

    assert response.status_code == 422


def test_attachments_need_a_token(client: TestClient) -> None:
    response = client.post("/attachments", files={"file": ("x.pdf", b"pdf", "application/pdf")})

    assert response.status_code == 401


def test_creating_a_conversation_with_a_title_truncates_it(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    response = client.post("/conversations", headers=member_headers, json={"title": "x" * 200})

    assert response.status_code == 201
    assert len(response.json()["title"]) == 30


def test_creating_a_conversation_claims_its_attachment_ids(
    client: TestClient, member_headers: dict[str, str], member: Any
) -> None:
    with session_scope() as session:
        draft = DocumentRepository(session).create(
            namespace=Namespace.USER_FILES,
            filename="draft.pdf",
            mime="application/pdf",
            byte_size=3,
            blob_sha256=uuid4().hex * 2,
            uploaded_by=str(member.id),
        )
        session.commit()

    response = client.post(
        "/conversations",
        headers=member_headers,
        json={"attachment_ids": [str(draft.id)]},
    )

    assert response.status_code == 201
    conversation_id = response.json()["id"]
    with session_scope() as session:
        claimed = DocumentRepository(session).get(draft.id)
    assert claimed is not None
    assert str(claimed.conversation_id) == conversation_id


def test_creating_a_conversation_with_someone_elses_attachment_id_is_404_but_keeps_the_row(
    client: TestClient, member_headers: dict[str, str], admin: Any
) -> None:
    with session_scope() as session:
        draft = DocumentRepository(session).create(
            namespace=Namespace.USER_FILES,
            filename="draft.pdf",
            mime="application/pdf",
            byte_size=3,
            blob_sha256=uuid4().hex * 2,
            uploaded_by=str(admin.id),
        )
        session.commit()

    response = client.post(
        "/conversations",
        headers=member_headers,
        json={"attachment_ids": [str(draft.id)]},
    )

    assert response.status_code == 404
    conversations = client.get("/conversations", headers=member_headers).json()
    assert len(conversations) == 1  # the row committed before the claim failed
