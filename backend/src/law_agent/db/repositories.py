"""Repositories: ORM entities in, pydantic models out.

Transactions belong to the caller. Ingestion commits the ``pending`` row before
a parse that takes minutes and commits again afterwards, so a repository that
committed on its own would take that choice away.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

# ``Role`` here is the *message* role (user/assistant); the access-control
# role imported below is a different concept, so this one is aliased.
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
from law_agent.conversations.models import (
    Conversation,
    ConversationMeta,
    Message,
)
from law_agent.conversations.models import (
    Role as MessageRole,
)
from law_agent.db import models as orm
from law_agent.documents.models import (
    Document,
    DocumentNotFoundError,
    DocumentStatus,
    DuplicateDocumentError,
    DuplicateFolderError,
    Folder,
    FolderCycleError,
    FolderNotEmptyError,
    FolderNotFoundError,
    Namespace,
)
from law_agent.users.models import DuplicateUserError, User, UserNotFoundError

_MAX_SEQ_RETRIES = 5

_UNSET: Any = object()
"""Distinguishes an argument the caller left out from an explicit ``None`` --
``FolderRepository.update`` needs the difference, because ``parent_id=None``
there means "move to the root", not "leave alone"."""


class FolderRepository:
    """The org files tree."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, name: str, *, parent_id: UUID | None = None) -> Folder:
        row = orm.Folder(id=uuid4(), name=name, parent_id=parent_id)
        try:
            # The add belongs inside the savepoint: rolling back to it has to
            # take the rejected object out of the session too, or the next flush
            # would try to insert it again.
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as error:
            msg = f"folder {name!r} already exists at this level"
            raise DuplicateFolderError(msg) from error
        return Folder.model_validate(row)

    def get(self, folder_id: UUID | None) -> Folder | None:
        if folder_id is None:
            return None
        row = self._session.get(orm.Folder, folder_id)
        return Folder.model_validate(row) if row is not None else None

    def children(self, parent_id: UUID | None) -> list[Folder]:
        statement = select(orm.Folder).where(self._parent_is(parent_id)).order_by(orm.Folder.name)
        return [Folder.model_validate(row) for row in self._session.scalars(statement)]

    def ensure_path(self, parts: Sequence[str]) -> Folder:
        """Walk ``parts`` from the roots down, creating what is missing.

        Only the developer CLI uses this; the web UI creates folders explicitly,
        because there a typo would silently grow the tree.
        """
        if not parts:
            msg = "folder path must have at least one segment"
            raise ValueError(msg)

        folder = self._find(parts[0], None) or self.create(parts[0])
        for name in parts[1:]:
            folder = self._find(name, folder.id) or self.create(name, parent_id=folder.id)
        return folder

    def _find(self, name: str, parent_id: UUID | None) -> Folder | None:
        statement = select(orm.Folder).where(orm.Folder.name == name, self._parent_is(parent_id))
        row = self._session.scalars(statement).first()
        return Folder.model_validate(row) if row is not None else None

    @staticmethod
    def _parent_is(parent_id: UUID | None) -> ColumnElement[bool]:
        """``IS NULL`` for a root, plain equality otherwise."""
        if parent_id is None:
            return orm.Folder.parent_id.is_(None)
        return orm.Folder.parent_id == parent_id

    def update(
        self, folder_id: UUID, *, name: str | None = None, parent_id: UUID | None = _UNSET
    ) -> Folder:
        """``parent_id`` omitted leaves the folder where it is; ``None`` moves
        it to the root."""
        row = self._session.get(orm.Folder, folder_id)
        if row is None:
            msg = f"no folder {folder_id}"
            raise FolderNotFoundError(msg)

        if (
            parent_id is not _UNSET
            and parent_id is not None
            and (parent_id == folder_id or self._is_descendant(parent_id, of=folder_id))
        ):
            msg = f"cannot move folder {folder_id} into its own descendant {parent_id}"
            raise FolderCycleError(msg)

        try:
            # The mutation belongs inside the savepoint, same reason as
            # ``create``: begin_nested() autoflushes any *pending* change before
            # opening the SAVEPOINT, so a change made before this block would
            # fail unprotected, outside the block that is supposed to catch it.
            with self._session.begin_nested():
                if name is not None:
                    row.name = name
                if parent_id is not _UNSET:
                    row.parent_id = parent_id
                self._session.flush()
        except IntegrityError as error:
            msg = f"folder {name!r} already exists at this level"
            raise DuplicateFolderError(msg) from error
        self._session.refresh(row)
        return Folder.model_validate(row)

    def delete(self, folder_id: UUID) -> None:
        row = self._session.get(orm.Folder, folder_id)
        if row is None:
            msg = f"no folder {folder_id}"
            raise FolderNotFoundError(msg)
        try:
            with self._session.begin_nested():
                self._session.delete(row)
                self._session.flush()
        except IntegrityError as error:
            msg = f"folder {folder_id} is not empty"
            raise FolderNotEmptyError(msg) from error

    def _is_descendant(self, candidate_id: UUID, *, of: UUID) -> bool:
        """Walk ``candidate_id``'s ancestor chain; ``True`` if it passes through ``of``."""
        current = self._session.get(orm.Folder, candidate_id)
        while current is not None and current.parent_id is not None:
            if current.parent_id == of:
                return True
            current = self._session.get(orm.Folder, current.parent_id)
        return False

    def ancestor_chain(self, folder_id: UUID) -> list[UUID]:
        """``folder_id`` followed by its ancestors up to a root, in that
        order. Empty if ``folder_id`` does not exist -- the caller (the access
        resolver) treats a chain that starts empty as "nothing to check"."""
        chain: list[UUID] = []
        current_id: UUID | None = folder_id
        while current_id is not None:
            row = self._session.get(orm.Folder, current_id)
            if row is None:
                break
            chain.append(current_id)
            current_id = row.parent_id
        return chain

    def subtree_ids(self, folder_ids: Sequence[UUID]) -> set[UUID]:
        """``folder_ids`` plus every folder underneath any of them, via one
        recursive query -- a grant on a folder implies its whole subtree, and
        that subtree can fan out arbitrarily wide, so this must not become
        one query per level."""
        if not folder_ids:
            return set()
        seed = (
            select(orm.Folder.id)
            .where(orm.Folder.id.in_(list(folder_ids)))
            .cte(name="subtree_folders", recursive=True)
        )
        children = select(orm.Folder.id).join(seed, orm.Folder.parent_id == seed.c.id)
        tree = seed.union_all(children)
        return set(self._session.scalars(select(tree.c.id)))


