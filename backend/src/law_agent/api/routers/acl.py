"""Access grants: who may see which folder or document, at exactly one node.

Resolving the *effective* set across a whole ancestor chain is
:func:`law_agent.access.service.effective_permission`, which this router does
not expose -- it is consumed directly by retrieval, per the design doc.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from law_agent.access.models import (
    AclEntry,
    InvalidAclGrantError,
    PrincipalType,
    ResourceType,
    RoleCapability,
)
from law_agent.access.service import delete_acl_entry as _delete_acl_entry
from law_agent.access.service import folders_with_nested_grant, inherited_acl_entries, role_for_user
from law_agent.access.service import upsert_acl_entry as _upsert_acl_entry
from law_agent.api.auth.dependencies import (
    CurrentUser,
    require_any_capability,
    require_capability,
)
from law_agent.api.schemas import (
    AclBrowseResponse,
    AclEffectiveResponse,
    AclEntryCreate,
    AclEntryResponse,
)
from law_agent.db import AclRepository, session_scope

router = APIRouter(
    prefix="/acl",
    tags=["acl"],
    dependencies=[
        Depends(require_any_capability(RoleCapability.MANAGE_GROUPS, RoleCapability.MANAGE_USERS))
    ],
)

# A second router sharing the "/users" prefix with users.py's account-management
# router, but with its own dependency -- FastAPI is fine with two routers
# contributing different paths under the same prefix. Lives here, not in
# users.py, because its capability (MANAGE_USERS, matching "who may grant a
# user file access") happens to equal that router's blanket dependency, but
# the two are conceptually unrelated and should not be coupled by accident.
user_acl_router = APIRouter(
    prefix="/users",
    tags=["acl"],
    dependencies=[Depends(require_capability(RoleCapability.MANAGE_USERS))],
)

_PRINCIPAL_CAPABILITY = {
    PrincipalType.GROUP: RoleCapability.MANAGE_GROUPS,
    PrincipalType.USER: RoleCapability.MANAGE_USERS,
}


def _require_principal_capability(user: CurrentUser, principal_type: PrincipalType) -> None:
    """Mutating a grant needs the capability matching *what* is being
    granted, not just any ACL-adjacent one: MANAGE_GROUPS for a group grant,
    MANAGE_USERS for a user grant. Reuses ``require_capability``'s checker
    directly rather than duplicating the role lookup."""
    require_capability(_PRINCIPAL_CAPABILITY[principal_type])(user)


def _managed_principal_types(user: CurrentUser) -> set[PrincipalType]:
    """Which principal types the caller may see grants for.

    The Share panel hides group grants from a MANAGE_USERS-only caller, and
    that hiding has to hold server-side too: a caller without MANAGE_GROUPS
    "shouldn't learn which groups have access at all", which a direct API
    call would otherwise defeat. The capability check is resolved once per
    request, not per entry.
    """
    role = role_for_user(user.user_id)
    if role is None:
        return set()
    if role.is_superuser:
        return set(_PRINCIPAL_CAPABILITY)
    return {
        principal_type
        for principal_type, capability in _PRINCIPAL_CAPABILITY.items()
        if capability in role.capabilities
    }


def _visible_entries(entries: list[AclEntry], managed: set[PrincipalType]) -> list[AclEntry]:
    return [entry for entry in entries if entry.principal_type in managed]


@router.post("", response_model=AclEntryResponse, status_code=status.HTTP_201_CREATED)
def upsert_acl_entry(payload: AclEntryCreate, user: CurrentUser) -> AclEntryResponse:
    _require_principal_capability(user, payload.principal_type)
    try:
        entry = _upsert_acl_entry(
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            principal_type=payload.principal_type,
            principal_id=payload.principal_id,
            permission=payload.permission,
        )
    except InvalidAclGrantError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    return AclEntryResponse.model_validate(entry)


@router.delete("/{acl_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_acl_entry(acl_id: UUID, user: CurrentUser) -> None:
    with session_scope() as session:
        entry = AclRepository(session).get(acl_id)
    if entry is not None:
        _require_principal_capability(user, entry.principal_type)
    _delete_acl_entry(acl_id)


@router.get("", response_model=list[AclEntryResponse])
def list_acl_entries(
    resource_type: ResourceType, resource_id: UUID, user: CurrentUser
) -> list[AclEntryResponse]:
    """The *explicit* grants on exactly this resource, for a "who has access
    to this one folder/file" panel -- not the resolved effective set. Grants
    of a principal type the caller cannot manage are withheld, not just
    hidden client-side."""
    managed = _managed_principal_types(user)
    with session_scope() as session:
        entries = AclRepository(session).list_for_resource(resource_type, resource_id)
    return [AclEntryResponse.model_validate(entry) for entry in _visible_entries(entries, managed)]


@router.get("/effective", response_model=AclEffectiveResponse)
def get_effective_acl(
    resource_type: ResourceType, resource_id: UUID, user: CurrentUser
) -> AclEffectiveResponse:
    """``own`` (editable) vs. ``inherited`` (read-only) grants on one resource
    -- the Share panel's data source. Both halves are filtered the same way
    ``GET /acl`` is: no principal type the caller cannot manage."""
    managed = _managed_principal_types(user)
    with session_scope() as session:
        own = AclRepository(session).list_for_resource(resource_type, resource_id)
    inherited = inherited_acl_entries(resource_type, resource_id)
    return AclEffectiveResponse(
        own=[AclEntryResponse.model_validate(entry) for entry in _visible_entries(own, managed)],
        inherited=[
            AclEntryResponse.model_validate(entry) for entry in _visible_entries(inherited, managed)
        ],
    )


@user_acl_router.get("/{user_id}/acl", response_model=AclBrowseResponse)
def list_user_acl(user_id: UUID) -> AclBrowseResponse:
    """Every grant this user holds directly (not via group membership),
    across every folder and file, plus which folders hold none of their own
    but something deeper inside -- mirrors GET /groups/{id}/acl, feeding the
    per-user access browser the same way that one feeds the group-centric
    browser."""
    with session_scope() as session:
        entries = AclRepository(session).list_for_principal(PrincipalType.USER, user_id)
    return AclBrowseResponse(
        entries=[AclEntryResponse.model_validate(entry) for entry in entries],
        folders_with_nested_grant=sorted(folders_with_nested_grant(PrincipalType.USER, user_id)),
    )
