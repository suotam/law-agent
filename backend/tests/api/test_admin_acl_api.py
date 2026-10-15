"""Access grants: explicit rows on exactly one resource each. MANAGE_GROUPS."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from law_agent.access.models import RoleCapability
from law_agent.api.auth.security import create_access_token
from law_agent.db.repositories import FolderRepository, GroupRepository


@pytest.fixture
def manage_groups_headers(make_role, make_user) -> dict[str, str]:
    role = make_role(capabilities=[RoleCapability.MANAGE_GROUPS])
    user = make_user(role)
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
def folder_and_group(db_engine):
    from uuid import uuid4

    from sqlalchemy.orm import Session

    # Randomised: the test database outlives a single test, and two root
    # folders may not share a name.
    with Session(bind=db_engine) as session:
        folder = FolderRepository(session).create(f"Smlouvy-{uuid4().hex[:8]}")
        group = GroupRepository(session).create(f"Klienti-{uuid4().hex[:8]}")
        session.commit()
    return folder, group


def test_an_acl_entry_is_created(
    client: TestClient, manage_groups_headers: dict[str, str], folder_and_group
) -> None:
    folder, group = folder_and_group

    response = client.post(
        "/acl",
        headers=manage_groups_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "group",
            "principal_id": str(group.id),
            "permission": "read",
        },
    )

    assert response.status_code == 201
    assert response.json()["permission"] == "read"


def test_a_duplicate_post_updates_the_permission_in_place(
    client: TestClient, manage_groups_headers: dict[str, str], folder_and_group
) -> None:
    folder, group = folder_and_group
    payload = {
        "resource_type": "folder",
        "resource_id": str(folder.id),
        "principal_type": "group",
        "principal_id": str(group.id),
        "permission": "read",
    }
    first = client.post("/acl", headers=manage_groups_headers, json=payload)

    payload["permission"] = "write"
    second = client.post("/acl", headers=manage_groups_headers, json=payload)

    assert second.json()["id"] == first.json()["id"]
    assert second.json()["permission"] == "write"
    listed = client.get(
        f"/acl?resource_type=folder&resource_id={folder.id}", headers=manage_groups_headers
    ).json()
    assert len(listed) == 1


def test_an_acl_entry_is_deleted(
    client: TestClient, manage_groups_headers: dict[str, str], folder_and_group
) -> None:
    folder, group = folder_and_group
    created = client.post(
        "/acl",
        headers=manage_groups_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "group",
            "principal_id": str(group.id),
            "permission": "read",
        },
    ).json()

    response = client.delete(f"/acl/{created['id']}", headers=manage_groups_headers)
    listed = client.get(
        f"/acl?resource_type=folder&resource_id={folder.id}", headers=manage_groups_headers
    ).json()

    assert response.status_code == 204
    assert listed == []


def test_a_member_without_the_capability_gets_403(
    client: TestClient, member_headers: dict[str, str], folder_and_group
) -> None:
    folder, _ = folder_and_group
    response = client.get(
        f"/acl?resource_type=folder&resource_id={folder.id}", headers=member_headers
    )

    assert response.status_code == 403


def test_effective_acl_splits_own_from_inherited(
    client: TestClient, manage_groups_headers: dict[str, str], db_engine
) -> None:
    with Session(bind=db_engine) as session:
        parent = FolderRepository(session).create(f"Rodic-{uuid4().hex[:8]}")
        child = FolderRepository(session).create(f"Dite-{uuid4().hex[:8]}", parent_id=parent.id)
        group = GroupRepository(session).create(f"Skupina-{uuid4().hex[:8]}")
        session.commit()

    client.post(
        "/acl",
        headers=manage_groups_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(parent.id),
            "principal_type": "group",
            "principal_id": str(group.id),
            "permission": "read",
        },
    )

    response = client.get(
        f"/acl/effective?resource_type=folder&resource_id={child.id}",
        headers=manage_groups_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["own"] == []
    assert len(body["inherited"]) == 1
    assert body["inherited"][0]["resource_id"] == str(parent.id)


def test_effective_acl_own_grant_is_not_duplicated_as_inherited(
    client: TestClient, manage_groups_headers: dict[str, str], folder_and_group
) -> None:
    folder, group = folder_and_group
    client.post(
        "/acl",
        headers=manage_groups_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "group",
            "principal_id": str(group.id),
            "permission": "read",
        },
    )

    response = client.get(
        f"/acl/effective?resource_type=folder&resource_id={folder.id}",
        headers=manage_groups_headers,
    )

    body = response.json()
    assert len(body["own"]) == 1
    assert body["inherited"] == []


def test_delete_acl_entry_on_folder_cascades_to_subtree(
    client: TestClient, manage_groups_headers: dict[str, str], folder_and_group, db_engine
) -> None:
    folder, group = folder_and_group
    with Session(bind=db_engine) as session:
        child = FolderRepository(session).create(f"Dite-{uuid4().hex[:8]}", parent_id=folder.id)
        session.commit()

    parent_grant = client.post(
        "/acl",
        headers=manage_groups_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "group",
            "principal_id": str(group.id),
            "permission": "read",
        },
    ).json()
    client.post(
        "/acl",
        headers=manage_groups_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(child.id),
            "principal_type": "group",
            "principal_id": str(group.id),
            "permission": "write",
        },
    )

    response = client.delete(f"/acl/{parent_grant['id']}", headers=manage_groups_headers)
    listed = client.get(
        f"/acl?resource_type=folder&resource_id={child.id}", headers=manage_groups_headers
    ).json()

    assert response.status_code == 204
    assert listed == []


def test_post_acl_write_on_document_is_422(client, manage_groups_headers):
    response = client.post(
        "/acl",
        json={
            "resource_type": "document",
            "resource_id": str(uuid4()),
            "principal_type": "group",
            "principal_id": str(uuid4()),
            "permission": "write",
        },
        headers=manage_groups_headers,
    )
    assert response.status_code == 422


@pytest.fixture
def folder_and_user(db_engine, make_user):
    with Session(bind=db_engine) as session:
        folder = FolderRepository(session).create(f"Uzivatelska-{uuid4().hex[:8]}")
        session.commit()
    return folder, make_user()


def test_post_user_grant_requires_manage_users(
    client: TestClient, manage_groups_headers: dict[str, str], folder_and_user
) -> None:
    folder, target = folder_and_user

    response = client.post(
        "/acl",
        headers=manage_groups_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "user",
            "principal_id": str(target.id),
            "permission": "read",
        },
    )

    assert response.status_code == 403


def test_post_user_grant_succeeds_with_manage_users(
    client: TestClient, manager_headers: dict[str, str], folder_and_user
) -> None:
    folder, target = folder_and_user

    response = client.post(
        "/acl",
        headers=manager_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "user",
            "principal_id": str(target.id),
            "permission": "read",
        },
    )

    assert response.status_code == 201


def test_post_group_grant_requires_manage_groups(
    client: TestClient, manager_headers: dict[str, str], folder_and_group
) -> None:
    folder, group = folder_and_group

    response = client.post(
        "/acl",
        headers=manager_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "group",
            "principal_id": str(group.id),
            "permission": "read",
        },
    )

    assert response.status_code == 403


def test_delete_user_grant_requires_manage_users(
    client: TestClient,
    manager_headers: dict[str, str],
    manage_groups_headers: dict[str, str],
    folder_and_user,
) -> None:
    folder, target = folder_and_user
    created = client.post(
        "/acl",
        headers=manager_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "user",
            "principal_id": str(target.id),
            "permission": "read",
        },
    ).json()

    forbidden = client.delete(f"/acl/{created['id']}", headers=manage_groups_headers)
    allowed = client.delete(f"/acl/{created['id']}", headers=manager_headers)

    assert forbidden.status_code == 403
    assert allowed.status_code == 204


def test_get_acl_succeeds_with_manage_users_alone(
    client: TestClient, manager_headers: dict[str, str], folder_and_group
) -> None:
    folder, _group = folder_and_group

    response = client.get(
        f"/acl?resource_type=folder&resource_id={folder.id}", headers=manager_headers
    )

    assert response.status_code == 200


@pytest.fixture
def folder_with_user_and_group_grants(
    client: TestClient,
    manager_headers: dict[str, str],
    manage_groups_headers: dict[str, str],
    db_engine,
    make_user,
):
    """A folder carrying a user grant of its own plus a group grant inherited
    from its parent -- the setup every principal-type-visibility test below
    reads from."""
    with Session(bind=db_engine) as session:
        parent = FolderRepository(session).create(f"Rodic-{uuid4().hex[:8]}")
        folder = FolderRepository(session).create(f"Dite-{uuid4().hex[:8]}", parent_id=parent.id)
        group = GroupRepository(session).create(f"Skupina-{uuid4().hex[:8]}")
        session.commit()
    target = make_user()
    client.post(
        "/acl",
        headers=manager_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "user",
            "principal_id": str(target.id),
            "permission": "read",
        },
    )
    client.post(
        "/acl",
        headers=manage_groups_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(parent.id),
            "principal_type": "group",
            "principal_id": str(group.id),
            "permission": "read",
        },
    )
    return folder


def test_get_acl_withholds_group_grants_from_a_manage_users_caller(
    client: TestClient,
    manager_headers: dict[str, str],
    folder_with_user_and_group_grants,
) -> None:
    """The Share panel hides group grants from a MANAGE_USERS-only caller
    ("shouldn't learn which groups have access at all") -- the restriction
    has to hold server-side too, not just in the UI."""
    folder = folder_with_user_and_group_grants

    listed = client.get(
        f"/acl?resource_type=folder&resource_id={folder.id}", headers=manager_headers
    ).json()
    effective = client.get(
        f"/acl/effective?resource_type=folder&resource_id={folder.id}",
        headers=manager_headers,
    ).json()

    assert {entry["principal_type"] for entry in listed} == {"user"}
    assert {entry["principal_type"] for entry in effective["own"]} == {"user"}
    assert {entry["principal_type"] for entry in effective["inherited"]} == set()


def test_get_acl_withholds_user_grants_from_a_manage_groups_caller(
    client: TestClient,
    manage_groups_headers: dict[str, str],
    folder_with_user_and_group_grants,
) -> None:
    folder = folder_with_user_and_group_grants

    listed = client.get(
        f"/acl?resource_type=folder&resource_id={folder.id}", headers=manage_groups_headers
    ).json()
    effective = client.get(
        f"/acl/effective?resource_type=folder&resource_id={folder.id}",
        headers=manage_groups_headers,
    ).json()

    assert listed == []
    assert effective["own"] == []
    assert {entry["principal_type"] for entry in effective["inherited"]} == {"group"}


def test_get_acl_shows_every_principal_type_to_a_superuser(
    client: TestClient, admin_headers: dict[str, str], folder_with_user_and_group_grants
) -> None:
    folder = folder_with_user_and_group_grants

    effective = client.get(
        f"/acl/effective?resource_type=folder&resource_id={folder.id}",
        headers=admin_headers,
    ).json()

    assert {entry["principal_type"] for entry in effective["own"]} == {"user"}
    assert {entry["principal_type"] for entry in effective["inherited"]} == {"group"}


def test_user_acl_lists_grants_across_every_resource(
    client: TestClient, manager_headers: dict[str, str], folder_and_user, db_engine
) -> None:
    folder, target = folder_and_user
    with Session(bind=db_engine) as session:
        other_folder = FolderRepository(session).create(f"Druha-{uuid4().hex[:8]}")
        session.commit()

    client.post(
        "/acl",
        headers=manager_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "user",
            "principal_id": str(target.id),
            "permission": "read",
        },
    )
    client.post(
        "/acl",
        headers=manager_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(other_folder.id),
            "principal_type": "user",
            "principal_id": str(target.id),
            "permission": "write",
        },
    )

    response = client.get(f"/users/{target.id}/acl", headers=manager_headers)

    assert response.status_code == 200
    resource_ids = {entry["resource_id"] for entry in response.json()["entries"]}
    assert resource_ids == {str(folder.id), str(other_folder.id)}


def test_user_acl_reports_folders_with_a_nested_grant(
    client: TestClient, manager_headers: dict[str, str], folder_and_user, db_engine
) -> None:
    folder, target = folder_and_user
    with Session(bind=db_engine) as session:
        child = FolderRepository(session).create(f"Dite-{uuid4().hex[:8]}", parent_id=folder.id)
        session.commit()

    client.post(
        "/acl",
        headers=manager_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(child.id),
            "principal_type": "user",
            "principal_id": str(target.id),
            "permission": "read",
        },
    )

    response = client.get(f"/users/{target.id}/acl", headers=manager_headers)

    assert response.status_code == 200
    body = response.json()
    # The child folder has its own grant, so it's in `entries`, not the
    # nested-grant set; `folder` has no grant of its own but contains one.
    assert body["folders_with_nested_grant"] == [str(folder.id)]


def test_user_acl_requires_manage_users(
    client: TestClient,
    member_headers: dict[str, str],
    manage_groups_headers: dict[str, str],
    folder_and_user,
) -> None:
    _folder, target = folder_and_user

    assert client.get(f"/users/{target.id}/acl", headers=member_headers).status_code == 403
    assert client.get(f"/users/{target.id}/acl", headers=manage_groups_headers).status_code == 403
