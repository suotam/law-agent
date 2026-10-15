"""Role and capability administration: mutations are superuser-only, never a
capability -- listing is open to anyone who can manage users."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from law_agent.access.models import Role, RoleCapability
from law_agent.api.auth.security import create_access_token
from law_agent.db import engine as engine_module
from law_agent.db.repositories import UserRepository
from law_agent.users.models import User


def test_a_superuser_creates_a_role(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post("/roles", headers=admin_headers, json={"name": "Manager"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Manager"
    assert body["is_superuser"] is False
    assert body["capabilities"] == []


def test_a_role_holding_every_other_capability_still_cannot_create_a_role(
    client: TestClient, make_role
) -> None:
    manager = make_role(
        capabilities=[
            RoleCapability.MANAGE_USERS,
            RoleCapability.MANAGE_GROUPS,
            RoleCapability.MANAGE_ORG_FILES_STRUCTURE,
        ]
    )

    response = client.post(
        "/roles",
        headers={"Authorization": f"Bearer {_token_for(manager)}"},
        json={"name": "X"},
    )

    assert response.status_code == 403


def test_a_manage_users_holder_can_list_roles(client: TestClient, manager_headers) -> None:
    """Listing roles is needed to populate a role picker when editing a user
    -- gating it on superuser would strand a MANAGE_USERS-only caller mid-flow."""
    response = client.get("/roles", headers=manager_headers)

    assert response.status_code == 200


def _token_for(role: Role) -> str:
    """A throwaway token for a freshly created role with no user yet --
    kept local to this file since it is only ever needed here."""
    with engine_module.get_sessionmaker()() as session:
        user = UserRepository(session).create(
            email=f"{uuid4().hex}@firma.cz", password_hash="hash", role_id=role.id
        )
        session.commit()
    return create_access_token(user.id)


def test_capabilities_replace_rather_than_append(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    role = client.post("/roles", headers=admin_headers, json={"name": "Manager"}).json()

    client.put(
        f"/roles/{role['id']}/capabilities",
        headers=admin_headers,
        json={"capabilities": ["manage_groups"]},
    )
    second = client.put(
        f"/roles/{role['id']}/capabilities",
        headers=admin_headers,
        json={"capabilities": ["manage_users"]},
    )

    assert second.json()["capabilities"] == ["manage_users"]


def test_deleting_a_role_in_use_is_409(
    client: TestClient, admin_headers: dict[str, str], member: User
) -> None:
    response = client.delete(f"/roles/{member.role_id}", headers=admin_headers)

    assert response.status_code == 409


def test_deleting_an_unused_role_succeeds(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    role = client.post("/roles", headers=admin_headers, json={"name": "Docasna"}).json()

    response = client.delete(f"/roles/{role['id']}", headers=admin_headers)

    assert response.status_code == 204
    remaining = client.get("/roles", headers=admin_headers).json()
    assert role["id"] not in {r["id"] for r in remaining}


def test_a_non_superuser_without_manage_users_gets_403_on_every_roles_route(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    assert client.get("/roles", headers=member_headers).status_code == 403
    assert client.post("/roles", headers=member_headers, json={"name": "X"}).status_code == 403
    assert client.delete(f"/roles/{uuid4()}", headers=member_headers).status_code == 403


def test_the_superuser_role_cannot_be_deleted(
    client: TestClient, admin_headers: dict[str, str], admin_role: Role
) -> None:
    """Even when no account holds it (all superusers demoted), deleting the
    role would leave the deployment with no way to mint a superuser: the API
    cannot set is_superuser on a role -- only this seed row (and the bootstrap
    script) can."""
    response = client.delete(f"/roles/{admin_role.id}", headers=admin_headers)

    assert response.status_code == 403


def test_the_superuser_role_cannot_be_renamed(
    client: TestClient, admin_headers: dict[str, str], admin_role: Role
) -> None:
    """The name is part of the bootstrap surface: scripts and runbooks point
    at it (create_user.py --role Admin)."""
    response = client.patch(f"/roles/{admin_role.id}", headers=admin_headers, json={"name": "X"})

    assert response.status_code == 403


def test_the_superuser_role_cannot_be_given_capabilities(
    client: TestClient, admin_headers: dict[str, str], admin_role: Role
) -> None:
    """is_superuser bypasses every capability check, so the set on a
    superuser role is decoration at best and misleading at worst."""
    response = client.put(
        f"/roles/{admin_role.id}/capabilities",
        headers=admin_headers,
        json={"capabilities": ["manage_users"]},
    )

    assert response.status_code == 403
