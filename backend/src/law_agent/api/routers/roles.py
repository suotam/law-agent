"""Role and capability administration.

Mutations are not gated by any capability -- see the design doc's
Authorization note: a capability could otherwise let a non-superuser role
hand itself more capabilities than it started with, which is exactly what
superuser-only bootstraps outside the thing it configures. Listing roles
carries no such risk, so it only requires MANAGE_USERS: a user administrator
needs the list to populate a role picker when editing a user's role.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from law_agent.access.models import Role, RoleCapability, RoleInUseError, RoleNotFoundError
from law_agent.api.auth.dependencies import require_capability, require_superuser
from law_agent.api.schemas import RoleCapabilitiesUpdate, RoleCreate, RoleResponse, RoleUpdate
from law_agent.db import RoleRepository, session_scope

router = APIRouter(prefix="/roles", tags=["roles"])


@router.post(
    "",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_superuser)],
)
def create_role(payload: RoleCreate) -> RoleResponse:
    with session_scope() as session:
        role = RoleRepository(session).create(payload.name)
        session.commit()
    return RoleResponse.from_domain(role)


@router.get(
    "",
    response_model=list[RoleResponse],
    dependencies=[Depends(require_capability(RoleCapability.MANAGE_USERS))],
)
def list_roles() -> list[RoleResponse]:
    with session_scope() as session:
        return [RoleResponse.from_domain(role) for role in RoleRepository(session).list()]


@router.patch("/{role_id}", response_model=RoleResponse, dependencies=[Depends(require_superuser)])
def update_role(role_id: UUID, payload: RoleUpdate) -> RoleResponse:
    with session_scope() as session:
        _assert_editable(session, role_id)
        try:
            role = RoleRepository(session).update(role_id, name=payload.name)
        except RoleNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        session.commit()
    return RoleResponse.from_domain(role)


@router.put(
    "/{role_id}/capabilities",
    response_model=RoleResponse,
    dependencies=[Depends(require_superuser)],
)
def replace_capabilities(role_id: UUID, payload: RoleCapabilitiesUpdate) -> RoleResponse:
    with session_scope() as session:
        _assert_editable(session, role_id)
        try:
            role = RoleRepository(session).set_capabilities(role_id, payload.capabilities)
        except RoleNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        session.commit()
    return RoleResponse.from_domain(role)


@router.delete(
    "/{role_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_superuser)]
)
def delete_role(role_id: UUID) -> None:
    with session_scope() as session:
        _assert_editable(session, role_id)
        try:
            RoleRepository(session).delete(role_id)
        except RoleNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except RoleInUseError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        session.commit()


def _assert_editable(session: Session, role_id: UUID) -> Role:
    """A superuser role is immutable and undeletable, even for a superuser.

    The API cannot create another superuser role (``is_superuser`` is only
    ever set by the seed migration / bootstrap script), so deleting the last
    one would leave the deployment with no way back into superuser
    administration. Renaming and capability edits are blocked with it: the
    name is the bootstrap surface scripts point at, and capabilities on a
    role that bypasses every check are decoration."""
    role = RoleRepository(session).get(role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no role {role_id}")
    if role.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="superuser roles cannot be modified"
        )
    return role
