"""Member-facing org files views and actions: no capability required,
strictly scoped to the caller's own accessible set (access/member_view.py,
access/service.py's effective_permission)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from law_agent.access.models import Permission, PrincipalType, ResourceType
from law_agent.access.service import accessible_org_folder_ids
from law_agent.db import AclRepository, DocumentRepository, FolderRepository, session_scope
from law_agent.documents.models import Namespace
from law_agent.storage import get_blob_store
from law_agent.users.models import User


def _grant_folder(user: User, folder_id: UUID, permission: Permission = Permission.READ) -> None:
    with session_scope() as session:
        AclRepository(session).upsert(
            resource_type=ResourceType.FOLDER,
            resource_id=folder_id,
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            permission=permission,
        )
        session.commit()


def _grant_document(user: User, document_id: UUID) -> None:
    with session_scope() as session:
        AclRepository(session).upsert(
            resource_type=ResourceType.DOCUMENT,
            resource_id=document_id,
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            permission=Permission.READ,
        )
        session.commit()


def _folder(name: str, parent_id: UUID | None = None):
    """Committed rather than rolled back (no per-test rollback here, same as
    `test_org_files_api.py`), so the name carries a random suffix to avoid
    colliding with a leftover row from a previous test."""
    with session_scope() as session:
        folder = FolderRepository(session).create(f"{name}-{uuid4().hex[:8]}", parent_id=parent_id)
        session.commit()
    return folder


def _document(filename: str, folder_id: UUID | None, blob_sha256: str | None = None):
    """Created directly through the repository, not ingestion, to keep the
    fixture fast -- ingestion/indexing is exercised in `test_org_files_api.py`.

    ``blob_sha256`` defaults to an arbitrary value: fine for tests that never
    read the document's bytes back. A download test passes a real one, stored
    via ``get_blob_store().put()``, or ``StreamingResponse`` blows up trying
    to open a file that was never written.
    """
    with session_scope() as session:
        document = DocumentRepository(session).create(
            namespace=Namespace.ORG_FILES,
            filename=filename,
            mime="application/pdf",
            byte_size=1,
            blob_sha256=blob_sha256 or f"{filename}-{uuid4().hex[:8]}",
            folder_id=folder_id,
        )
        session.commit()
    return document


def test_roots_returns_a_granted_folder_not_its_ungranted_parent(
    client: TestClient, member: User, member_headers: dict[str, str]
) -> None:
    root = _folder("root-a")
    litigation = _folder("Litigation", parent_id=root.id)
    _grant_folder(member, litigation.id)

    response = client.get("/me/org-files/roots", headers=member_headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(litigation.id)]
    assert response.json()[0]["ancestor_path"] == root.name


def test_a_folder_two_levels_below_a_grant_appears_without_its_own_grant(
    client: TestClient, member: User, member_headers: dict[str, str]
) -> None:
    granted = _folder("root-b")
    mid = _folder("2026", parent_id=granted.id)
    deep = _folder("Q1", parent_id=mid.id)
    _grant_folder(member, granted.id)

    response = client.get(f"/me/org-files/folders/{mid.id}", headers=member_headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["folders"]] == [str(deep.id)]


def test_a_folder_outside_the_accessible_set_is_404(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    other = _folder("root-c")

    response = client.get(f"/me/org-files/folders/{other.id}", headers=member_headers)

    assert response.status_code == 404


def test_a_user_with_no_grants_gets_empty_results_not_an_error(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    assert client.get("/me/org-files/roots", headers=member_headers).json() == []


def test_a_superuser_sees_every_root_folder_with_no_acl_grant_at_all(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    root = _folder("root-superuser")

    response = client.get("/me/org-files/roots", headers=admin_headers)

    assert response.status_code == 200
    assert str(root.id) in [item["id"] for item in response.json()]


def test_a_superuser_can_browse_any_folder_with_no_acl_grant_at_all(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    root = _folder("root-superuser-browse")
    child = _folder("child", parent_id=root.id)

    response = client.get(f"/me/org-files/folders/{root.id}", headers=admin_headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["folders"]] == [str(child.id)]


def test_a_superuser_still_gets_a_404_for_a_folder_that_does_not_exist(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.get(f"/me/org-files/folders/{uuid4()}", headers=admin_headers)

    assert response.status_code == 404


def test_get_folder_reports_effective_permission_and_structure_manager_flag(
    client: TestClient, member: User, member_headers: dict[str, str]
) -> None:
    root = _folder("root-perm")
    write_child = _folder("write-child", parent_id=root.id)
    read_child = _folder("read-child", parent_id=root.id)
    _grant_folder(member, root.id)
    _grant_folder(member, write_child.id, permission=Permission.WRITE)

    response = client.get(f"/me/org-files/folders/{root.id}", headers=member_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["folders"]
    by_id = {folder["id"]: folder for folder in body["folders"]}
    assert by_id[str(write_child.id)]["effective_permission"] == "write"
    assert by_id[str(write_child.id)]["is_structure_manager"] is False
    assert by_id[str(read_child.id)]["effective_permission"] == "read"
    assert by_id[str(read_child.id)]["is_structure_manager"] is False


def test_roots_report_effective_permission_and_structure_manager_flag(
    client: TestClient, member: User, member_headers: dict[str, str]
) -> None:
    root = _folder("root-perm-roots")
    _grant_folder(member, root.id, permission=Permission.WRITE)

    response = client.get("/me/org-files/roots", headers=member_headers)

    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()}
    assert by_id[str(root.id)]["effective_permission"] == "write"
    assert by_id[str(root.id)]["is_structure_manager"] is False


def test_roots_report_write_and_structure_manager_for_a_superuser(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    root = _folder("root-perm-roots-admin")

    response = client.get("/me/org-files/roots", headers=admin_headers)

    assert response.status_code == 200
    item = next(item for item in response.json() if item["id"] == str(root.id))
    assert item["effective_permission"] == "write"
    assert item["is_structure_manager"] is True


def test_get_folder_reports_write_and_structure_manager_for_a_superuser(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    root = _folder("root-perm-admin")
    _folder("child", parent_id=root.id)

    response = client.get(f"/me/org-files/folders/{root.id}", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["folders"]
    for folder in body["folders"]:
        assert folder["effective_permission"] == "write"
        assert folder["is_structure_manager"] is True


# ---------------------------------------------------------------- member actions


@pytest.fixture
def member_user_id(member: User) -> UUID:
    return member.id


@pytest.fixture
def read_only_folder_id(member: User) -> UUID:
    folder = _folder("read-only")
    _grant_folder(member, folder.id, permission=Permission.READ)
    return folder.id


@pytest.fixture
def write_folder_id(member: User) -> UUID:
    folder = _folder("write-folder")
    _grant_folder(member, folder.id, permission=Permission.WRITE)
    return folder.id


@pytest.fixture
def read_only_document_id(read_only_folder_id: UUID) -> UUID:
    document = _document("read-only.pdf", read_only_folder_id)
    return document.id


@pytest.fixture
def write_folder_document_id(write_folder_id: UUID) -> UUID:
    document = _document("write-folder.pdf", write_folder_id)
    return document.id


@pytest.fixture
def directly_granted_document_id(member: User) -> UUID:
    """A document with a direct grant to the member but no folder grant at
    all -- the folder itself stays outside the member's accessible set."""
    ungranted_folder = _folder("ungranted")
    sha256 = get_blob_store().put(b"secret content")
    document = _document("directly-granted.pdf", ungranted_folder.id, blob_sha256=sha256)
    _grant_document(member, document.id)
    return document.id


