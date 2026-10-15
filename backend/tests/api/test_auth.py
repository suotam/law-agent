"""Login and token validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from tests.api.conftest import PASSWORD

from law_agent.access.models import RoleCapability
from law_agent.api.app import create_app
from law_agent.api.auth.dependencies import CurrentUser, require_capability, require_superuser
from law_agent.api.auth.security import ALGORITHM, create_access_token
from law_agent.config import settings
from law_agent.db.repositories import UserRepository
from law_agent.users.models import User


def _guarded_client() -> TestClient:
    """An app with one open route, one capability-gated route and one
    superuser-only route, so the dependencies can be tested without waiting
    for the real endpoints."""
    app: FastAPI = create_app()

    @app.get("/whoami")
    def whoami(user: CurrentUser) -> dict[str, str]:
        return {"user_id": str(user.user_id)}

    @app.get(
        "/manage-only",
        dependencies=[Depends(require_capability(RoleCapability.MANAGE_USERS))],
    )
    def manage_only() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/superuser-only", dependencies=[Depends(require_superuser)])
    def superuser_only() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def test_login_returns_a_usable_token(client: TestClient, member: User) -> None:
    response = client.post("/auth/login", json={"email": member.email, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"

    guarded = _guarded_client()
    whoami = guarded.get("/whoami", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert whoami.json() == {"user_id": str(member.id)}


def test_a_wrong_password_is_401(client: TestClient, member: User) -> None:
    response = client.post("/auth/login", json={"email": member.email, "password": "spatne"})

    assert response.status_code == 401


def test_an_unknown_email_is_401_and_says_the_same_thing(client: TestClient, member: User) -> None:
    """The two failures must be indistinguishable, or the endpoint tells an
    attacker which addresses are registered."""
    wrong_password = client.post("/auth/login", json={"email": member.email, "password": "spatne"})
    unknown = client.post("/auth/login", json={"email": "nikdo@firma.cz", "password": PASSWORD})

    assert unknown.status_code == 401
    assert unknown.json() == wrong_password.json()


def test_a_deactivated_account_cannot_log_in(
    client: TestClient, member: User, db_engine: Engine
) -> None:
    """Same one message as the other login failures: the account exists, so
    revealing deactivation would reveal nothing an attacker does not already
    know, but uniformity keeps the endpoint simple."""
    with Session(bind=db_engine) as session:
        UserRepository(session).set_active(member.id, active=False)
        session.commit()

    response = client.post("/auth/login", json={"email": member.email, "password": PASSWORD})

    assert response.status_code == 401


def test_a_deactivated_account_s_token_is_rejected_everywhere(
    client: TestClient, member: User, member_headers: dict[str, str], db_engine: Engine
) -> None:
    """Soft delete must kill an existing token on the very next request -- that
    immediacy is the entire point of checking the account per request instead
    of trusting the token until it expires."""
    with Session(bind=db_engine) as session:
        UserRepository(session).set_active(member.id, active=False)
        session.commit()

    assert client.get("/auth/me", headers=member_headers).status_code == 401


def test_me_describes_the_holder_of_the_token(
    client: TestClient, member: User, member_headers: dict[str, str]
) -> None:
    response = client.get("/auth/me", headers=member_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(member.id)
    assert body["email"] == member.email
    assert body["role"]["name"] == "Member"
    assert "password_hash" not in body


def test_me_needs_a_token(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 401


def test_me_is_401_for_a_token_whose_user_is_gone(client: TestClient) -> None:
    """A validly signed token for an account that does not exist: the signature
    is fine, the identity is not."""
    orphaned = create_access_token(uuid4())

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {orphaned}"})

    assert response.status_code == 401


def test_a_missing_token_is_401() -> None:
    assert _guarded_client().get("/whoami").status_code == 401


def test_a_garbage_token_is_401() -> None:
    response = _guarded_client().get("/whoami", headers={"Authorization": "Bearer nonsense"})

    assert response.status_code == 401


def test_an_expired_token_is_401() -> None:
    expired = jwt.encode(
        {"sub": str(uuid4()), "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )

    response = _guarded_client().get("/whoami", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401


def test_a_member_may_not_enter_a_capability_gated_route(member_headers: dict[str, str]) -> None:
    assert _guarded_client().get("/manage-only", headers=member_headers).status_code == 403


def test_an_admin_may_enter_a_capability_gated_route(admin_headers: dict[str, str]) -> None:
    assert _guarded_client().get("/manage-only", headers=admin_headers).status_code == 200


def test_a_member_may_not_enter_a_superuser_only_route(member_headers: dict[str, str]) -> None:
    assert _guarded_client().get("/superuser-only", headers=member_headers).status_code == 403


def test_an_admin_may_enter_a_superuser_only_route(admin_headers: dict[str, str]) -> None:
    assert _guarded_client().get("/superuser-only", headers=admin_headers).status_code == 200


def test_a_user_can_change_their_own_password(
    client: TestClient, member: User, member_headers: dict[str, str]
) -> None:
    response = client.post(
        "/me/password",
        headers=member_headers,
        json={"current_password": PASSWORD, "new_password": "nove-heslo"},
    )

    assert response.status_code == 204
    assert (
        client.post(
            "/auth/login", json={"email": member.email, "password": "nove-heslo"}
        ).status_code
        == 200
    )
    # The old password stops working: this is a change, not an addition.
    assert (
        client.post("/auth/login", json={"email": member.email, "password": PASSWORD}).status_code
        == 401
    )


def test_changing_password_requires_the_current_one(
    client: TestClient, member: User, member_headers: dict[str, str]
) -> None:
    """Whoever holds the token must still prove they know the account's
    current password -- a stolen token alone must not be able to take the
    account over permanently."""
    response = client.post(
        "/me/password",
        headers=member_headers,
        json={"current_password": "spatne", "new_password": "nove-heslo"},
    )

    assert response.status_code == 403
    # Nothing changed.
    assert (
        client.post("/auth/login", json={"email": member.email, "password": PASSWORD}).status_code
        == 200
    )