class DocumentRepository:
    """Rows of ``documents``, including their indexing state."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        namespace: Namespace,
        filename: str,
        mime: str,
        byte_size: int,
        blob_sha256: str,
        folder_id: UUID | None = None,
        message_id: UUID | None = None,
        conversation_id: UUID | None = None,
        uploaded_by: str | None = None,
    ) -> Document:
        row = orm.Document(
            id=uuid4(),
            namespace=str(namespace),
            folder_id=folder_id,
            message_id=message_id,
            conversation_id=conversation_id,
            filename=filename,
            mime=mime,
            byte_size=byte_size,
            blob_sha256=blob_sha256,
            uploaded_by=uploaded_by,
            status=str(DocumentStatus.PENDING),
        )
        try:
            # A duplicate upload is an expected outcome the CLI recovers from,
            # so it must not poison the transaction it happened in. The add sits
            # inside the savepoint for the same reason as in FolderRepository.
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as error:
            msg = f"{filename!r} is already in this folder"
            raise DuplicateDocumentError(msg) from error
        return Document.model_validate(row)

    def get(self, document_id: UUID) -> Document | None:
        row = self._session.get(orm.Document, document_id)
        return Document.model_validate(row) if row is not None else None

    def mark_indexed(self, document_id: UUID, *, chunk_count: int) -> None:
        row = self._require(document_id)
        row.status = str(DocumentStatus.INDEXED)
        row.chunk_count = chunk_count
        row.error = None
        row.indexed_at = func.now()
        self._session.flush()
        self._session.refresh(row)

    def mark_failed(self, document_id: UUID, *, error: str) -> None:
        row = self._require(document_id)
        row.status = str(DocumentStatus.FAILED)
        row.error = error
        self._session.flush()

    def delete(self, document_id: UUID) -> None:
        row = self._session.get(orm.Document, document_id)
        if row is not None:
            self._session.delete(row)
            self._session.flush()

    def count_by_blob(self, blob_sha256: str) -> int:
        statement = (
            select(func.count())
            .select_from(orm.Document)
            .where(orm.Document.blob_sha256 == blob_sha256)
        )
        return self._session.scalar(statement) or 0

    def list_by_conversation(self, conversation_id: UUID) -> list[Document]:
        statement = (
            select(orm.Document)
            .where(orm.Document.conversation_id == conversation_id)
            .order_by(orm.Document.uploaded_at)
        )
        return [Document.model_validate(row) for row in self._session.scalars(statement)]

    def attach_to_message(self, document_ids: Sequence[UUID], *, message_id: UUID) -> None:
        """Bind already-indexed attachments to the message that references them.

        The chunks are already in Qdrant under the conversation, so this only
        records which turn used the file -- what the archive's citations need.
        """
        for document_id in document_ids:
            self._require(document_id).message_id = message_id
        self._session.flush()

    def claim(self, document_ids: Sequence[UUID], *, conversation_id: UUID) -> None:
        """Bind previously unbound drafts to ``conversation_id``.

        Metadata only -- the caller is responsible for retagging the matching
        Qdrant points (see ``law_agent.indexing.retag_conversation``), since
        this repository has no vector-store access.
        """
        for document_id in document_ids:
            self._require(document_id).conversation_id = conversation_id
        self._session.flush()

    def list_by_folder(self, folder_id: UUID) -> list[Document]:
        statement = (
            select(orm.Document)
            .where(orm.Document.folder_id == folder_id)
            .order_by(orm.Document.uploaded_at)
        )
        return [Document.model_validate(row) for row in self._session.scalars(statement)]

    def ids_in_folders(self, folder_ids: Sequence[UUID]) -> set[UUID]:
        """Every document id whose ``folder_id`` is in ``folder_ids`` -- the
        cascading-prune helper's view of "documents inside this subtree"."""
        if not folder_ids:
            return set()
        statement = select(orm.Document.id).where(orm.Document.folder_id.in_(list(folder_ids)))
        return set(self._session.scalars(statement))

    def list_unbound(self, *, older_than: datetime) -> list[Document]:
        """Drafts nobody has claimed: no folder, no conversation, uploaded
        before ``older_than``. The grace window is the caller's job to apply."""
        statement = select(orm.Document).where(
            orm.Document.folder_id.is_(None),
            orm.Document.conversation_id.is_(None),
            orm.Document.uploaded_at < older_than,
        )
        return [Document.model_validate(row) for row in self._session.scalars(statement)]

    def _require(self, document_id: UUID) -> orm.Document:
        row = self._session.get(orm.Document, document_id)
        if row is None:
            msg = f"no document {document_id}"
            raise DocumentNotFoundError(msg)
        return row