@pytest.fixture
def stub_ingest(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Stubs ingestion the same way `test_org_files_api.py` does: a real
    upload needs docling-serve and Qdrant, neither of which this test suite
    runs against."""
    calls: list[dict[str, Any]] = []

    def fake_ingest(data: bytes, **kwargs: Any) -> UUID:
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

    monkeypatch.setattr("law_agent.api.routers.me_org_files.ingest_document", fake_ingest)
    return calls


def test_member_upload_requires_write_permission(
    client: TestClient, member_headers: dict[str, str], read_only_folder_id: UUID
) -> None:
    response = client.post(
        f"/me/org-files/folders/{read_only_folder_id}/documents",
        files={"file": ("a.pdf", b"content", "application/pdf")},
        headers=member_headers,
    )
    assert response.status_code == 403


@pytest.mark.usefixtures("stub_ingest")
def test_member_upload_into_write_folder_succeeds_and_is_retrievable(
    client: TestClient,
    member_headers: dict[str, str],
    write_folder_id: UUID,
    member_user_id: UUID,
) -> None:
    response = client.post(
        f"/me/org-files/folders/{write_folder_id}/documents",
        files={"file": ("a.pdf", b"content", "application/pdf")},
        headers=member_headers,
    )
    assert response.status_code == 201
    assert response.json()["id"]
    assert write_folder_id in accessible_org_folder_ids(member_user_id)


def test_member_delete_requires_write_permission(
    client: TestClient, member_headers: dict[str, str], read_only_document_id: UUID
) -> None:
    response = client.delete(
        f"/me/org-files/documents/{read_only_document_id}", headers=member_headers
    )
    assert response.status_code == 403


def test_member_delete_in_write_folder_succeeds(
    client: TestClient, member_headers: dict[str, str], write_folder_document_id: UUID
) -> None:
    response = client.delete(
        f"/me/org-files/documents/{write_folder_document_id}", headers=member_headers
    )
    assert response.status_code == 204


def test_member_download_with_direct_grant_succeeds(
    client: TestClient, member_headers: dict[str, str], directly_granted_document_id: UUID
) -> None:
    response = client.get(
        f"/me/org-files/documents/{directly_granted_document_id}/download", headers=member_headers
    )
    assert response.status_code == 200


def test_member_download_without_grant_is_404(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    response = client.get(f"/me/org-files/documents/{uuid4()}/download", headers=member_headers)
    assert response.status_code == 404


def test_shared_documents_route_removed(client: TestClient, member_headers: dict[str, str]) -> None:
    response = client.get("/me/org-files/shared-documents", headers=member_headers)
    assert response.status_code == 404
