"""One turn, end to end: question in, streamed answer out, archive written.

The write order is what makes the ``status`` column unnecessary. The question is
inserted before the model is called, so a request that dies still shows what was
asked; everything the turn produces is held in memory and written in one closing
transaction, so an interrupted turn leaves an orphaned question rather than a
tool call with no answer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from pydantic import BaseModel

from law_agent.access.service import (
    accessible_org_folder_ids,
    directly_granted_document_ids,
    has_full_org_files_access,
)
from law_agent.chain.answer import request_search, stream_answer
from law_agent.chain.citations import Numbering
from law_agent.chain.prompt import render_context
from law_agent.chain.tools import to_items
from law_agent.config import settings
from law_agent.conversations.blocks import (
    blocks_from,
    carried_refs,
    offered_items,
    text_block,
    to_langchain,
    tool_result_block,
)
from law_agent.conversations.models import (
    AttachmentNotFoundError,
    Conversation,
    ConversationMeta,
    ConversationNotFoundError,
    Message,
    Role,
    SourceItem,
)
from law_agent.db import (
    ConversationRepository,
    DocumentRepository,
    MessageRepository,
    session_scope,
)
from law_agent.documents.models import Document
from law_agent.documents.service import delete_document, ingest_document
from law_agent.indexing import get_qdrant_client, retag_conversation
from law_agent.retrieval import search

CREATE_TITLE_LENGTH = 30


class Stage(StrEnum):
    """What the turn is doing, for a UI that wants to say so.

    A question with an attachment waits on the parse -- tens of seconds -- and
    that has to read as a step of its own rather than as a frozen spinner.
    """

    ATTACHMENT = "attachment"
    SEARCH = "search"
    ANSWER = "answer"


Progress = Callable[[Stage], None]


class Attachment(BaseModel):
    """A file submitted together with the question."""

    filename: str
    data: bytes


@dataclass
class Answer:
    """The result of a turn: its sources now, its text as it arrives.

    The sources are ready before the first token because the UI renders the
    source panel above the answer.
    """

    items: list[SourceItem]
    _pieces: Iterator[str] = field(repr=False)

    def __iter__(self) -> Iterator[str]:
        return self._pieces


def _truncate(text: str, limit: int) -> str:
    """Collapse whitespace and cut to ``limit`` characters, ellipsis on overflow."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def create_conversation(
    owner: str,
    *,
    user_id: UUID,
    title: str = "",
    meta: ConversationMeta | None = None,
    attachment_ids: Sequence[UUID] = (),
) -> UUID:
    """Start a thread, optionally named and carrying attachments already.

    Its own call rather than an optional ``conversation_id`` on :func:`ask`:
    that would give one argument two behaviours, and the caller would still
    have to be handed the new id back.

    Args:
        user_id: Whose access ceiling ``meta.org_files_folder_ids``/
            ``meta.org_files_document_ids`` are intersected against before
            being frozen -- a stale or tampered client selection can only
            ever narrow, never widen, what ``search()`` already enforces
            (see the chat org files scope picker design doc).

    The title is truncated the same way an auto-derived one is; empty or
    omitted leaves the conversation untitled. Unlike a bad title, a bad
    attachment id is not silently dropped: the row has already committed by
    the time claiming runs, so a client that gets an
    :class:`AttachmentNotFoundError` here should retry by sending the id in a
    message instead of assuming the conversation itself failed.

    Raises:
        AttachmentNotFoundError: an id in ``attachment_ids`` is not a
            claimable draft owned by ``owner``.
    """
    with session_scope() as session:
        conversation = ConversationRepository(session).create(
            owner,
            title=_truncate(title, CREATE_TITLE_LENGTH) if title else "",
            meta=_narrow_org_files_selection(meta or ConversationMeta(), user_id),
        )
        session.commit()

    for attachment_id in attachment_ids:
        _claim(attachment_id, conversation=conversation, owner=owner)

    return conversation.id


def _narrow_org_files_selection(meta: ConversationMeta, user_id: UUID) -> ConversationMeta:
    """Intersect a client-provided folder/document narrowing with the
    caller's actual access ceiling.

    Narrowing is one decision about the whole org-files selection, not one
    per field: once either field is present the conversation is narrowed,
    and the untouched side is frozen as ``[]`` -- leaving it ``None`` would
    mean "no narrowing" downstream in ``search()``, which would keep every
    unrelated direct grant searchable next to the checked folder/document.

    A superuser or a role holding `MANAGE_ORG_FILES_STRUCTURE` has no
    "ceiling" to intersect against: the ACL resolvers return only their
    *personal* grants, which are typically none, and intersecting against
    that would silently wipe out an explicit selection instead of honouring
    it. Mirrors the same reasoning `search()` already applies for full
    access -- their narrowing, if any, is trusted as-is.
    """
    folder_ids = meta.org_files_folder_ids
    document_ids = meta.org_files_document_ids
    if folder_ids is None and document_ids is None:
        return meta

    if has_full_org_files_access(user_id):
        return meta.model_copy(
            update={
                "org_files_folder_ids": list(folder_ids or ()),
                "org_files_document_ids": list(document_ids or ()),
            }
        )

    folder_ceiling = accessible_org_folder_ids(user_id)
    document_ceiling = directly_granted_document_ids(user_id)
    return meta.model_copy(
        update={
            "org_files_folder_ids": (
                [value for value in folder_ids if value in folder_ceiling]
                if folder_ids is not None
                else []
            ),
            "org_files_document_ids": (
                [value for value in document_ids if value in document_ceiling]
                if document_ids is not None
                else []
            ),
        }
    )


