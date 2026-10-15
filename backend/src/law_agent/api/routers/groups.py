"""Group administration: who can see which org files, independent of role."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from law_agent.access.models import GroupNotFoundError, PrincipalType, RoleCapability
from law_agent.access.service import folders_with_nested_grant
from law_agent.api.auth.dependencies import require_capability
from law_agent.api.schemas import (
    AclBrowseResponse,
    AclEntryResponse,
    GroupCreate,
    GroupMemberCreate,
    GroupResponse,
    GroupUpdate,
    UserResponse,
)
from law_agent.db import (
    AclRepository,
    GroupRepository,
    RoleRepository,
    UserRepository,
    session_scope,
)

router = APIRouter(
    prefix="/groups",
    tags=["groups"],
    dependencies=[Depends(require_capability(RoleCapability.MANAGE_GROUPS))],
)

# A second router sharing the "/users" prefix, same shape as acl.py's
# user_acl_router: group membership is group data, so reading which groups
# one user belongs to needs MANAGE_GROUPS (the user-centric membership
# editor), not MANAGE_USERS.
user_groups_router = APIRouter(
    prefix="/users",
    tags=["groups"],
    dependencies=[Depends(require_capability(RoleCapability.MANAGE_GROUPS))],
)


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate) -> GroupResponse:
    with session_scope() as session:
        group = GroupRepository(session).create(payload.name)
        session.commit()
    return GroupResponse.model_validate(group)


@router.get("", response_model=list[GroupResponse])
def list_groups() -> list[GroupResponse]:
    with session_scope() as session:
        return [GroupResponse.model_validate(group) for group in GroupRepository(session).list()]


@router.patch("/{group_id}", response_model=GroupResponse)
def update_group(group_id: UUID, payload: GroupUpdate) -> GroupResponse:
    with session_scope() as session:
        try:
            group = GroupRepository(session).update(group_id, payload.name)
        except GroupNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        session.commit()
    return GroupResponse.model_validate(group)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: UUID) -> None:
    with session_scope() as session:
        try:
            GroupRepository(session).delete(group_id)
            # acl_entries has no FK to groups, so the group's grants are
            # swept here, in the same transaction, rather than dangling.
            AclRepository(session).delete_for_principal(PrincipalType.GROUP, group_id)
        except GroupNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        session.commit()


@router.post("/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def add_member(group_id: UUID, payload: GroupMemberCreate) -> None:
    with session_scope() as session:
        GroupRepository(session).add_member(group_id, payload.user_id)
        session.commit()


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(group_id: UUID, user_id: UUID) -> None:
    with session_scope() as session:
        GroupRepository(session).remove_member(group_id, user_id)
        session.commit()


@router.get("/{group_id}/members", response_model=list[UserResponse])
def list_members(group_id: UUID) -> list[UserResponse]:
    with session_scope() as session:
        members = GroupRepository(session).members(group_id)
        roles = {role.id: role for role in RoleRepository(session).list()}
    return [UserResponse.from_domain(user, roles[user.role_id]) for user in members]


@router.get("/{group_id}/acl", response_model=AclBrowseResponse)
def list_group_acl(group_id: UUID) -> AclBrowseResponse:
    """Every grant this group holds, across every folder and file, plus which
    folders hold none of their own but something deeper inside -- the
    group-centric access browser fetches this once for the whole tree."""
    with session_scope() as session:
        entries = AclRepository(session).list_for_principal(PrincipalType.GROUP, group_id)
    return AclBrowseResponse(
        entries=[AclEntryResponse.model_validate(entry) for entry in entries],
        folders_with_nested_grant=sorted(folders_with_nested_grant(PrincipalType.GROUP, group_id)),
    )


@user_groups_router.get("/{user_id}/groups", response_model=list[GroupResponse])
def list_user_groups(user_id: UUID) -> list[GroupResponse]:
    """Which groups one user belongs to -- the reverse view of membership,
    feeding the user-centric membership editor the same way
    GET /groups/{id}/members feeds the group-centric one."""
    with session_scope() as session:
        if UserRepository(session).get(user_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no user {user_id}")
        group_ids = GroupRepository(session).groups_for_user(user_id)
        groups = [group for group in GroupRepository(session).list() if group.id in group_ids]
    return [GroupResponse.model_validate(group) for group in groups]
