"""Member-facing org files views and actions: what one user may see and do,
not what everyone sees. Capability-free by design -- any authenticated
member may call these; `api/routers/org_files.py` stays the admin-only,
capability-gated structure-management surface.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from law_agent.access.member_view import folder_contents, list_roots
from law_agent.access.models import Permission, ResourceType
from law_agent.access.service import (
    effective_permission,
    effective_permissions,
    has_full_org_files_access,
)
from law_agent.api.auth.dependencies import CurrentUser
from law_agent.api.routers.org_files import _content_disposition
from law_agent.api.schemas import (
    DocumentResponse,
    FolderResponse,
    OrgFileRootResponse,
    OrgFilesFolderContentsResponse,
)
from law_agent.api.uploads import read_upload
from law_agent.db import DocumentRepository, session_scope
from law_agent.documents.models import DocumentNotFoundError, DuplicateDocumentError
from law_agent.documents.service import delete_document, ingest_document
from law_agent.storage import get_blob_store

router = APIRouter(prefix="/me/org-files", tags=["me-org-files"])


def _permission_map(
    user_id: UUID,
    pairs: list[tuple[ResourceType, UUID]],
    *,
    is_structure_manager: bool,
) -> dict[tuple[ResourceType, UUID], Permission | None]:
    """A structure manager writes everywhere without holding a single grant;
    everyone else's grants are resolved for the whole listing at once --
    per-row resolver calls used to walk the ancestor chain N×D times."""
    if is_structure_manager:
        return {pair: Permission.WRITE for pair in pairs}
    return effective_permissions(user_id, pairs)


@router.get("/roots", response_model=list[OrgFileRootResponse])
def get_roots(user: CurrentUser) -> list[OrgFileRootResponse]:
    roots = list_roots(user.user_id)
    is_structure_manager = has_full_org_files_access(user.user_id)
    permissions = _permission_map(
        user.user_id,
        [(ResourceType.FOLDER, root.folder.id) for root in roots],
        is_structure_manager=is_structure_manager,
    )
    return [
        OrgFileRootResponse(
            id=root.folder.id,
            name=root.folder.name,
            ancestor_path=root.ancestor_path,
            effective_permission=permissions[(ResourceType.FOLDER, root.folder.id)],
            is_structure_manager=is_structure_manager,
        )
        for root in roots
    ]


@router.get("/folders/{folder_id}", response_model=OrgFilesFolderContentsResponse)
def get_folder(folder_id: UUID, user: CurrentUser) -> OrgFilesFolderContentsResponse:
    contents = folder_contents(user.user_id, folder_id)
    if contents is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="folder not found")
    is_structure_manager = has_full_org_files_access(user.user_id)
    permissions = _permission_map(
        user.user_id,
        [(ResourceType.FOLDER, folder.id) for folder in contents.folders]
        + [(ResourceType.DOCUMENT, document.id) for document in contents.documents],
        is_structure_manager=is_structure_manager,
    )
    folders = [
        FolderResponse.model_validate(folder).model_copy(
            update={
                "effective_permission": permissions[(ResourceType.FOLDER, folder.id)],
                "is_structure_manager": is_structure_manager,
            }
        )
        for folder in contents.folders
    ]
    documents = [
        DocumentResponse.model_validate(document).model_copy(
            update={
                "effective_permission": permissions[(ResourceType.DOCUMENT, document.id)],
                "is_structure_manager": is_structure_manager,
            }
        )
        for document in contents.documents
    ]
    return OrgFilesFolderContentsResponse(folders=folders, files=documents)


@router.post(
    "/folders/{folder_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    folder_id: UUID, user: CurrentUser, file: Annotated[UploadFile, File()]
) -> DocumentResponse:
    permission = effective_permission(user.user_id, ResourceType.FOLDER, folder_id)
    if permission is not Permission.WRITE and not has_full_org_files_access(user.user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="write access required")
    data = read_upload(file)
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
    return DocumentResponse.model_validate(document)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_route(document_id: UUID, user: CurrentUser) -> None:
    with session_scope() as session:
        document = DocumentRepository(session).get(document_id)
    if document is None or document.folder_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    permission = effective_permission(user.user_id, ResourceType.FOLDER, document.folder_id)
    if permission is not Permission.WRITE and not has_full_org_files_access(user.user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="write access required")
    try:
        # `delete_document` already removes the document's own ACL grants in
        # the same transaction as its row -- see its docstring.
        delete_document(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/documents/{document_id}/download")
def download_document(document_id: UUID, user: CurrentUser) -> StreamingResponse:
    with session_scope() as session:
        document = DocumentRepository(session).get(document_id)
    if document is None or document.folder_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    has_read = (
        has_full_org_files_access(user.user_id)
        or effective_permission(user.user_id, ResourceType.DOCUMENT, document_id) is not None
    )
    if not has_read:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return StreamingResponse(
        get_blob_store().open(document.blob_sha256),
        media_type=document.mime,
        headers={"Content-Disposition": _content_disposition(document.filename)},
    )
