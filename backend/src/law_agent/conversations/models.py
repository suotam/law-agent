"""The domain shape of a conversation, a message and a retrieved source.

Separate from the ORM entities in ``law_agent.db.models`` for the same reason
as :mod:`law_agent.documents.models`: callers hold an immutable, fully loaded
object with no session behind it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from law_agent.documents.models import DEFAULT_SCOPE, ScopeSource


class Role(StrEnum):
    """Who a message row belongs to.

    A plain ``text`` column in Postgres, validated here: a fourth role is then
    a value, not a migration.
    """

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class SourceItem(BaseModel):
    """One numbered source a tool offered the model.

    ``ref`` is what a ``[n]`` mark in the answer points at -- an identifier,
    not a position in a list. It is assigned before the model sees the
    material and stored, so it can never drift from what the model actually
    read.

    ``content`` is opaque and shaped by whichever tool produced the item; only
    ``ref``, ``kind`` and ``label`` are shared across tools.
    """

    model_config = ConfigDict(frozen=True)

    ref: int
    kind: str
    """``law`` or ``document`` today; tells the UI how to resolve the link."""

    label: str
    """What the user sees, e.g. ``§ 1829 obč. zák.``."""

    content: dict[str, Any]


class ConversationMeta(BaseModel):
    """The sidebar's source selection, frozen with the conversation.

    A pydantic model rather than a free-form dict: a jsonb column with no
    declared shape turns into a junk drawer within a month.

    ``org_files_folder_ids``/``org_files_document_ids``: ``None`` means "no
    narrowing, search the full access ceiling" (today's behaviour); a
    concrete list narrows `org_files` retrieval to that subset, and is
    intersected with the caller's ceiling at creation time
    (`conversations/service.py:create_conversation`), never trusted outright.
    """

    model_config = ConfigDict(frozen=True)

    scope: list[ScopeSource] = Field(default_factory=lambda: list(DEFAULT_SCOPE))
    limit: int = 10
    org_files_folder_ids: list[UUID] | None = None
    org_files_document_ids: list[UUID] | None = None


class Conversation(BaseModel):
    """A chat thread. ``deleted_at`` set means soft-deleted."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    owner: str
    title: str
    meta: ConversationMeta
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    """One row of a conversation; ``blocks`` is always an array."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    conversation_id: UUID
    seq: int
    role: Role
    blocks: list[dict[str, Any]]
    created_at: datetime


class ConversationNotFoundError(Exception):
    """No conversation with this id, or it is soft-deleted."""


class AttachmentNotFoundError(Exception):
    """No such attachment in this conversation, or it is already used by a message."""
