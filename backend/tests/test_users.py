"""The users table: the identities the API's tokens are minted for."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

from law_agent.db.repositories import RoleRepository, UserRepository
from law_agent.users.models import DuplicateUserError, UserNotFoundError


def test_the_users_table_exists(db_engine: Engine) -> None:
    inspector = inspect(db_engine)

    assert "users" in inspector.get_table_names()
    assert {index["name"] for index in inspector.get_indexes("users")} >= {"ux_users_email"}


def test_a_user_is_found_by_email(session: Session) -> None:
    role = RoleRepository(session).create("Pravnik")
    repository = UserRepository(session)
    created = repository.create(email="admin@firma.cz", password_hash="hash", role_id=role.id)

    found = repository.get_by_email("admin@firma.cz")

    assert found is not None
    assert found.id == created.id
    assert found.role_id == role.id


def test_an_unknown_email_is_none_rather_than_an_error(session: Session) -> None:
    """Login asks this question about addresses that do not exist; a missing
    user is an ordinary answer, not an exception."""
    assert UserRepository(session).get_by_email("nikdo@firma.cz") is None


def test_the_same_email_cannot_be_registered_twice(session: Session) -> None:
    role = RoleRepository(session).create("Pravnik")
    repository = UserRepository(session)
    repository.create(email="admin@firma.cz", password_hash="hash", role_id=role.id)

    with pytest.raises(DuplicateUserError):
        repository.create(email="admin@firma.cz", password_hash="other", role_id=role.id)


def test_a_users_role_is_reassigned(session: Session) -> None:
    repository = UserRepository(session)
    first = RoleRepository(session).create("Pravnik")
    second = RoleRepository(session).create("Asistent")
    user = repository.create(email="jana@firma.cz", password_hash="hash", role_id=first.id)

    updated = repository.set_role(user.id, role_id=second.id)

    assert updated.role_id == second.id


def test_reassigning_an_unknown_users_role_raises(session: Session) -> None:
    role = RoleRepository(session).create("Pravnik")

    with pytest.raises(UserNotFoundError):
        UserRepository(session).set_role(__import__("uuid").uuid4(), role_id=role.id)


def test_a_user_can_be_deactivated_and_reactivated(session: Session) -> None:
    """Soft delete: the row stays (conversations, ACL grants and the email
    address keep pointing at it), only the flag flips."""
    role = RoleRepository(session).create("Pravnik")
    repository = UserRepository(session)
    user = repository.create(email="jana@firma.cz", password_hash="hash", role_id=role.id)
    assert user.is_active is True

    deactivated = repository.set_active(user.id, active=False)

    assert deactivated.is_active is False
    assert repository.get(user.id).is_active is False

    reactivated = repository.set_active(user.id, active=True)

    assert reactivated.is_active is True


def test_deactivating_an_unknown_user_raises(session: Session) -> None:
    role = RoleRepository(session).create("Pravnik")
    UserRepository(session).create(email="jana@firma.cz", password_hash="hash", role_id=role.id)

    with pytest.raises(UserNotFoundError):
        UserRepository(session).set_active(__import__("uuid").uuid4(), active=False)
