"""Member-facing read views over org files: "what can I see", not "what
does everyone see" (that stays admin-only, `api/routers/org_files.py`).

Distinct from `access/service.py`'s resolvers, which return raw id sets for
retrieval filtering: this module shapes them into folders/documents with
plain-text ancestor breadcrumbs for the file browser and chat scope picker.
See `docs/superpowers/specs/2026-09-05-org-files-access-redesign-design.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from law_agent.access.service import (
    FolderAccessSets,
    folder_access_sets,
    has_full_org_files_access,
)
from law_agent.db import DocumentRepository, FolderRepository, session_scope
from law_agent.documents.models import Document, Folder


@dataclass(frozen=True)
class OrgFileRoot:
    """A virtual root: a folder in the caller's visible set whose real
    parent is not visible -- inheritance and path visibility both only flow
    down/along a document's ancestors, never sideways. ``ancestor_path`` is
    the real chain above it, shown as context only -- browsing further up is
    not offered."""

    folder: Folder
    ancestor_path: str


@dataclass(frozen=True)
class FolderContents:
    """The children of one visible folder, filtered:

    - subfolders: shown iff they are themselves in the visible set.
    - documents: every document if the folder itself is retrievable (a
      folder grant covers its whole subtree); only the directly granted ones
      if the folder is merely on a path to a granted document.
    """

    folders: list[Folder]
    documents: list[Document]


def list_roots(user_id: UUID) -> list[OrgFileRoot]:
    """The topmost folders in ``user_id``'s visible set -- every real
    top-level folder for a full-access holder (superuser or
    ``MANAGE_ORG_FILES_STRUCTURE``), who bypasses the resolvers entirely."""
    with session_scope() as session:
        folder_repo = FolderRepository(session)
        if has_full_org_files_access(user_id):
            return [
                OrgFileRoot(folder=folder, ancestor_path="")
                for folder in folder_repo.children(None)
            ]
        visible = folder_access_sets(user_id).visible_folders
        roots: list[OrgFileRoot] = []
        for folder_id in visible:
            folder = folder_repo.get(folder_id)
            # A folder deleted after the resolver scan resolved its id is
            # skipped, not surfaced as a dangling row.
            if folder is None:
                continue
            if folder.parent_id is not None and folder.parent_id in visible:
                continue  # not a virtual root: its parent is browsable too
            roots.append(
                OrgFileRoot(
                    folder=folder, ancestor_path=_ancestor_path(folder_repo, folder.parent_id)
                )
            )
        return roots


def folder_contents(user_id: UUID, folder_id: UUID) -> FolderContents | None:
    """``None`` when ``folder_id`` is outside the caller's visible set -- the
    router turns that into a 404 without confirming the folder exists. A
    full-access holder's visible set is every folder, so this only checks
    the folder actually exists for them."""
    has_full_access = has_full_org_files_access(user_id)
    if has_full_access:
        with session_scope() as session:
            folder_repo = FolderRepository(session)
            if folder_repo.get(folder_id) is None:
                return None
            return FolderContents(
                folders=folder_repo.children(folder_id),
                documents=DocumentRepository(session).list_by_folder(folder_id),
            )

    sets: FolderAccessSets = folder_access_sets(user_id)
    if folder_id not in sets.visible_folders:
        return None
    is_retrievable = folder_id in sets.retrievable_folders

    with session_scope() as session:
        folder_repo = FolderRepository(session)
        document_repo = DocumentRepository(session)
        subfolders = [f for f in folder_repo.children(folder_id) if f.id in sets.visible_folders]
        if is_retrievable:
            documents = document_repo.list_by_folder(folder_id)
        else:
            documents = [
                d for d in document_repo.list_by_folder(folder_id) if d.id in sets.granted_documents
            ]
        return FolderContents(folders=subfolders, documents=documents)


def _ancestor_path(folder_repo: FolderRepository, folder_id: UUID | None) -> str:
    """The real path from the root down to and including ``folder_id``, as
    plain text -- never a link, never a browsable id.

    Callers always pass the *containing* folder, one level up from whatever
    entity's own name is shown separately (a virtual root's own name) -- so
    ``folder_id`` itself belongs in the path, not just its ancestors.
    """
    if folder_id is None:
        return ""
    chain = folder_repo.ancestor_chain(folder_id)  # folder_id, then its ancestors, root last
    names = [folder.name for ancestor_id in chain if (folder := folder_repo.get(ancestor_id))]
    return " / ".join(reversed(names))
