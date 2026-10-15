"""Conversation CRUD over HTTP: ownership, status codes, payload shape."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient


def _create(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/conversations", headers=headers, json={})
    assert response.status_code == 201
    return response.json()["id"]


def test_a_new_conversation_starts_empty_and_untitled(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    response = client.post("/conversations", headers=member_headers, json={})

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == ""
    assert body["id"]


def test_the_list_holds_only_my_conversations(
    client: TestClient, member_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    mine = _create(client, member_headers)
    _create(client, admin_headers)

    response = client.get("/conversations", headers=member_headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [mine]


def test_a_deleted_conversation_leaves_the_list(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    conversation_id = _create(client, member_headers)

    deleted = client.delete(f"/conversations/{conversation_id}", headers=member_headers)
    assert deleted.status_code == 204

    assert client.get("/conversations", headers=member_headers).json() == []


def test_a_conversation_reports_the_scope_it_was_created_with(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    created = client.post(
        "/conversations", headers=member_headers, json={"scope": ["laws"], "limit": 3}
    )
    conversation_id = created.json()["id"]

    response = client.get(f"/conversations/{conversation_id}", headers=member_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == conversation_id
    assert body["scope"] == ["laws"]
    assert body["limit"] == 3


def test_a_conversation_created_without_a_scope_reports_the_defaults(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    conversation_id = _create(client, member_headers)

    body = client.get(f"/conversations/{conversation_id}", headers=member_headers).json()

    assert body["scope"] == ["laws", "org_files"]
    assert body["limit"] == 10


def test_an_unknown_source_in_the_scope_is_422(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    """A typo used to be stored and then silently retrieve nothing."""
    response = client.post(
        "/conversations", headers=member_headers, json={"scope": ["laws", "zakony"]}
    )

    assert response.status_code == 422


def test_a_deleted_conversation_cannot_be_fetched(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    conversation_id = _create(client, member_headers)
    client.delete(f"/conversations/{conversation_id}", headers=member_headers)

    response = client.get(f"/conversations/{conversation_id}", headers=member_headers)

    assert response.status_code == 404


def test_someone_elses_conversation_is_404_not_403(
    client: TestClient, member_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    """404 rather than 403: 403 would confirm that this id exists."""
    theirs = _create(client, admin_headers)

    assert client.get(f"/conversations/{theirs}", headers=member_headers).status_code == 404
    assert client.delete(f"/conversations/{theirs}", headers=member_headers).status_code == 404


def test_an_unknown_conversation_is_404(client: TestClient, member_headers: dict[str, str]) -> None:
    assert client.get(f"/conversations/{uuid4()}", headers=member_headers).status_code == 404
    assert client.delete(f"/conversations/{uuid4()}", headers=member_headers).status_code == 404


def test_conversations_need_a_token(client: TestClient) -> None:
    assert client.get("/conversations").status_code == 401
    assert client.post("/conversations", json={}).status_code == 401