class ConversationRepository:
    """Chat threads, soft-deleted."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, owner: str, *, title: str, meta: ConversationMeta) -> Conversation:
        # ``mode="json"`` so the jsonb column holds plain strings: an enum member
        # survives the driver only because it subclasses ``str``.
        row = orm.Conversation(
            id=uuid4(), owner=owner, title=title, meta=meta.model_dump(mode="json")
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return Conversation.model_validate(row)

    def get(self, conversation_id: UUID) -> Conversation | None:
        """Returns soft-deleted rows too: an archived conversation is still
        readable, it merely leaves the list."""
        row = self._session.get(orm.Conversation, conversation_id)
        return Conversation.model_validate(row) if row is not None else None

    def list(self, owner: str, *, limit: int = 50) -> list[Conversation]:
        statement = (
            select(orm.Conversation)
            .where(orm.Conversation.owner == owner, orm.Conversation.deleted_at.is_(None))
            .order_by(orm.Conversation.updated_at.desc())
            .limit(limit)
        )
        return [Conversation.model_validate(row) for row in self._session.scalars(statement)]

    def soft_delete(self, conversation_id: UUID) -> None:
        """The messages stay, and so do the documents attached to them --
        otherwise the archive would have nowhere to point its citations."""
        row = self._session.get(orm.Conversation, conversation_id)
        if row is not None:
            row.deleted_at = func.now()
            self._session.flush()

    def touch(self, conversation_id: UUID) -> None:
        """Move the conversation to the top of the list.

        ``clock_timestamp()`` rather than ``now()``: the latter is the start of
        the transaction, so two conversations created and touched in one
        transaction would tie and the ordering would be arbitrary.
        """
        row = self._session.get(orm.Conversation, conversation_id)
        if row is not None:
            row.updated_at = func.clock_timestamp()
            self._session.flush()
            self._session.refresh(row)


class MessageRepository:
    """Rows of one conversation, in ``seq`` order."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self, conversation_id: UUID, *, role: MessageRole, blocks: list[dict[str, Any]]
    ) -> Message:
        """Append one row, taking the next ``seq`` in the writing transaction.

        Two concurrent writers (a double-click, two open panels) can compute
        the same ``seq`` before either commits. The unique constraint on
        ``(conversation_id, seq)`` catches that; retrying with a freshly
        computed ``seq`` is cheaper than serializing every append.
        """
        for _ in range(_MAX_SEQ_RETRIES):
            row = orm.Message(
                id=uuid4(),
                conversation_id=conversation_id,
                seq=self._next_seq(conversation_id),
                role=str(role),
                blocks=blocks,
            )
            try:
                with self._session.begin_nested():
                    self._session.add(row)
                    self._session.flush()
            except IntegrityError:
                continue
            self._session.refresh(row)
            return Message.model_validate(row)
        msg = f"could not allocate seq for conversation {conversation_id}"
        raise RuntimeError(msg)

    def list(self, conversation_id: UUID) -> list[Message]:
        statement = (
            select(orm.Message)
            .where(orm.Message.conversation_id == conversation_id)
            .order_by(orm.Message.seq)
        )
        return [Message.model_validate(row) for row in self._session.scalars(statement)]

    def _next_seq(self, conversation_id: UUID) -> int:
        statement = select(func.coalesce(func.max(orm.Message.seq), 0) + 1).where(
            orm.Message.conversation_id == conversation_id
        )
        return self._session.scalar(statement) or 1


