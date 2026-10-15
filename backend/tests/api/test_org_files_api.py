"""Org files: folders and the documents inside them, admin-only.

Ingestion is stubbed at the router boundary, same reasoning as the attachments
tests -- a real upload needs docling-serve and Qdrant.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from law_agent.api.routers.org_files import _content_disposition
from law_agent.db import DocumentRepository, FolderRepository, session_scope
from law_agent.documents.models import (
    Document,
    DocumentNotFoundError,
    DuplicateDocumentError,
    Folder,
    Namespace,
)


def _chat_attachment(filename: str = "priloha.pdf") -> Document:
    """A document living in a conversation, not a folder -- what the org-files
    endpoints must refuse to touch."""
    with session_scope() as session:
        document = DocumentRepository(session).create(
            namespace=Namespace.USER_FILES,
            filename=filename,
            mime="application/pdf",
            byte_size=3,
            blob_sha256=uuid4().hex * 2,
        )
        session.commit()
    return document


def _folder(name: str = "Vzory", parent_id: UUID | None = None) -> Folder:
    """A folder under a name unique to this call.

    Folder rows commit to the real test database and outlive the test (there
    is no per-test rollback the way the ``session`` fixture gives repository
    tests), so a literal, repeated name across tests in this module would
    collide with the root-name uniqueness constraint from a previous test's
    leftover row.
    """
    with session_scope() as session:
        folder = FolderRepository(session).create(f"{name}-{uuid4().hex[:8]}", parent_id=parent_id)
        session.commit()
    return folder


@pytest.fixture
def stub_ingest(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_ingest(data: bytes, **kwargs: Any) -> UUID:
        from law_agent.db import DocumentRepository
        from law_agent.documents.models import Namespace
        from law_agent.storage import get_blob_store

        calls.append({"data": data, **kwargs})
        sha256 = get_blob_store().put(data)
        with session_scope() as session:
            document = DocumentRepository(session).create(
                namespace=Namespace.ORG_FILES,
                filename=str(kwargs["filename"]),
                mime="application/pdf",
                byte_size=len(data),
                blob_sha256=sha256,
                folder_id=kwargs["folder_id"],
                uploaded_by=kwargs.get("uploaded_by"),
            )
            session.commit()
        return document.id

    monkeypatch.setattr("law_agent.api.routers.org_files.ingest_document", fake_ingest)
    return calls


def test_a_folder_is_created(client: TestClient, admin_headers: dict[str, str]) -> None:
    name = f"Vzory-{uuid4().hex[:8]}"

    response = client.post("/folders", headers=admin_headers, json={"name": name})

    assert response.status_code == 201
    assert response.json()["name"] == name


def test_a_duplicate_sibling_name_is_409(client: TestClient, admin_headers: dict[str, str]) -> None:
    name = f"Vzory-{uuid4().hex[:8]}"
    client.post("/folders", headers=admin_headers, json={"name": name})

    response = client.post("/folders", headers=admin_headers, json={"name": name})

    assert response.status_code == 409


def test_a_folder_is_renamed(client: TestClient, admin_headers: dict[str, str]) -> None:
    folder = _folder("Vzory")
    new_name = f"Šablony-{uuid4().hex[:8]}"

    response = client.patch(f"/folders/{folder.id}", headers=admin_headers, json={"name": new_name})

    assert response.status_code == 200
    assert response.json()["name"] == new_name


def test_a_folder_is_moved(client: TestClient, admin_headers: dict[str, str]) -> None:
    vzory = _folder("Vzory")
    klienti = _folder("Klienti")

    response = client.patch(
        f"/folders/{vzory.id}", headers=admin_headers, json={"parent_id": str(klienti.id)}
    )

    assert response.status_code == 200
    assert response.json()["parent_id"] == str(klienti.id)


def test_a_folder_is_moved_back_to_the_root(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    klienti = _folder("Klienti")
    vzory = _folder("Vzory", parent_id=klienti.id)

    response = client.patch(f"/folders/{vzory.id}", headers=admin_headers, json={"parent_id": None})

    assert response.status_code == 200
    assert response.json()["parent_id"] is None


def test_a_rename_without_parent_id_does_not_move_the_folder(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    klienti = _folder("Klienti")
    vzory = _folder("Vzory", parent_id=klienti.id)

    response = client.patch(
        f"/folders/{vzory.id}", headers=admin_headers, json={"name": f"Šablony-{uuid4().hex[:8]}"}
    )

    assert response.status_code == 200
    assert response.json()["parent_id"] == str(klienti.id)


def test_moving_a_folder_into_its_own_descendant_is_409(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    vzory = _folder("Vzory")
    smlouvy = _folder("Smlouvy", parent_id=vzory.id)

    response = client.patch(
        f"/folders/{vzory.id}", headers=admin_headers, json={"parent_id": str(smlouvy.id)}
    )

    assert response.status_code == 409


def test_folders_are_listed_by_parent(client: TestClient, admin_headers: dict[str, str]) -> None:
    vzory = _folder("Vzory")
    smlouvy = _folder("Smlouvy", parent_id=vzory.id)
    klienti = _folder("Klienti")

    roots = client.get("/folders", headers=admin_headers).json()
    children = client.get(f"/folders?parent_id={vzory.id}", headers=admin_headers).json()

    root_ids = {item["id"] for item in roots}
    assert {str(vzory.id), str(klienti.id)} <= root_ids
    assert [item["id"] for item in children] == [str(smlouvy.id)]


def test_an_empty_folder_is_deleted(client: TestClient, admin_headers: dict[str, str]) -> None:
    folder = _folder("Vzory")

    response = client.delete(f"/folders/{folder.id}", headers=admin_headers)

    assert response.status_code == 204


def test_a_non_empty_folder_cannot_be_deleted(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    parent = _folder("Vzory")
    _folder("Smlouvy", parent_id=parent.id)

    response = client.delete(f"/folders/{parent.id}", headers=admin_headers)

    assert response.status_code == 409


def test_deleting_a_folder_removes_its_acl_rows(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """Deleting a folder must not leave orphaned rows in ``acl_entries`` --
    there is no FK cascade on ``resource_id``, so this is the service layer's
    job, exercised here end to end through the HTTP routes."""
    folder = _folder("Vzory")
    client.post(
        "/acl",
        headers=admin_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "user",
            "principal_id": str(uuid4()),
            "permission": "read",
        },
    )

    response = client.delete(f"/folders/{folder.id}", headers=admin_headers)
    listed = client.get(
        f"/acl?resource_type=folder&resource_id={folder.id}", headers=admin_headers
    ).json()

    assert response.status_code == 204
    assert listed == []


def test_a_member_gets_403_on_every_org_files_route(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    folder_id = uuid4()

    assert client.post("/folders", headers=member_headers, json={"name": "x"}).status_code == 403
    assert client.get("/folders", headers=member_headers).status_code == 403
    assert client.patch(f"/folders/{folder_id}", headers=member_headers, json={}).status_code == 403
    assert client.delete(f"/folders/{folder_id}", headers=member_headers).status_code == 403
    assert (
        client.post(
            f"/folders/{folder_id}/files",
            headers=member_headers,
            files={"file": ("x.pdf", b"x", "application/pdf")},
        ).status_code
        == 403
    )
    assert client.get(f"/folders/{folder_id}/files", headers=member_headers).status_code == 403
    assert client.delete(f"/org-files/{folder_id}", headers=member_headers).status_code == 403
    assert client.get(f"/org-files/{folder_id}/download", headers=member_headers).status_code == 403


def test_a_file_is_uploaded_into_a_folder(
    client: TestClient, admin_headers: dict[str, str], stub_ingest: list[dict[str, Any]]
) -> None:
    folder = _folder("Vzory")

    response = client.post(
        f"/folders/{folder.id}/files",
        headers=admin_headers,
        files={"file": ("smlouva.pdf", b"pdf-bytes", "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json()["filename"] == "smlouva.pdf"
    assert stub_ingest[0]["folder_id"] == folder.id


def test_a_duplicate_blob_in_the_same_folder_is_409(
    client: TestClient, admin_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder("Vzory")

    def failing(*args: Any, **kwargs: Any) -> UUID:  # noqa: ARG001
        msg = "already in this folder"
        raise DuplicateDocumentError(msg)

    monkeypatch.setattr("law_agent.api.routers.org_files.ingest_document", failing)

    response = client.post(
        f"/folders/{folder.id}/files",
        headers=admin_headers,
        files={"file": ("smlouva.pdf", b"pdf", "application/pdf")},
    )

    assert response.status_code == 409


@pytest.mark.usefixtures("stub_ingest")
def test_files_are_listed_by_folder(client: TestClient, admin_headers: dict[str, str]) -> None:
    folder = _folder("Vzory")
    client.post(
        f"/folders/{folder.id}/files",
        headers=admin_headers,
        files={"file": ("smlouva.pdf", b"pdf", "application/pdf")},
    )

    response = client.get(f"/folders/{folder.id}/files", headers=admin_headers)

    assert response.status_code == 200
    assert [item["filename"] for item in response.json()] == ["smlouva.pdf"]


@pytest.mark.usefixtures("stub_ingest")
def test_a_file_is_deleted(
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deleted: list[UUID] = []
    monkeypatch.setattr(
        "law_agent.api.routers.org_files.delete_document",
        lambda document_id: deleted.append(document_id),
    )
    folder = _folder("Vzory")
    upload = client.post(
        f"/folders/{folder.id}/files",
        headers=admin_headers,
        files={"file": ("smlouva.pdf", b"pdf", "application/pdf")},
    ).json()

    response = client.delete(f"/org-files/{upload['id']}", headers=admin_headers)

    assert response.status_code == 204
    assert deleted == [UUID(upload["id"])]


def test_a_chat_attachment_cannot_be_deleted_through_org_files(
    client: TestClient, admin_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted: list[UUID] = []
    monkeypatch.setattr(
        "law_agent.api.routers.org_files.delete_document",
        lambda document_id: deleted.append(document_id),
    )
    attachment = _chat_attachment()

    response = client.delete(f"/org-files/{attachment.id}", headers=admin_headers)

    assert response.status_code == 404
    assert deleted == []


def test_a_chat_attachment_cannot_be_downloaded_through_org_files(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    attachment = _chat_attachment()

    response = client.get(f"/org-files/{attachment.id}/download", headers=admin_headers)

    assert response.status_code == 404


def test_a_multimedia_upload_is_415(
    client: TestClient, admin_headers: dict[str, str], stub_ingest: list[dict[str, Any]]
) -> None:
    folder = _folder("Vzory")

    response = client.post(
        f"/folders/{folder.id}/files",
        headers=admin_headers,
        files={"file": ("zaznam.mp4", b"video-bytes", "video/mp4")},
    )

    assert response.status_code == 415
    assert stub_ingest == []


def test_deleting_an_unknown_file_is_404(
    client: TestClient, admin_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        msg = "no document"
        raise DocumentNotFoundError(msg)

    monkeypatch.setattr("law_agent.api.routers.org_files.delete_document", failing)

    response = client.delete(f"/org-files/{uuid4()}", headers=admin_headers)

    assert response.status_code == 404


@pytest.mark.usefixtures("stub_ingest")
def test_a_file_is_downloaded(client: TestClient, admin_headers: dict[str, str]) -> None:
    folder = _folder("Vzory")
    upload = client.post(
        f"/folders/{folder.id}/files",
        headers=admin_headers,
        files={"file": ("smlouva.pdf", b"pdf-bytes", "application/pdf")},
    ).json()

    response = client.get(f"/org-files/{upload['id']}/download", headers=admin_headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="smlouva.pdf"' in response.headers["content-disposition"]


@pytest.mark.usefixtures("stub_ingest")
def test_a_czech_filename_survives_the_download_header(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """The header value must stay latin-1: the exact name travels percent-encoded
    in ``filename*`` and the plain ``filename`` is an ASCII fallback."""
    folder = _folder("Vzory")
    upload = client.post(
        f"/folders/{folder.id}/files",
        headers=admin_headers,
        files={"file": ("žluťoučká smlouva.pdf", b"pdf-bytes", "application/pdf")},
    ).json()

    response = client.get(f"/org-files/{upload['id']}/download", headers=admin_headers)

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert 'filename="luouk smlouva.pdf"' in disposition
    assert "filename*=UTF-8''%C5%BElu%C5%A5ou%C4%8Dk%C3%A1%20smlouva.pdf" in disposition


def test_the_disposition_header_neutralises_quotes_and_control_characters() -> None:
    """Quotes would break out of the quoted string and CR/LF would split the
    header; multipart clients escape them upstream, so the guard is unit-tested
    here rather than through an upload."""
    disposition = _content_disposition('a"b\r\nc.pdf')

    assert 'filename="abc.pdf"' in disposition
    assert "filename*=UTF-8''a%22b%0D%0Ac.pdf" in disposition
