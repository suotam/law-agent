"""Account provisioning: admin-only, no self-registration."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.api.conftest import PASSWORD

from law_agent.access.models import Role, RoleCapability
from law_agent.api.auth.security import create_access_token
from law_agent.users.models import User


@pytest.fixture
def manage_groups_headers(make_role, make_user) -> dict[str, str]:
    role = make_role(capabilities=[RoleCapability.MANAGE_GROUPS])
    user = make_user(role)
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_an_admin_creates_a_user(
    client: TestClient, admin_headers: dict[str, str], member_role: Role
) -> None:
    response = client.post(
        "/users",
        headers=admin_headers,
        json={"email": "novy@firma.cz", "password": "heslo123", "role_id": str(member_role.id)},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "novy@firma.cz"
    assert body["role"] == {"id": str(member_role.id), "name": "Member"}
    assert body["capabilities"] == []
    assert body["is_superuser"] is False
    assert body["is_active"] is True
    assert "password" not in body
    assert "password_hash" not in body


def test_the_created_user_appears_in_the_list(
    client: TestClient, admin_headers: dict[str, str], admin: User, member_role: Role
) -> None:
    client.post(
        "/users",
        headers=admin_headers,
        json={"email": "kolega@firma.cz", "password": "heslo123", "role_id": str(member_role.id)},
    )

    response = client.get("/users", headers=admin_headers)

    assert response.status_code == 200
    emails = {item["email"] for item in response.json()}
    assert {"kolega@firma.cz", admin.email} <= emails


def test_a_duplicate_email_is_409(
    client: TestClient, admin_headers: dict[str, str], member_role: Role
) -> None:
    payload = {"email": "dvakrat@firma.cz", "password": "heslo123", "role_id": str(member_role.id)}
    client.post("/users", headers=admin_headers, json=payload)

    response = client.post("/users", headers=admin_headers, json=payload)

    assert response.status_code == 409


def test_an_unknown_role_id_is_404(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post(
        "/users",
        headers=admin_headers,
        json={"email": "sirotek@firma.cz", "password": "heslo123", "role_id": str(uuid4())},
    )

    assert response.status_code == 404


def test_a_users_role_is_reassigned(
    client: TestClient, admin_headers: dict[str, str], member: User, admin_role: Role
) -> None:
    response = client.patch(
        f"/users/{member.id}",
        headers=admin_headers,
        json={"role_id": str(admin_role.id)},
    )

    assert response.status_code == 200
    assert response.json()["role"]["name"] == "Admin"


def test_a_manager_can_reassign_an_ordinary_member(
    client: TestClient, manager_headers: dict[str, str], member: User, member_role: Role
) -> None:
    """MANAGE_USERS below superuser is the whole point of the capability: an
    ordinary member is fair game for a manager."""
    other_member_role = member_role

    response = client.patch(
        f"/users/{member.id}",
        headers=manager_headers,
        json={"role_id": str(other_member_role.id)},
    )

    assert response.status_code == 200


def test_a_non_superuser_cannot_reassign_a_superusers_role(
    client: TestClient, manager_headers: dict[str, str], admin: User, member_role: Role
) -> None:
    """Demoting (or re-pointing) a superuser account is superuser business --
    a manager with MANAGE_USERS would otherwise be able to take the admin
    role away from an account they cannot otherwise touch."""

    response = client.patch(
        f"/users/{admin.id}",
        headers=manager_headers,
        json={"role_id": str(member_role.id)},
    )

    assert response.status_code == 403


def test_a_non_superuser_cannot_assign_the_superuser_role(
    client: TestClient, manager_headers: dict[str, str], member: User, admin_role: Role
) -> None:
    response = client.patch(
        f"/users/{member.id}",
        headers=manager_headers,
        json={"role_id": str(admin_role.id)},
    )

    assert response.status_code == 403


def test_nobody_changes_their_own_role(
    client: TestClient, admin_headers: dict[str, str], admin: User, member_role: Role
) -> None:
    """Not even a superuser: self-service role changes are how an accidental
    demotion (or a coerced one) happens with no one else the wiser."""
    response = client.patch(
        f"/users/{admin.id}",
        headers=admin_headers,
        json={"role_id": str(member_role.id)},
    )

    assert response.status_code == 403


def test_a_non_superuser_cannot_create_a_superuser_account(
    client: TestClient, manager_headers: dict[str, str], admin_role: Role
) -> None:
    response = client.post(
        "/users",
        headers=manager_headers,
        json={
            "email": "vlastni-superuser@firma.cz",
            "password": "heslo123",
            "role_id": str(admin_role.id),
        },
    )

    assert response.status_code == 403


def test_a_superuser_can_create_a_superuser_account(
    client: TestClient, admin_headers: dict[str, str], admin_role: Role
) -> None:
    response = client.post(
        "/users",
        headers=admin_headers,
        json={
            "email": "dalsi-superuser@firma.cz",
            "password": "heslo123",
            "role_id": str(admin_role.id),
        },
    )

    assert response.status_code == 201
    assert response.json()["is_superuser"] is True


def test_a_member_cannot_create_users(
    client: TestClient, member_headers: dict[str, str], member_role: Role
) -> None:
    response = client.post(
        "/users",
        headers=member_headers,
        json={
            "email": "propasovany@firma.cz",
            "password": "heslo123",
            "role_id": str(member_role.id),
        },
    )

    assert response.status_code == 403


def test_a_member_cannot_list_users(client: TestClient, member_headers: dict[str, str]) -> None:
    assert client.get("/users", headers=member_headers).status_code == 403


def test_a_group_manager_can_list_users_but_not_create_them(
    client: TestClient, manage_groups_headers: dict[str, str], member_role: Role
) -> None:
    assert client.get("/users", headers=manage_groups_headers).status_code == 200

    response = client.post(
        "/users",
        headers=manage_groups_headers,
        json={"email": "novy2@firma.cz", "password": "heslo123", "role_id": str(member_role.id)},
    )
    assert response.status_code == 403


def test_an_anonymous_caller_is_401(client: TestClient) -> None:
    assert client.get("/users").status_code == 401


def test_a_malformed_body_is_422(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post(
        "/users",
        headers=admin_headers,
        json={"email": "not-an-email", "password": "heslo123", "role_id": "not-a-uuid"},
    )

    assert response.status_code == 422


def test_deleting_a_user_deactivates_them_not_erases_them(
    client: TestClient, admin_headers: dict[str, str], member: User
) -> None:
    """Soft delete: the row (and its email address) stays, only the flag
    flips -- conversations and ACL grants keep pointing at it."""
    response = client.delete(f"/users/{member.id}", headers=admin_headers)

    assert response.status_code == 204

    listed = client.get("/users", headers=admin_headers).json()
    deleted = next(item for item in listed if item["id"] == str(member.id))
    assert deleted["is_active"] is False


def test_a_deleted_user_is_logged_out_immediately(
    client: TestClient, admin_headers: dict[str, str], member_headers: dict[str, str], member: User
) -> None:
    client.delete(f"/users/{member.id}", headers=admin_headers)

    assert client.get("/auth/me", headers=member_headers).status_code == 401


def test_a_deleted_user_cannot_log_back_in(
    client: TestClient, admin_headers: dict[str, str], member: User
) -> None:
    client.delete(f"/users/{member.id}", headers=admin_headers)

    response = client.post("/auth/login", json={"email": member.email, "password": PASSWORD})

    assert response.status_code == 401


def test_a_deleted_users_email_stays_reserved(
    client: TestClient, admin_headers: dict[str, str], member: User, member_role: Role
) -> None:
    """Deactivating must not free the address for re-registration: the point
    of soft delete is that the old row is still there, and re-hiring means
    reactivating, not creating a fresh account with the same identity."""
    client.delete(f"/users/{member.id}", headers=admin_headers)

    response = client.post(
        "/users",
        headers=admin_headers,
        json={"email": member.email, "password": "heslo123", "role_id": str(member_role.id)},
    )

    assert response.status_code == 409


def test_a_deactivated_user_can_be_reactivated(
    client: TestClient, admin_headers: dict[str, str], member_headers: dict[str, str], member: User
) -> None:
    client.delete(f"/users/{member.id}", headers=admin_headers)
    assert client.get("/auth/me", headers=member_headers).status_code == 401

    response = client.post(f"/users/{member.id}/activate", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    # The account is whole again: the old token works too, no re-login needed.
    assert client.get("/auth/me", headers=member_headers).status_code == 200


def test_a_non_superuser_cannot_delete_a_superuser(
    client: TestClient, manager_headers: dict[str, str], admin: User
) -> None:
    response = client.delete(f"/users/{admin.id}", headers=manager_headers)

    assert response.status_code == 403


def test_nobody_deletes_their_own_account(
    client: TestClient, admin_headers: dict[str, str], admin: User
) -> None:
    response = client.delete(f"/users/{admin.id}", headers=admin_headers)

    assert response.status_code == 403


def test_deleting_an_unknown_user_is_404(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert client.delete(f"/users/{uuid4()}", headers=admin_headers).status_code == 404


def test_an_admin_resets_a_users_password(
    client: TestClient, admin_headers: dict[str, str], member: User
) -> None:
    response = client.put(
        f"/users/{member.id}/password",
        headers=admin_headers,
        json={"new_password": "nove-heslo"},
    )

    assert response.status_code == 204
    assert (
        client.post(
            "/auth/login", json={"email": member.email, "password": "nove-heslo"}
        ).status_code
        == 200
    )


def test_a_non_superuser_cannot_reset_a_superusers_password(
    client: TestClient, manager_headers: dict[str, str], admin: User
) -> None:
    """Resetting someone's password is taking their account over: the same
    superuser boundary as every other superuser-account operation."""
    response = client.put(
        f"/users/{admin.id}/password",
        headers=manager_headers,
        json={"new_password": "prevzal-jsem-ucet"},
    )

    assert response.status_code == 403


def test_nobody_resets_their_own_password_via_the_admin_endpoint(
    client: TestClient, admin_headers: dict[str, str], admin: User
) -> None:
    response = client.put(
        f"/users/{admin.id}/password",
        headers=admin_headers,
        json={"new_password": "nove-heslo"},
    )

    assert response.status_code == 403


def test_resetting_an_unknown_users_password_is_404(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    assert (
        client.put(
            f"/users/{uuid4()}/password",
            headers=admin_headers,
            json={"new_password": "nove-heslo"},
        ).status_code
        == 404
    )
