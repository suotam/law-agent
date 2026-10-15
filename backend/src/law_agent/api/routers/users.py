"""User management. Accounts are provisioned by an admin -- this is an internal
tool for one firm, so there is no self-registration and no password-reset flow;
passwords are set at provisioning, changed by the account holder, or reset
here by an admin."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from law_agent.access.models import Role, RoleCapability
from law_agent.api.auth.dependencies import CurrentUser, require_any_capability, require_capability
from law_agent.api.auth.security import hash_password
from law_agent.api.schemas import (
    PasswordReset,
    UserCreate,
    UserResponse,
    UserRoleUpdate,
)
from law_agent.db import RoleRepository, UserRepository, session_scope
from law_agent.users.models import DuplicateUserError, User

router = APIRouter(
    tags=["users"],
    dependencies=[Depends(require_capability(RoleCapability.MANAGE_USERS))],
)

# Listing users is also needed by a group manager picking who to add to a
# group, which does not imply MANAGE_USERS -- a second router, same shape as
# acl.py's user_acl_router, so this one endpoint can admit MANAGE_GROUPS too
# while every other account-management endpoint here stays MANAGE_USERS-only.
list_users_router = APIRouter(
    tags=["users"],
    dependencies=[
        Depends(require_any_capability(RoleCapability.MANAGE_USERS, RoleCapability.MANAGE_GROUPS))
    ],
)


def _assert_manageable(
    user_repository: UserRepository,
    role_repository: RoleRepository,
    *,
    caller_id: UUID,
    target: User | None,
    new_role: Role | None,
) -> None:
    """The superuser boundary on account management.

    Three rules, checked against the database state (not the token): a caller
    never manages their own account; and unless the caller is a superuser,
    superuser accounts stay untouched and the superuser role cannot be handed
    out -- otherwise MANAGE_USERS could mint or demote superusers, escalating
    past the capability system that is supposed to be beneath it.
    """

    if target is not None and target.id == caller_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="a user cannot manage their own account"
        )

    caller = user_repository.get(caller_id)
    caller_role = role_repository.get(caller.role_id) if caller else None
    if caller_role is not None and caller_role.is_superuser:
        return

    target_role = role_repository.get(target.role_id) if target is not None else None
    grants_superuser = (new_role is not None and new_role.is_superuser) or (
        target_role is not None and target_role.is_superuser
    )
    if grants_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="superuser accounts are managed by superusers only",
        )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(caller: CurrentUser, payload: UserCreate) -> UserResponse:
    with session_scope() as session:
        user_repository = UserRepository(session)
        role_repository = RoleRepository(session)
        role = role_repository.get(payload.role_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="role not found")
        _assert_manageable(
            user_repository,
            role_repository,
            caller_id=caller.user_id,
            target=None,
            new_role=role,
        )
        try:
            user = user_repository.create(
                email=payload.email,
                password_hash=hash_password(payload.password),
                role_id=payload.role_id,
            )
        except DuplicateUserError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        session.commit()
    return UserResponse.from_domain(user, role)


@list_users_router.get("/users", response_model=list[UserResponse])
def list_users() -> list[UserResponse]:
    with session_scope() as session:
        users = UserRepository(session).list()
        roles = {role.id: role for role in RoleRepository(session).list()}
    return [UserResponse.from_domain(user, roles[user.role_id]) for user in users]


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user_role(caller: CurrentUser, user_id: UUID, payload: UserRoleUpdate) -> UserResponse:
    with session_scope() as session:
        user_repository = UserRepository(session)
        role_repository = RoleRepository(session)
        target = user_repository.get(user_id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no user {user_id}")
        role = role_repository.get(payload.role_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="role not found")
        _assert_manageable(
            user_repository,
            role_repository,
            caller_id=caller.user_id,
            target=target,
            new_role=role,
        )
        user = user_repository.set_role(user_id, role_id=payload.role_id)
        session.commit()
    return UserResponse.from_domain(user, role)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(caller: CurrentUser, user_id: UUID) -> None:
    """Soft delete: the account stops authenticating (login and every existing
    token), but the row stays -- its email address stays reserved and its
    conversations and ACL grants keep pointing at it."""
    with session_scope() as session:
        # The guard's existence check is the 404 source; set_active cannot miss.
        _assert_target_manageable(session, caller_id=caller.user_id, target_id=user_id)
        UserRepository(session).set_active(user_id, active=False)
        session.commit()


@router.post("/users/{user_id}/activate", response_model=UserResponse)
def activate_user(caller: CurrentUser, user_id: UUID) -> UserResponse:
    with session_scope() as session:
        _assert_target_manageable(session, caller_id=caller.user_id, target_id=user_id)
        user = UserRepository(session).set_active(user_id, active=True)
        role = RoleRepository(session).get(user.role_id)
        session.commit()
    return UserResponse.from_domain(user, role)  # type: ignore[arg-type]


def _assert_target_manageable(session: Session, *, caller_id: UUID, target_id: UUID) -> User:
    """The same superuser boundary as role assignment, for deleting an
    account: superuser accounts can only be deactivated by a superuser, and
    nobody deactivates their own. Returns the target for the caller to use."""
    target = UserRepository(session).get(target_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no user {target_id}")
    _assert_manageable(
        UserRepository(session),
        RoleRepository(session),
        caller_id=caller_id,
        target=target,
        new_role=None,
    )
    return target


@router.put("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_user_password(caller: CurrentUser, user_id: UUID, payload: PasswordReset) -> None:
    """An admin resetting an account they hold MANAGE_USERS over. The caller
    proves nothing beyond their capability -- unlike the self-service change,
    there is no current password to verify. Resetting a password is taking the
    account over, so the same superuser boundary applies."""
    with session_scope() as session:
        _assert_target_manageable(session, caller_id=caller.user_id, target_id=user_id)
        UserRepository(session).set_password(user_id, hash_password(payload.new_password))
        session.commit()
