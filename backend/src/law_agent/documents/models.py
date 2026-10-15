"""The domain shape of a document and a folder.

Separate from the ORM entities in ``law_agent.db.models`` on purpose: callers
get an immutable, fully loaded object with no session behind it, and the
storage shape can change without changing what the application passes around.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from law_agent.ingestion.files import NAMESPACE as FILES_NAMESPACE
from law_agent.ingestion.laws import NAMESPACE as LAWS_NAMESPACE


class Namespace(StrEnum):
    """Which corpus a document's chunks are indexed into.

    A plain ``text`` column in Postgres, validated here: adding a namespace is
    then a value, not a migration.
    """

    ORG_FILES = "org_files"
    USER_FILES = "user_files"


class DocumentStatus(StrEnum):
    """How far ingestion got.

    Columns on ``documents`` rather than a history table: the UI needs "did it
    pass, and if not why", not a time series of attempts.
    """

    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class ScopeSource(StrEnum):
    """A corpus a client may switch on or off for a conversation.

    Narrower than :class:`Namespace`: ``user_files`` is not listed, because a
    conversation's own attachments are always searched and are not part of
    the choice.

    The values come from the ingestion modules rather than being spelled again,
    so a namespace cannot be renamed on one side only. Defined here, next to
    ``Namespace``, and not in ``law_agent.retrieval``, because
    ``conversations.models`` (which the ``law_agent.db`` repositories import)
    types ``ConversationMeta.scope`` with it -- retrieval imports access, and
    access imports the repositories: a definition over there closes a loop.
    """

    LAWS = LAWS_NAMESPACE
    ORG_FILES = FILES_NAMESPACE


DEFAULT_SCOPE = (ScopeSource.LAWS, ScopeSource.ORG_FILES)


class Folder(BaseModel):
    """A node of the org files tree; several nodes may have no parent."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    parent_id: UUID | None
    name: str
    created_at: datetime


class Document(BaseModel):
    """An uploaded file. ``id`` is the ``doc_id`` in the Qdrant payload."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    namespace: Namespace
    folder_id: UUID | None
    message_id: UUID | None
    conversation_id: UUID | None
    filename: str
    mime: str
    byte_size: int
    blob_sha256: str
    uploaded_by: str | None
    uploaded_at: datetime
    status: DocumentStatus
    error: str | None
    chunk_count: int | None
    indexed_at: datetime | None


class DuplicateDocumentError(Exception):
    """The same content is already in this folder -- always a mistake."""


class DuplicateFolderError(Exception):
    """A sibling folder of this name already exists."""


class FolderNotFoundError(Exception):
    """No folder with this id."""


class FolderNotEmptyError(Exception):
    """A folder holding child folders or documents cannot be deleted."""


class FolderCycleError(Exception):
    """Moving a folder into itself or one of its own descendants."""


class DocumentNotFoundError(Exception):
    """No document with this id."""
