"""Org files: the shared folder tree and the documents inside it, admin-only.

One line -- the router-level dependency below -- to change if a role other
than a superuser should manage org files later; see the design doc's
Authorization note.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from law_agent.access.models import Permission, RoleCapability
from law_agent.access.service import delete_folder_cascading
from law_agent.api.auth.dependencies import CurrentUser, require_capability
from law_agent.api.schemas import DocumentResponse, FolderCreate, FolderResponse, FolderUpdate
from law_agent.api.uploads import read_upload
from law_agent.db import DocumentRepository, FolderRepository, session_scope
from law_agent.documents.models import (
    Document,
    DocumentNotFoundError,
    DuplicateDocumentError,
    DuplicateFolderError,
    Folder,
    FolderCycleError,
    FolderNotEmptyError,
    FolderNotFoundError,
)
from law_agent.documents.service import delete_document, ingest_document
from law_agent.storage import get_blob_store

router = APIRouter(
    tags=["org-files"],
    dependencies=[Depends(require_capability(RoleCapability.MANAGE_ORG_FILES_STRUCTURE))],
)


def _folder_response(folder: Folder) -> FolderResponse:
    """Every route here is capability-gated on ``MANAGE_ORG_FILES_STRUCTURE``,
    so every caller is, by definition, a structure manager with implicit
    write access everywhere -- no ACL lookup needed."""
    return FolderResponse.model_validate(folder).model_copy(
        update={"effective_permission": Permission.WRITE, "is_structure_manager": True}
    )


def _document_response(document: Document) -> DocumentResponse:
    return DocumentResponse.model_validate(document).model_copy(
        update={"effective_permission": Permission.WRITE, "is_structure_manager": True}
    )


@router.post("/folders", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
def create_folder(payload: FolderCreate) -> FolderResponse:
    with session_scope() as session:
        try:
            folder = FolderRepository(session).create(payload.name, parent_id=payload.parent_id)
        except DuplicateFolderError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        session.commit()
    return _folder_response(folder)


@router.patch("/folders/{folder_id}", response_model=FolderResponse)
def update_folder(folder_id: UUID, payload: FolderUpdate) -> FolderResponse:
    # ``parent_id`` is forwarded only when the request actually sent it: an
    # explicit ``null`` means "move to the root", absence means "leave alone".
    move = {"parent_id": payload.parent_id} if "parent_id" in payload.model_fields_set else {}
    with session_scope() as session:
        try:
            folder = FolderRepository(session).update(folder_id, name=payload.name, **move)
        except FolderNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except (DuplicateFolderError, FolderCycleError) as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        session.commit()
    return _folder_response(folder)


@router.get("/folders", response_model=list[FolderResponse])
def list_folders(parent_id: UUID | None = None) -> list[FolderResponse]:
    with session_scope() as session:
        return [
            _folder_response(folder)
            for folder in FolderRepository(session).children(parent_id)
        ]


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(folder_id: UUID) -> None:
    try:
        delete_folder_cascading(folder_id)
    except FolderNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except FolderNotEmptyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/folders/{folder_id}/files",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_file(
    folder_id: UUID, user: CurrentUser, file: Annotated[UploadFile, File()]
) -> DocumentResponse:
    data = read_upload(file)
    with session_scope() as session:
        folder = FolderRepository(session).get(folder_id)
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="folder not found")

    try:
        document_id = ingest_document(
            data,
            filename=file.filename or "document",
            folder_id=folder_id,
            uploaded_by=str(user.user_id),
        )
    except DuplicateDocumentError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    with session_scope() as session:
        document = DocumentRepository(session).get(document_id)
    return _document_response(document)


@router.get("/folders/{folder_id}/files", response_model=list[DocumentResponse])
def list_files(folder_id: UUID) -> list[DocumentResponse]:
    with session_scope() as session:
        folder = FolderRepository(session).get(folder_id)
        if folder is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="folder not found")
        return [
            _document_response(document)
            for document in DocumentRepository(session).list_by_folder(folder_id)
        ]


@router.delete("/org-files/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(document_id: UUID) -> None:
    """``delete_document`` removes the row and its ACL grants in one
    transaction -- see its docstring in ``documents/service.py``."""
    _require_org_file(document_id)
    try:
        delete_document(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/org-files/{document_id}/download")
def download_file(document_id: UUID) -> StreamingResponse:
    """The only place in the codebase that serves a document's bytes back --
    deliberately not extended to chat attachments, which stay display-only."""
    document = _require_org_file(document_id)
    return StreamingResponse(
        get_blob_store().open(document.blob_sha256),
        media_type=document.mime,
        headers={"Content-Disposition": _content_disposition(document.filename)},
    )


def _require_org_file(document_id: UUID) -> Document:
    """404 for anything that is not an org file. Without the ``folder_id``
    check these admin endpoints would also reach chat attachments, which are
    private to their conversation's owner and stay display-only."""
    with session_scope() as session:
        document = DocumentRepository(session).get(document_id)
    if document is None or document.folder_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return document


def _content_disposition(filename: str) -> str:
    """RFC 5987: the header value must be latin-1, while filenames are Czech.

    The plain ``filename`` carries an ASCII fallback with quotes and control
    characters dropped -- anything else would break out of the quoted string --
    and ``filename*`` carries the exact name, percent-encoded.
    """
    fallback = "".join(c for c in filename if c.isascii() and c.isprintable() and c != '"')
    return f"attachment; filename=\"{fallback or 'download'}\"; filename*=UTF-8''{quote(filename)}"