def delete_conversation(conversation_id: UUID) -> None:
    """Soft delete. The documents attached to the messages are left alone --
    without the originals the archive's citations lead nowhere."""
    with session_scope() as session:
        ConversationRepository(session).soft_delete(conversation_id)
        session.commit()


def history(conversation_id: UUID) -> list[Message]:
    """Every stored row of the conversation, in order."""
    with session_scope() as session:
        return MessageRepository(session).list(conversation_id)


def attachments(conversation_id: UUID) -> list[Document]:
    """Files uploaded to this conversation that no message references yet."""
    with session_scope() as session:
        return [
            document
            for document in DocumentRepository(session).list_by_conversation(conversation_id)
            if document.message_id is None
        ]


def sent_attachments(conversation_id: UUID) -> dict[UUID, list[Document]]:
    """Files this conversation's messages were sent with, by message id.

    The counterpart of :func:`attachments`: that one answers what a draft is
    holding, this one what the archive should show. Splitting them keeps a
    caller from having to read the meaning out of a null ``message_id``.
    """
    grouped: dict[UUID, list[Document]] = {}
    with session_scope() as session:
        documents = DocumentRepository(session).list_by_conversation(conversation_id)
    for document in documents:
        if document.message_id is not None:
            grouped.setdefault(document.message_id, []).append(document)
    return grouped


def add_attachment(
    data: bytes,
    *,
    filename: str,
    conversation_id: UUID | None = None,
    uploaded_by: str | None = None,
) -> Document:
    """Upload a file, optionally bound to a conversation immediately.

    Synchronous on purpose: the document is parsed, chunked and indexed before
    this returns, so a caller that has the id back can safely put it in a
    question -- there is no window in which the attachment is saved but not yet
    searchable.

    ``conversation_id`` given ingests straight into that conversation, exactly
    as before. Omitted, the file is ingested as an unbound draft: indexed
    under ``USER_FILES`` but unreachable by search until something claims it.

    Raises:
        ConversationNotFoundError: ``conversation_id`` given but unknown.
    """
    if conversation_id is not None:
        _require(conversation_id)
    document_id = ingest_document(
        data,
        filename=filename,
        conversation_id=conversation_id,
        uploaded_by=uploaded_by,
    )
    with session_scope() as session:
        document = DocumentRepository(session).get(document_id)
    if document is None:  # pragma: no cover - the row was just written
        msg = f"no document {document_id}"
        raise AttachmentNotFoundError(msg)
    return document


def remove_attachment(document_id: UUID, *, owner: str) -> None:
    """Drop an upload no message has referenced yet -- draft or already placed
    in a conversation, whichever it is.

    A file already referenced by a message stays: removing it would leave that
    turn's citations pointing at nothing.

    Raises:
        AttachmentNotFoundError: not this owner's upload, or already used by a
            message.
    """
    with session_scope() as session:
        document = DocumentRepository(session).get(document_id)
    if document is None or document.uploaded_by != owner or document.message_id is not None:
        msg = f"no pending attachment {document_id} for {owner}"
        raise AttachmentNotFoundError(msg)
    delete_document(document_id)


def _claim(document_id: UUID, *, conversation: Conversation, owner: str) -> Document:
    """Bind an unbound draft to ``conversation``: a metadata move, never a
    re-parse or re-chunk -- the draft is already indexed, just unreachable.

    Raises:
        AttachmentNotFoundError: not a claimable draft of ``owner``'s (unknown
            id, already placed, or already used by a message).
    """
    with session_scope() as session:
        document = DocumentRepository(session).get(document_id)
    if (
        document is None
        or document.conversation_id is not None
        or document.folder_id is not None
        or document.message_id is not None
        or document.uploaded_by != owner
    ):
        msg = f"no claimable draft {document_id} for {owner}"
        raise AttachmentNotFoundError(msg)

    with session_scope() as session:
        DocumentRepository(session).claim([document_id], conversation_id=conversation.id)
        session.commit()

    retag_conversation(
        get_qdrant_client(),
        settings.qdrant_collection,
        doc_id=document_id,
        conversation_id=conversation.id,
    )

    with session_scope() as session:
        claimed = DocumentRepository(session).get(document_id)
    if claimed is None:  # pragma: no cover - just written
        msg = f"no document {document_id}"
        raise AttachmentNotFoundError(msg)
    return claimed


