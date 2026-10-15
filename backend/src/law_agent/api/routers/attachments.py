"""Freestanding uploads: files that may or may not yet belong to a conversation.

Split from ``conversations.py`` because an attachment now exists before any
conversation does -- the FE uploads first and only creates (or messages) a
conversation once something is actually said.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from law_agent.api.auth.dependencies import CurrentUser
from law_agent.api.routers.conversations import owned_conversation
from law_agent.api.schemas import DocumentResponse
from law_agent.api.uploads import read_upload
from law_agent.conversations.models import AttachmentNotFoundError
from law_agent.conversations.service import add_attachment, remove_attachment

router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload(
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    conversation_id: Annotated[UUID | None, Form()] = None,
) -> DocumentResponse:
    """One file per request, blocking until it is indexed.

    ``conversation_id`` given places it there immediately, exactly as the old
    nested endpoint did -- ownership-checked the same way :func:`owned_conversation`
    always has been, just called directly instead of through the path. Omitted,
    the upload is a draft owned by the caller: indexed, but unreachable by
    search until a conversation claims it.
    """
    data = read_upload(file)
    conversation = (
        owned_conversation(conversation_id, user) if conversation_id is not None else None
    )
    document = add_attachment(
        data,
        filename=file.filename or "attachment",
        conversation_id=conversation.id if conversation is not None else None,
        uploaded_by=str(user.user_id),
    )
    return DocumentResponse.model_validate(document)


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(attachment_id: UUID, user: CurrentUser) -> None:
    """Removes an upload no message has referenced yet -- draft or already
    placed in a conversation. A file still uploading is cancelled by aborting
    its own request instead."""
    try:
        remove_attachment(attachment_id, owner=str(user.user_id))
    except AttachmentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
