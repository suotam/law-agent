"""The domain shape of a user account.

Separate from the ORM entity in ``law_agent.db.models`` for the same reason as
:mod:`law_agent.documents.models`: callers hold an immutable, fully loaded
object with no session behind it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class User(BaseModel):
    """An account. ``password_hash`` never leaves the server.

    ``role_id`` points at :class:`law_agent.access.models.Role` -- what the
    account may do is admin-configurable, not one of two hardcoded strings.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    email: str
    password_hash: str
    role_id: UUID
    # Soft delete: a deactivated account keeps its row (and its email address,
    # which stays reserved), it just stops authenticating.
    is_active: bool
    created_at: datetime


class DuplicateUserError(Exception):
    """An account with this email already exists."""


class UserNotFoundError(Exception):
    """No user with this id."""