def _ensure_bound(conversation: Conversation, document_id: UUID) -> None:
    """Already belonging to ``conversation`` is a no-op; an unbound draft of
    its owner is claimed now, in place of a read-only pending check -- a
    client can send an id straight from an unbound upload and the turn itself
    finishes the binding.

    Raises:
        AttachmentNotFoundError: not this conversation's, and not a claimable
            draft of its owner's either.
    """
    with session_scope() as session:
        document = DocumentRepository(session).get(document_id)
    if document is not None and document.conversation_id == conversation.id:
        return
    _claim(document_id, conversation=conversation, owner=conversation.owner)


def ask(
    conversation_id: UUID,
    question: str,
    *,
    user_id: UUID,
    attachments: Sequence[Attachment] = (),
    attachment_ids: Sequence[UUID] = (),
    model: BaseChatModel | None = None,
    progress: Progress | None = None,
) -> Answer:
    """Run one turn of the conversation.

    Args:
        conversation_id: An existing conversation; its ``meta`` is the single
            source of truth for the retrieval scope.
        question: What the user typed.
        user_id: Whose access ceiling gates `org_files` retrieval for this
            turn -- threaded straight into `search()`.
        attachments: Files submitted with the question. Ingested before
            retrieval, or the model would not know about a file just attached.
        attachment_ids: Files already uploaded -- to this conversation, or
            still an unbound draft of its owner's. Bound to the question
            rather than ingested again; an unbound id is claimed against this
            conversation as a side effect.
        model: Injection point for tests; production callers omit it.
        progress: Called as the turn moves between stages, so a UI can name the
            step it is waiting on.

    Returns:
        An :class:`Answer` whose sources are ready immediately and whose text
        arrives by iteration. Nothing beyond the question is stored until that
        iteration completes.

    Raises:
        ConversationNotFoundError: No conversation with this id.
        AttachmentNotFoundError: An id that is not a pending attachment of this
            conversation.
    """
    conversation = _require(conversation_id)
    report = progress or (lambda _stage: None)

    for attachment_id in attachment_ids:
        _ensure_bound(conversation, attachment_id)

    user_message = _append(conversation_id, Role.USER, [text_block(question)])
    if attachment_ids:
        with session_scope() as session:
            DocumentRepository(session).attach_to_message(
                attachment_ids, message_id=user_message.id
            )
            session.commit()

    for attachment in attachments:
        report(Stage.ATTACHMENT)
        ingest_document(
            attachment.data,
            filename=attachment.filename,
            message_id=user_message.id,
            conversation_id=conversation_id,
        )

    stored = history(conversation_id)
    replayed = to_langchain(stored, render=render_context)

    report(Stage.SEARCH)
    call = request_search(replayed, model=model)
    tool_call = call.tool_calls[0]
    chunks = search(
        str(tool_call["args"]["query"]),
        scope=conversation.meta.scope,
        limit=conversation.meta.limit,
        conversation_id=conversation_id,
        user_id=user_id,
        org_files_folder_ids=conversation.meta.org_files_folder_ids,
        org_files_document_ids=conversation.meta.org_files_document_ids,
    )
    # Numbered against the whole conversation, not this round: a chunk found
    # again keeps the ref the model already has in front of it, and a new one
    # takes a number nothing else has ever used.
    items = to_items(chunks, numbering=Numbering.of(offered_items(stored)))
    tool_message = ToolMessage(
        content=render_context(items, carried_refs(stored)),
        tool_call_id=str(tool_call["id"]),
    )

    report(Stage.ANSWER)
    pieces = _stream_and_store(
        conversation_id,
        messages=[*replayed, call, tool_message],
        call=call,
        tool_call_id=str(tool_call["id"]),
        items=items,
        model=model,
    )
    return Answer(items=items, _pieces=pieces)


def _stream_and_store(
    conversation_id: UUID,
    *,
    messages: Sequence[BaseMessage],
    call: BaseMessage,
    tool_call_id: str,
    items: Sequence[SourceItem],
    model: BaseChatModel | None,
) -> Iterator[str]:
    collected: list[str] = []
    for piece in stream_answer(messages, model=model):
        collected.append(piece)
        yield piece

    # One transaction at the end: an exception or a client disconnect before this
    # point leaves the question alone in the archive, never a half-written turn.
    with session_scope() as session:
        repository = MessageRepository(session)
        repository.append(conversation_id, role=Role.ASSISTANT, blocks=blocks_from(call))
        repository.append(
            conversation_id, role=Role.TOOL, blocks=[tool_result_block(tool_call_id, items)]
        )
        repository.append(
            conversation_id, role=Role.ASSISTANT, blocks=[text_block("".join(collected))]
        )
        ConversationRepository(session).touch(conversation_id)
        session.commit()


def _append(conversation_id: UUID, role: Role, blocks: list[dict[str, Any]]) -> Message:
    with session_scope() as session:
        message = MessageRepository(session).append(conversation_id, role=role, blocks=blocks)
        session.commit()
    return message


def _require(conversation_id: UUID) -> Conversation:
    with session_scope() as session:
        conversation = ConversationRepository(session).get(conversation_id)
    if conversation is None:
        msg = f"no conversation {conversation_id}"
        raise ConversationNotFoundError(msg)
    return conversation
