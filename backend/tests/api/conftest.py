"""Fixtures for the HTTP layer's tests.

The API tests are deliberately thin: service behaviour is already covered
directly in ``tests/test_conversations.py``, so what is exercised here is only
what HTTP can get wrong -- auth, status codes and payload shape.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from law_agent.access.models import Role, RoleCapability
from law_agent.api.app import create_app
from law_agent.api.auth.security import create_access_token, hash_password
from law_agent.db.repositories import RoleRepository, UserRepository
from law_agent.users.models import User

PASSWORD = "tajne-heslo"


@pytest.fixture(autouse=True)
def api_engine(monkeypatch: pytest.MonkeyPatch, db_engine: Engine) -> None:
    """Point every ``session_scope()`` the endpoints open at the test database.

    Autouse: an endpoint reaching the developer's real database from a test is
    a failure mode worth making impossible rather than remembering to prevent.
    """
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr("law_agent.db.engine.get_sessionmaker", lambda: factory)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """``raise_server_exceptions=False`` makes the client behave like a real
    server: an unhandled exception becomes a 500 response instead of being
    re-raised into the test."""
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def make_role(db_engine: Engine) -> Callable[..., Role]:
    """A role with an arbitrary name and, optionally, a fixed set of
    capabilities -- for testing capability gating without touching the
    seeded ``Admin``/``Member`` rows."""

    def factory(
        *, name: str | None = None, capabilities: list[RoleCapability] | None = None
    ) -> Role:
        with Session(bind=db_engine) as session:
            repository = RoleRepository(session)
            role = repository.create(name or f"role-{uuid4().hex[:8]}")
            if capabilities:
                role = repository.set_capabilities(role.id, capabilities)
            session.commit()
        return role

    return factory


@pytest.fixture
def admin_role(db_engine: Engine) -> Role:
    """The seeded superuser role every deployment starts with."""
    with Session(bind=db_engine) as session:
        role = RoleRepository(session).get_by_name("Admin")
    assert role is not None
    return role


@pytest.fixture
def member_role(db_engine: Engine) -> Role:
    """The seeded no-capabilities role every deployment starts with."""
    with Session(bind=db_engine) as session:
        role = RoleRepository(session).get_by_name("Member")
    assert role is not None
    return role


@pytest.fixture
def make_user(db_engine: Engine, member_role: Role) -> Callable[..., User]:
    """Committed rather than rolled back: the endpoint under test opens its own
    session and would not see an uncommitted row.

    The address is randomised because the test database outlives the test: a
    per-test counter would hand the second test an email the first one took.
    """

    def factory(role: Role | None = None, email: str | None = None) -> User:
        role = role or member_role
        with Session(bind=db_engine) as session:
            user = UserRepository(session).create(
                email=email or f"user-{uuid4().hex}@firma.cz",
                password_hash=hash_password(PASSWORD),
                role_id=role.id,
            )
            session.commit()
        return user

    return factory


@pytest.fixture
def member(make_user: Callable[..., User], member_role: Role) -> User:
    return make_user(member_role)


@pytest.fixture
def admin(make_user: Callable[..., User], admin_role: Role) -> User:
    return make_user(admin_role)


@pytest.fixture
def member_headers(member: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(member.id)}"}


@pytest.fixture
def admin_headers(admin: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


@pytest.fixture
def manager(make_user: Callable[..., User], make_role: Callable[..., Role]) -> User:
    """A non-superuser holding MANAGE_USERS: the user-administration job is
    deliberately grantable below superuser, so the superuser-account guard
    rules can be tested against a caller who legitimately holds the capability."""
    role = make_role(name="Manager", capabilities=[RoleCapability.MANAGE_USERS])
    return make_user(role)


@pytest.fixture
def manager_headers(manager: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(manager.id)}"}
