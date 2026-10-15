"""The domain shape of roles, capabilities, groups and access grants.

Separate from the ORM entities in ``law_agent.db.models`` for the same reason
as :mod:`law_agent.documents.models`: callers hold an immutable, fully loaded
object with no session behind it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RoleCapability(StrEnum):
    """A system capability a role may grant. Fixed and code-level -- the set
    of things the app can check is defined by what code exists to check it;
    which roles have which capabilities is what is admin-configurable.
    """

    MANAGE_USERS = "manage_users"
    MANAGE_GROUPS = "manage_groups"
    MANAGE_ORG_FILES_STRUCTURE = "manage_org_files_structure"


class Role(BaseModel):
    """An admin-defined role. ``is_superuser`` bypasses every capability
    check; it is not itself a capability, so a superuser role cannot forget
    one and a capability can never grant "become superuser".
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str
    is_superuser: bool
    capabilities: frozenset[RoleCapability]
    created_at: datetime


class Group(BaseModel):
    """A named set of users, for the purpose of granting org files access."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    name: str
    created_at: datetime


class ResourceType(StrEnum):
    FOLDER = "folder"
    DOCUMENT = "document"


class PrincipalType(StrEnum):
    GROUP = "group"
    USER = "user"


class Permission(StrEnum):
    READ = "read"
    WRITE = "write"


class AclEntry(BaseModel):
    """One access grant: ``principal`` may ``permission`` on ``resource``."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    resource_type: ResourceType
    resource_id: UUID
    principal_type: PrincipalType
    principal_id: UUID
    permission: Permission
    created_at: datetime


class RoleNotFoundError(Exception):
    """No role with this id."""


class RoleInUseError(Exception):
    """A role still assigned to at least one user cannot be deleted."""


class GroupNotFoundError(Exception):
    """No group with this id."""


class InvalidAclGrantError(Exception):
    """A grant that violates a permission-model rule, e.g. ``write`` on a document."""
