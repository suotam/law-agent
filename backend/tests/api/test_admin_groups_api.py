"""Group administration and membership: MANAGE_GROUPS."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from law_agent.access.models import PrincipalType, RoleCapability
from law_agent.api.auth.security import create_access_token
from law_agent.db.repositories import FolderRepository, GroupRepository
from law_agent.users.models import User


@pytest.fixture
def manage_groups_headers(make_role, make_user) -> dict[str, str]:
    role = make_role(capabilities=[RoleCapability.MANAGE_GROUPS])
    user = make_user(role)
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
def folder_and_group(db_engine):
    # Randomised: the test database outlives a single test, and two root
    # folders may not share a name.
    with Session(bind=db_engine) as session:
        folder = FolderRepository(session).create(f"Smlouvy-{uuid4().hex[:8]}")
        group = GroupRepository(session).create(f"Klienti-{uuid4().hex[:8]}")
        session.commit()
    return folder, group


def test_a_group_is_created_and_listed(
    client: TestClient, manage_groups_headers: dict[str, str]
) -> None:
    response = client.post("/groups", headers=manage_groups_headers, json={"name": "Klienti"})

    assert response.status_code == 201
    group_id = response.json()["id"]
    listed = client.get("/groups", headers=manage_groups_headers).json()
    assert group_id in {g["id"] for g in listed}


def test_a_group_is_renamed(client: TestClient, manage_groups_headers: dict[str, str]) -> None:
    group = client.post("/groups", headers=manage_groups_headers, json={"name": "Klienti"}).json()

    response = client.patch(
        f"/groups/{group['id']}", headers=manage_groups_headers, json={"name": "Klienti 2026"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Klienti 2026"


def test_a_group_is_deleted(client: TestClient, manage_groups_headers: dict[str, str]) -> None:
    group = client.post("/groups", headers=manage_groups_headers, json={"name": "Docasna"}).json()

    response = client.delete(f"/groups/{group['id']}", headers=manage_groups_headers)

    assert response.status_code == 204


def test_deleting_a_group_deletes_its_grants(
    client: TestClient,
    manage_groups_headers: dict[str, str],
    db_engine,
) -> None:
    """acl_entries has no FK to groups, so group deletion must sweep the
    group's grants itself: GET /acl must not keep listing grants on a group
    that no longer exists."""
    from law_agent.db.repositories import AclRepository

    group = client.post("/groups", headers=manage_groups_headers, json={"name": "Docasna"}).json()
    client.post(
        "/acl",
        headers=manage_groups_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(uuid4()),
            "principal_type": "group",
            "principal_id": group["id"],
            "permission": "read",
        },
    )

    deleted = client.delete(f"/groups/{group['id']}", headers=manage_groups_headers)
    assert deleted.status_code == 204

    with Session(bind=db_engine) as session:
        remaining = AclRepository(session).list_for_principal(
            PrincipalType.GROUP, UUID(group["id"])
        )
    assert remaining == []


def test_membership_is_added_and_listed(
    client: TestClient, manage_groups_headers: dict[str, str], member: User
) -> None:
    group = client.post("/groups", headers=manage_groups_headers, json={"name": "Klienti"}).json()

    add = client.post(
        f"/groups/{group['id']}/members",
        headers=manage_groups_headers,
        json={"user_id": str(member.id)},
    )
    listed = client.get(f"/groups/{group['id']}/members", headers=manage_groups_headers)

    assert add.status_code == 204
    assert {u["id"] for u in listed.json()} == {str(member.id)}


def test_membership_is_removed(
    client: TestClient, manage_groups_headers: dict[str, str], member: User
) -> None:
    group = client.post("/groups", headers=manage_groups_headers, json={"name": "Klienti"}).json()
    client.post(
        f"/groups/{group['id']}/members",
        headers=manage_groups_headers,
        json={"user_id": str(member.id)},
    )

    response = client.delete(
        f"/groups/{group['id']}/members/{member.id}", headers=manage_groups_headers
    )
    listed = client.get(f"/groups/{group['id']}/members", headers=manage_groups_headers)

    assert response.status_code == 204
    assert listed.json() == []


def test_a_users_groups_are_listed(
    client: TestClient, manage_groups_headers: dict[str, str], member: User
) -> None:
    """The user-centric membership editor needs the reverse view of
    membership: which groups one user belongs to."""
    first = client.post("/groups", headers=manage_groups_headers, json={"name": "Klienti"}).json()
    second = client.post("/groups", headers=manage_groups_headers, json={"name": "Docasna"}).json()
    client.post("/groups", headers=manage_groups_headers, json={"name": "Jina"})
    for group in (first, second):
        client.post(
            f"/groups/{group['id']}/members",
            headers=manage_groups_headers,
            json={"user_id": str(member.id)},
        )

    response = client.get(f"/users/{member.id}/groups", headers=manage_groups_headers)

    assert response.status_code == 200
    assert {group["name"] for group in response.json()} == {"Klienti", "Docasna"}


def test_a_user_with_no_groups_is_an_empty_list(
    client: TestClient, manage_groups_headers: dict[str, str], member: User
) -> None:
    assert client.get(f"/users/{member.id}/groups", headers=manage_groups_headers).json() == []


def test_an_unknown_users_groups_are_404(
    client: TestClient, manage_groups_headers: dict[str, str]
) -> None:
    assert client.get(f"/users/{uuid4()}/groups", headers=manage_groups_headers).status_code == 404


def test_a_member_cannot_list_a_users_groups(
    client: TestClient, member_headers: dict[str, str], member: User
) -> None:
    assert client.get(f"/users/{member.id}/groups", headers=member_headers).status_code == 403


def test_a_member_without_the_capability_gets_403(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    assert client.get("/groups", headers=member_headers).status_code == 403
    assert client.post("/groups", headers=member_headers, json={"name": "X"}).status_code == 403


def test_group_acl_lists_grants_across_every_resource(
    client: TestClient, manage_groups_headers: dict[str, str], folder_and_group, db_engine
) -> None:
    folder, group = folder_and_group
    with Session(bind=db_engine) as session:
        other_folder = FolderRepository(session).create(f"Druha-{uuid4().hex[:8]}")
        session.commit()

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
    client.post(
        "/acl",
        headers=manage_groups_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(other_folder.id),
            "principal_type": "group",
            "principal_id": str(group.id),
            "permission": "write",
        },
    )

    response = client.get(f"/groups/{group.id}/acl", headers=manage_groups_headers)

    assert response.status_code == 200
    resource_ids = {entry["resource_id"] for entry in response.json()["entries"]}
    assert resource_ids == {str(folder.id), str(other_folder.id)}


def test_group_acl_excludes_other_groups_grants(
    client: TestClient, manage_groups_headers: dict[str, str], folder_and_group
) -> None:
    folder, group = folder_and_group
    other_group = client.post(
        "/groups", headers=manage_groups_headers, json={"name": f"Jina-{folder.id.hex[:8]}"}
    ).json()
    client.post(
        "/acl",
        headers=manage_groups_headers,
        json={
            "resource_type": "folder",
            "resource_id": str(folder.id),
            "principal_type": "group",
            "principal_id": other_group["id"],
            "permission": "read",
        },
    )

    response = client.get(f"/groups/{group.id}/acl", headers=manage_groups_headers)

    assert response.json() == {"entries": [], "folders_with_nested_grant": []}
