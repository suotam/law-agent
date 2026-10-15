"""Access control: domain models and the permission resolver.

The ``service`` functions are re-exported lazily: ``law_agent.db.repositories``
imports this package's ``models`` for the domain enums, and ``access.service``
in turn needs the repositories -- an eager re-export would make the two
packages import each other, and whichever loaded second would fail.
"""

from typing import TYPE_CHECKING

from law_agent.access.models import (
    AclEntry,
    Group,
    GroupNotFoundError,
    Permission,
    PrincipalType,
    ResourceType,
    Role,
    RoleCapability,
    RoleInUseError,
    RoleNotFoundError,
)

if TYPE_CHECKING:
    from law_agent.access.service import effective_permission, role_for_user

__all__ = [
    "AclEntry",
    "Group",
    "GroupNotFoundError",
    "Permission",
    "PrincipalType",
    "ResourceType",
    "Role",
    "RoleCapability",
    "RoleInUseError",
    "RoleNotFoundError",
    "effective_permission",
    "role_for_user",
]


def __getattr__(name: str) -> object:
    if name in ("effective_permission", "role_for_user"):
        from law_agent.access import service

        return getattr(service, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