class UserRepository:
    """Accounts. The only place the password hash is read from."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, email: str, password_hash: str, role_id: UUID) -> User:
        row = orm.User(id=uuid4(), email=email, password_hash=password_hash, role_id=role_id)
        try:
            # Inside a savepoint for the same reason as FolderRepository.create:
            # an admin re-adding an existing address is an expected outcome the
            # caller turns into a 409, not a poisoned transaction.
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as error:
            msg = f"user {email!r} already exists"
            raise DuplicateUserError(msg) from error
        return User.model_validate(row)

    def get(self, user_id: UUID) -> User | None:
        row = self._session.get(orm.User, user_id)
        return User.model_validate(row) if row is not None else None

    def get_by_email(self, email: str) -> User | None:
        """``None`` rather than an exception: login asks about addresses that
        do not exist, and that is not an error condition."""
        row = self._session.scalars(select(orm.User).where(orm.User.email == email)).first()
        return User.model_validate(row) if row is not None else None

    def set_role(self, user_id: UUID, *, role_id: UUID) -> User:
        row = self._session.get(orm.User, user_id)
        if row is None:
            msg = f"no user {user_id}"
            raise UserNotFoundError(msg)
        row.role_id = role_id
        self._session.flush()
        self._session.refresh(row)
        return User.model_validate(row)

    def set_active(self, user_id: UUID, *, active: bool) -> User:
        """Soft delete (and its undo): the row never leaves the table, so its
        email address stays reserved and every FK pointing at it stays valid."""
        row = self._session.get(orm.User, user_id)
        if row is None:
            msg = f"no user {user_id}"
            raise UserNotFoundError(msg)
        row.is_active = active
        self._session.flush()
        self._session.refresh(row)
        return User.model_validate(row)

    def set_password(self, user_id: UUID, password_hash: str) -> User:
        row = self._session.get(orm.User, user_id)
        if row is None:
            msg = f"no user {user_id}"
            raise UserNotFoundError(msg)
        row.password_hash = password_hash
        self._session.flush()
        self._session.refresh(row)
        return User.model_validate(row)

    def list(self) -> list[User]:
        statement = select(orm.User).order_by(orm.User.created_at)
        return [User.model_validate(row) for row in self._session.scalars(statement)]


class RoleRepository:
    """Admin-defined roles and the capabilities each one holds."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, name: str) -> Role:
        row = orm.Role(id=uuid4(), name=name, is_superuser=False)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return self._to_model(row, capabilities=frozenset())

    def get(self, role_id: UUID) -> Role | None:
        row = self._session.get(orm.Role, role_id)
        return self._to_model(row, capabilities=self._capabilities(role_id)) if row else None

    def get_by_name(self, name: str) -> Role | None:
        row = self._session.scalars(select(orm.Role).where(orm.Role.name == name)).first()
        return self._to_model(row, capabilities=self._capabilities(row.id)) if row else None

    def list(self) -> list[Role]:
        rows = self._session.scalars(select(orm.Role).order_by(orm.Role.created_at)).all()
        capabilities_by_role = self._capabilities_for([row.id for row in rows])
        return [
            self._to_model(row, capabilities=capabilities_by_role.get(row.id, frozenset()))
            for row in rows
        ]

    def update(self, role_id: UUID, *, name: str | None = None) -> Role:
        row = self._session.get(orm.Role, role_id)
        if row is None:
            msg = f"no role {role_id}"
            raise RoleNotFoundError(msg)
        if name is not None:
            row.name = name
        self._session.flush()
        self._session.refresh(row)
        return self._to_model(row, capabilities=self._capabilities(role_id))

    def set_capabilities(self, role_id: UUID, capabilities: list[RoleCapability]) -> Role:
        """Replaces the full set -- never appends."""
        row = self._session.get(orm.Role, role_id)
        if row is None:
            msg = f"no role {role_id}"
            raise RoleNotFoundError(msg)
        self._session.execute(
            sa_delete(orm.RoleCapability).where(orm.RoleCapability.role_id == role_id)
        )
        for capability in capabilities:
            self._session.add(orm.RoleCapability(role_id=role_id, capability=str(capability)))
        self._session.flush()
        return self._to_model(row, capabilities=frozenset(capabilities))

    def delete(self, role_id: UUID) -> None:
        row = self._session.get(orm.Role, role_id)
        if row is None:
            msg = f"no role {role_id}"
            raise RoleNotFoundError(msg)
        try:
            # Inside a savepoint for the same reason as FolderRepository.delete:
            # a role still assigned to a user is an expected outcome the caller
            # turns into a 409, not a poisoned transaction. The FK from
            # users.role_id (ondelete="RESTRICT") is what raises here.
            with self._session.begin_nested():
                self._session.delete(row)
                self._session.flush()
        except IntegrityError as error:
            msg = f"role {role_id} is still assigned to a user"
            raise RoleInUseError(msg) from error

    def _capabilities(self, role_id: UUID) -> frozenset[RoleCapability]:
        statement = select(orm.RoleCapability.capability).where(
            orm.RoleCapability.role_id == role_id
        )
        return frozenset(RoleCapability(value) for value in self._session.scalars(statement))

    def _capabilities_for(self, role_ids: Sequence[UUID]) -> dict[UUID, frozenset[RoleCapability]]:
        """One query for many roles' capabilities -- ``RoleRepository.list``
        used to issue one query per role (1+R round trips per admin page)."""
        statement = select(orm.RoleCapability.role_id, orm.RoleCapability.capability).where(
            orm.RoleCapability.role_id.in_(role_ids)
        )
        grouped: dict[UUID, set[RoleCapability]] = {}
        for role_id, capability in self._session.execute(statement):
            grouped.setdefault(role_id, set()).add(RoleCapability(capability))
        return {role_id: frozenset(values) for role_id, values in grouped.items()}

    @staticmethod
    def _to_model(row: orm.Role, *, capabilities: frozenset[RoleCapability]) -> Role:
        return Role(
            id=row.id,
            name=row.name,
            is_superuser=row.is_superuser,
            capabilities=capabilities,
            created_at=row.created_at,
        )


