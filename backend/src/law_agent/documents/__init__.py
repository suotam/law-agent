"""Documents: the domain layer above the blob store and the database.

Only the domain is re-exported here. ``ingest_document`` and its siblings live
in :mod:`law_agent.documents.service` and are imported from there, because the
repositories in ``law_agent.db`` import this package for its models -- pulling
the service in would close that loop.
"""

from law_agent.documents.models import (
    DEFAULT_SCOPE,
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
    ScopeSource,
)

__all__ = [
    "DEFAULT_SCOPE",
    "Document",
    "DocumentNotFoundError",
    "DocumentStatus",
    "DuplicateDocumentError",
    "DuplicateFolderError",
    "Folder",
    "FolderCycleError",
    "FolderNotEmptyError",
    "FolderNotFoundError",
    "Namespace",
    "ScopeSource",
]
