"""SQLAlchemy entities. Nothing outside ``law_agent.db`` imports them.

Repositories map these to the pydantic models in ``law_agent.documents``: the
persistence shape and the domain shape are free to drift apart, and a caller
can never hold a detached instance whose lazy load would fail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Folder(Base):
    """A node of the org files tree.

    The tree has several roots -- "Smlouvy", "Faktury" and "Vzory" sit side by
    side, each with ``parent_id IS NULL``; there is no artificial root row.
    """

    __tablename__ = "folders"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    parent_id: Mapped[UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("folders.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ux_folders_sibling_name", "parent_id", "name", unique=True),
        # Postgres does not consider two NULLs equal, so the index above lets
        # two root folders share a name. This partial index forbids it.
        Index(
            "ux_folders_root_name",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
    )


class Document(Base):
    """An uploaded file: its metadata, its blob and its indexing state.

    ``id`` is the ``doc_id`` carried in the Qdrant payload and used as the scope
    of orphan pruning, which makes the identity one across both stores.

    A document is either an org file (``folder_id``) or an in-chat file
    (``conversation_id``, plus ``message_id`` once a message references it).
    The application layer enforces it -- a CHECK constraint would have to be
    dropped and recreated the first time a third location appears.
    """

    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    namespace: Mapped[str] = mapped_column(Text, nullable=False)
    folder_id: Mapped[UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("folders.id", ondelete="RESTRICT"), nullable=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # Set for every in-chat file, with or without a message: an attachment is
    # uploaded and indexed before the message that references it exists, and
    # this is what makes it findable and deletable in the meantime.
    conversation_id: Mapped[UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=True,
    )

    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    blob_sha256: Mapped[str] = mapped_column(Text, nullable=False)

    uploaded_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The same file twice in one folder is always a mistake. Across folders
        # duplication is deliberate: for org files the folder is part of the
        # meaning, and "Vzory / Smlouva" cites differently from "Klient A /
        # Smlouva".
        Index("ux_documents_folder_blob", "folder_id", "blob_sha256", unique=True),
        # Deleting a document asks whether any other row still holds the blob.
        Index("ix_documents_blob_sha256", "blob_sha256"),
    )


class Conversation(Base):
    """A chat thread. Soft-deleted, because cleanup is not transactional and a
    conversation with a client deleted by mistake is an expensive error."""

    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    owner: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # The sidebar's source selection, so that continuing an old conversation
    # runs over the same scope it was answered from.
    meta: Mapped[dict[str, Any]] = mapped_column(
        postgresql.JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # Partial: the conversation list never wants the deleted ones.
        Index(
            "ix_conversations_owner_updated",
            "owner",
            updated_at.desc(),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class Message(Base):
    """One row of a conversation. ``blocks`` is always an array, even for a
    single piece of text -- no reader has to branch on ``str | list``.

    No ``status`` column: an answer is written whole, at the end of the turn,
    so an interrupted turn leaves an unanswered question rather than a broken
    shape.
    """

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(postgresql.JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # No index of its own: messages are always read a whole conversation at a
    # time, which this unique constraint already covers.
    __table_args__ = (Index("ux_messages_conversation_seq", "conversation_id", "seq", unique=True),)


class Role(Base):
    """An admin-defined role: a name, whether it bypasses capability checks
    entirely, and (via ``RoleCapability``) which management actions it grants.
    """

    __tablename__ = "roles"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RoleCapability(Base):
    """One system capability granted to one role. ``capability`` is validated
    against :class:`law_agent.access.models.RoleCapability`, not FK'd to a
    table -- the set of checkable capabilities is defined by what code exists
    to check them.
    """

    __tablename__ = "role_capabilities"

    role_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    capability: Mapped[str] = mapped_column(Text, primary_key=True)


class Group(Base):
    """A named set of users, for the purpose of granting org files access."""

    __tablename__ = "groups"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GroupMember(Base):
    """One user's membership in one group."""

    __tablename__ = "group_members"

    group_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class AclEntry(Base):
    """One access grant: ``principal`` may ``permission`` on ``resource``.

    ``resource_type``/``resource_id`` and ``principal_type``/``principal_id``
    are deliberately not FK columns -- a single FK cannot point at two
    different tables, the same trade-off ``Document`` already makes for "folder
    file vs. chat file". Only ``union`` is ever computed from these rows: a
    resource with no rows of its own inherits its ancestors' grants outright.
    """

    __tablename__ = "acl_entries"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), nullable=False)
    principal_type: Mapped[str] = mapped_column(Text, nullable=False)
    principal_id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), nullable=False)
    permission: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ux_acl_entries_resource_principal",
            "resource_type",
            "resource_id",
            "principal_type",
            "principal_id",
            unique=True,
        ),
    )


class User(Base):
    """An account the API authenticates.

    ``role_id`` is a FK, not a string: see :class:`law_agent.access.models.Role`.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    # Soft delete flag: False means the account no longer authenticates.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ux_users_email", "email", unique=True),)