class GroupRepository:
    """Admin-defined groups and their membership."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, name: str) -> Group:
        row = orm.Group(id=uuid4(), name=name)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return Group.model_validate(row)

    def get(self, group_id: UUID) -> Group | None:
        row = self._session.get(orm.Group, group_id)
        return Group.model_validate(row) if row is not None else None

    def list(self) -> list[Group]:
        statement = select(orm.Group).order_by(orm.Group.name)
        return [Group.model_validate(row) for row in self._session.scalars(statement)]

    def update(self, group_id: UUID, name: str) -> Group:
        row = self._session.get(orm.Group, group_id)
        if row is None:
            msg = f"no group {group_id}"
            raise GroupNotFoundError(msg)
        row.name = name
        self._session.flush()
        self._session.refresh(row)
        return Group.model_validate(row)

    def delete(self, group_id: UUID) -> None:
        row = self._session.get(orm.Group, group_id)
        if row is None:
            msg = f"no group {group_id}"
            raise GroupNotFoundError(msg)
        self._session.delete(row)
        self._session.flush()

    def add_member(self, group_id: UUID, user_id: UUID) -> None:
        """Idempotent: adding an existing member is a no-op, not a 409 --
        nothing downstream distinguishes "already there" from "just added"."""
        exists = self._session.get(orm.GroupMember, (group_id, user_id))
        if exists is None:
            self._session.add(orm.GroupMember(group_id=group_id, user_id=user_id))
            self._session.flush()

    def remove_member(self, group_id: UUID, user_id: UUID) -> None:
        row = self._session.get(orm.GroupMember, (group_id, user_id))
        if row is not None:
            self._session.delete(row)
            self._session.flush()

    def members(self, group_id: UUID) -> list[User]:
        statement = (
            select(orm.User)
            .join(orm.GroupMember, orm.GroupMember.user_id == orm.User.id)
            .where(orm.GroupMember.group_id == group_id)
            .order_by(orm.User.email)
        )
        return [User.model_validate(row) for row in self._session.scalars(statement)]

    def groups_for_user(self, user_id: UUID) -> set[UUID]:
        statement = select(orm.GroupMember.group_id).where(orm.GroupMember.user_id == user_id)
        return set(self._session.scalars(statement))


def _resources_condition(
    folder_ids: Iterable[UUID], document_ids: Iterable[UUID]
) -> ColumnElement[bool] | None:
    """The folder/document resource-matching half of an ACL prune or delete,
    shared by the cascading-prune and orphan-cleanup paths -- two verbatim
    copies of security-sensitive matching logic is one bug class waiting to
    be fixed in only one of them (as happened once for the ACL fetches)."""
    conditions = []
    folders = list(folder_ids)
    documents = list(document_ids)
    if folders:
        conditions.append(
            tuple_(orm.AclEntry.resource_type, orm.AclEntry.resource_id).in_(
                [(str(ResourceType.FOLDER), folder_id) for folder_id in folders]
            )
        )
    if documents:
        conditions.append(
            tuple_(orm.AclEntry.resource_type, orm.AclEntry.resource_id).in_(
                [(str(ResourceType.DOCUMENT), document_id) for document_id in documents]
            )
        )
    if not conditions:
        return None
    return or_(*conditions)


class AclRepository:
    """Explicit access grants on exactly one resource each. Resolving what a
    user may see across a whole ancestor chain is :func:`law_agent.access.
    service.effective_permission`, not this repository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(
        self,
        *,
        resource_type: ResourceType,
        resource_id: UUID,
        principal_type: PrincipalType,
        principal_id: UUID,
        permission: Permission,
    ) -> AclEntry:
        row = self._find(resource_type, resource_id, principal_type, principal_id)
        if row is not None:
            row.permission = str(permission)
        else:
            row = orm.AclEntry(
                id=uuid4(),
                resource_type=str(resource_type),
                resource_id=resource_id,
                principal_type=str(principal_type),
                principal_id=principal_id,
                permission=str(permission),
            )
            try:
                # Inside a savepoint for the same reason as the other unique-
                # constraint writers here: two concurrent requests for the same
                # (resource, principal) -- a double-click on SharePanel's Add
                # button -- can both pass the not-found-by-select branch, and
                # the loser's INSERT hits ux_acl_entries_resource_principal.
                # The loser must retry as an update, not blow up with a 500.
                with self._session.begin_nested():
                    self._session.add(row)
                    self._session.flush()
            except IntegrityError:
                # Postgres blocks the losing INSERT on the unique index until
                # the winner commits, so the row is visible again by now.
                row = self._find(resource_type, resource_id, principal_type, principal_id)
                if row is None:
                    raise
                row.permission = str(permission)
        self._session.flush()
        self._session.refresh(row)
        return AclEntry.model_validate(row)

    def _find(
        self,
        resource_type: ResourceType,
        resource_id: UUID,
        principal_type: PrincipalType,
        principal_id: UUID,
    ) -> orm.AclEntry | None:
        return self._session.scalars(
            select(orm.AclEntry).where(
                orm.AclEntry.resource_type == str(resource_type),
                orm.AclEntry.resource_id == resource_id,
                orm.AclEntry.principal_type == str(principal_type),
                orm.AclEntry.principal_id == principal_id,
            )
        ).first()

    def resource_ids_for_principals(
        self, resource_type: ResourceType, *, user_id: UUID, group_ids: Iterable[UUID]
    ) -> set[UUID]:
        """Every ``resource_id`` of ``resource_type`` granted directly (any
        permission) to ``user_id`` or one of ``group_ids`` -- the seed set
        retrieval filtering resolves from, not the ancestor-chain check
        :func:`law_agent.access.service.effective_permission` does."""
        principals = [(str(PrincipalType.USER), user_id)] + [
            (str(PrincipalType.GROUP), group_id) for group_id in group_ids
        ]
        statement = select(orm.AclEntry.resource_id).where(
            orm.AclEntry.resource_type == str(resource_type),
            tuple_(orm.AclEntry.principal_type, orm.AclEntry.principal_id).in_(principals),
        )
        return set(self._session.scalars(statement))

    def list_for_principal(
        self, principal_type: PrincipalType, principal_id: UUID
    ) -> list[AclEntry]:
        """Every grant held by one principal, across every resource -- the
        group-centric browser's "which rows already have a grant" query,
        answered once instead of per visited row."""
        statement = select(orm.AclEntry).where(
            orm.AclEntry.principal_type == str(principal_type),
            orm.AclEntry.principal_id == principal_id,
        )
        return [AclEntry.model_validate(row) for row in self._session.scalars(statement)]

    def delete_for_principal(self, principal_type: PrincipalType, principal_id: UUID) -> None:
        """Delete every grant ``principal_id`` holds, across every resource --
        principal-scoped cleanup when the principal itself is deleted. There
        is no FK from ``acl_entries`` to ``groups``, so group deletion must
        sweep these rows itself or ``GET /acl`` keeps listing grants on a
        group that no longer exists."""
        self._session.execute(
            sa_delete(orm.AclEntry).where(
                orm.AclEntry.principal_type == str(principal_type),
                orm.AclEntry.principal_id == principal_id,
            )
        )
        self._session.flush()

    def delete(self, acl_id: UUID) -> None:
        row = self._session.get(orm.AclEntry, acl_id)
        if row is not None:
            self._session.delete(row)
            self._session.flush()

    def get(self, acl_id: UUID) -> AclEntry | None:
        row = self._session.get(orm.AclEntry, acl_id)
        return AclEntry.model_validate(row) if row is not None else None

    def delete_for_principal_on_resources(
        self,
        principal_type: PrincipalType,
        principal_id: UUID,
        *,
        folder_ids: Iterable[UUID],
        document_ids: Iterable[UUID],
    ) -> None:
        """Delete every grant ``principal_id`` holds on any of ``folder_ids`` or
        ``document_ids`` -- the cascading-prune rule: setting or removing a
        folder grant clears that principal's individual grants inside it."""
        condition = _resources_condition(folder_ids, document_ids)
        if condition is None:
            return
        self._session.execute(
            sa_delete(orm.AclEntry).where(
                orm.AclEntry.principal_type == str(principal_type),
                orm.AclEntry.principal_id == principal_id,
                condition,
            )
        )
        self._session.flush()

    def delete_for_resources(
        self, *, folder_ids: Iterable[UUID], document_ids: Iterable[UUID]
    ) -> None:
        """Delete every grant (any principal) on any of ``folder_ids`` or
        ``document_ids`` -- orphan cleanup when the resource itself is deleted."""
        condition = _resources_condition(folder_ids, document_ids)
        if condition is None:
            return
        self._session.execute(sa_delete(orm.AclEntry).where(condition))
        self._session.flush()

    def list_for_resource(self, resource_type: ResourceType, resource_id: UUID) -> list[AclEntry]:
        statement = select(orm.AclEntry).where(
            orm.AclEntry.resource_type == str(resource_type),
            orm.AclEntry.resource_id == resource_id,
        )
        return [AclEntry.model_validate(row) for row in self._session.scalars(statement)]

    def list_for_pairs(self, pairs: Sequence[tuple[ResourceType, UUID]]) -> list[AclEntry]:
        """Every grant on any of ``pairs`` -- the resolver's ancestor chain."""
        if not pairs:
            return []
        statement = select(orm.AclEntry).where(
            tuple_(orm.AclEntry.resource_type, orm.AclEntry.resource_id).in_(
                [(str(resource_type), resource_id) for resource_type, resource_id in pairs]
            )
        )
        return [AclEntry.model_validate(row) for row in self._session.scalars(statement)]
