"""Conversations: CRUD, history, attachments and the chat turn.

Every endpoint here resolves the conversation through :func:`owned_conversation`,
which is also the authorisation check -- a thread belonging to somebody else is
indistinguishable from one that does not exist.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from law_agent.api.auth.dependencies import CurrentUser
from law_agent.api.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationResponse,
    HistoryMessage,
    MessageRequest,
)
from law_agent.api.streaming import (
    UI_MESSAGE_STREAM_HEADERS,
    attachments_part,
    sources_part,
    ui_message_stream,
)
from law_agent.conversations.blocks import TEXT, TOOL_USE, offered_items, turns
from law_agent.conversations.models import (
    AttachmentNotFoundError,
    Conversation,
    ConversationMeta,
    Message,
    Role,
)
from law_agent.conversations.service import (
    ask,
    create_conversation,
    delete_conversation,
    history,
    sent_attachments,
)
from law_agent.db import ConversationRepository, session_scope
from law_agent.documents.models import Document

router = APIRouter(prefix="/conversations", tags=["conversations"])


def owned_conversation(conversation_id: UUID, user: CurrentUser) -> Conversation:
    """The conversation, if it is this user's and not deleted.

    404 rather than 403 for somebody else's thread: a 403 would confirm the id
    exists.
    """
    with session_scope() as session:
        conversation = ConversationRepository(session).get(conversation_id)
    if (
        conversation is None
        or conversation.owner != str(user.user_id)
        or conversation.deleted_at is not None
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    return conversation


OwnedConversation = Annotated[Conversation, Depends(owned_conversation)]


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create(payload: ConversationCreate, user: CurrentUser) -> ConversationResponse:
    """An empty or attachment-carrying thread. The FE calls this lazily -- at
    the first attachment or the first message, whichever comes first -- and
    the id is always ours, never one the client made up."""
    defaults = ConversationMeta()
    meta = ConversationMeta(
        scope=payload.scope if payload.scope is not None else defaults.scope,
        limit=payload.limit if payload.limit is not None else defaults.limit,
        org_files_folder_ids=payload.org_files_folder_ids,
        org_files_document_ids=payload.org_files_document_ids,
    )
    try:
        conversation_id = create_conversation(
            str(user.user_id),
            user_id=user.user_id,
            title=payload.title or "",
            meta=meta,
            attachment_ids=payload.attachment_ids,
        )
    except AttachmentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    with session_scope() as session:
        conversation = ConversationRepository(session).get(conversation_id)
    if conversation is None:  # pragma: no cover - the row was just committed
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="conversation vanished"
        )
    return ConversationResponse.model_validate(conversation)


@router.get("", response_model=list[ConversationResponse])
def list_conversations(user: CurrentUser) -> list[ConversationResponse]:
    with session_scope() as session:
        conversations = ConversationRepository(session).list(str(user.user_id))
    return [ConversationResponse.model_validate(item) for item in conversations]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation: OwnedConversation) -> ConversationDetail:
    """One thread with its retrieval scope, for a client opening it from history.

    ``meta`` is flattened into the response rather than nested: the scope is
    frozen at creation and never sent back, so a nested object would only
    suggest it can be written.
    """
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        scope=conversation.meta.scope,
        limit=conversation.meta.limit,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(conversation: OwnedConversation) -> None:
    delete_conversation(conversation.id)


@router.post("/{conversation_id}/messages")
def send_message(
    conversation: OwnedConversation, payload: MessageRequest, user: CurrentUser
) -> StreamingResponse:
    """One turn, streamed.

    ``ask`` runs before the response is returned, which is what lets an unknown
    attachment or a missing conversation still be a status code: it resolves
    everything and produces the sources before the first token exists. Anything
    that goes wrong after this point is an error part inside the stream.
    """
    try:
        answer = ask(
            conversation.id,
            payload.question,
            user_id=user.user_id,
            attachment_ids=payload.attachment_ids,
        )
    except AttachmentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return StreamingResponse(
        ui_message_stream(answer, message_id=str(uuid4())),
        media_type="text/event-stream",
        headers=UI_MESSAGE_STREAM_HEADERS,
    )


@router.get("/{conversation_id}/history", response_model=list[HistoryMessage])
def get_history(conversation: OwnedConversation) -> list[HistoryMessage]:
    return _history_messages(history(conversation.id), sent_attachments(conversation.id))


def _history_messages(
    messages: Sequence[Message], attachments: Mapping[UUID, Sequence[Document]]
) -> list[HistoryMessage]:
    """The archive as chat.

    The search round is dropped: a ``tool_use`` message is machinery, and its
    ``tool_result`` sibling comes back attached to the answer as the sources
    part instead -- the same shape the live stream sends.
    """
    replayed: list[HistoryMessage] = []
    for turn in turns(messages):
        items = list(offered_items(turn).values())
        for message in turn:
            if message.role is Role.USER:
                parts = [_text_part(message)]
                if files := attachments.get(message.id):
                    parts.insert(0, attachments_part(files))
                replayed.append(HistoryMessage(id=str(message.id), role="user", parts=parts))
            elif message.role is Role.ASSISTANT and not _is_search_round(message):
                parts = [_text_part(message)]
                if items:
                    parts.append(sources_part(items))
                replayed.append(HistoryMessage(id=str(message.id), role="assistant", parts=parts))
    return replayed


def _is_search_round(message: Message) -> bool:
    return any(block.get("type") == TOOL_USE for block in message.blocks)


def _text_part(message: Message) -> dict[str, Any]:
    text = "\n".join(
        str(block.get("text", "")) for block in message.blocks if block.get("type") == TEXT
    )
    return {"type": "text", "text": text}
