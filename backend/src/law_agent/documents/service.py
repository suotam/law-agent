"""Ingesting and deleting a document end to end.

The one place that composes the blob store, the database and the vector store.
The CLI calls it today and the web UI's upload will call the same function --
which is why it takes bytes and a filename, not a path.
"""

from __future__ import annotations

import mimetypes
from datetime import UTC, datetime, timedelta
from uuid import UUID

from docling_core.types.doc.document import DoclingDocument

from law_agent.config import settings
from law_agent.core.embeddings import get_embeddings
from law_agent.db import AclRepository, DocumentRepository, session_scope
from law_agent.documents.models import DocumentNotFoundError, Namespace
from law_agent.indexing import (
    ensure_collection,
    get_qdrant_client,
    get_sparse_embedder,
    index_chunks,
    prune_orphans,
)
from law_agent.ingestion.files import DoclingClient, FileChunker
from law_agent.ingestion.files.chunker import DEFAULT_MAX_TOKENS
from law_agent.storage import SweepStats, get_blob_store, sweep_blobs

_MIME_FALLBACK = "application/octet-stream"


def namespace_for(
    folder_id: UUID | None,
    message_id: UUID | None,  # noqa: ARG001 - part of the location tuple, not of the decision
    conversation_id: UUID | None = None,
) -> Namespace:
    """Where the document lives decides which corpus it is indexed into.

    An org file has a folder. An in-chat file has a conversation, and gains a
    message once one references it -- which is why ``message_id`` alone is not
    a location: an attachment exists before its message does. All three unset
    is a freestanding draft, uploaded before any conversation exists yet: it
    still indexes into ``USER_FILES``, just with no ``conversation_id`` in its
    payload, which is what keeps it out of every search until something claims
    it.
    """
    if folder_id is not None and conversation_id is not None:
        msg = "an org file cannot also belong to a conversation"
        raise ValueError(msg)
    return Namespace.ORG_FILES if folder_id is not None else Namespace.USER_FILES


def ingest_document(
    data: bytes,
    *,
    filename: str,
    folder_id: UUID | None = None,
    message_id: UUID | None = None,
    conversation_id: UUID | None = None,
    uploaded_by: str | None = None,
    parsed: DoclingDocument | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> UUID:
    """Store, parse, chunk and index one document.

    Args:
        data: The original file's bytes.
        filename: Name shown to the user and in citations.
        folder_id: Folder for an org file.
        message_id: Message for an in-chat file.
        conversation_id: Conversation an in-chat attachment belongs to; written
            into the chunk payload so retrieval can filter on it.
        uploaded_by: Who uploaded it; plain text until there is a users table.
        parsed: An already parsed document, which skips docling-serve. The CLI
            passes its parse cache in this way.
        max_tokens: Chunker budget.

    Returns:
        The document's id -- also its ``doc_id`` in the Qdrant payload.

    Raises:
        ValueError: no location, or both a folder and a conversation.
        DuplicateDocumentError: the same content is already in this folder.
    """
    namespace = namespace_for(folder_id, message_id, conversation_id)
    sha256 = get_blob_store().put(data)

    with session_scope() as session:
        document = DocumentRepository(session).create(
            namespace=namespace,
            filename=filename,
            mime=_mime_for(filename),
            byte_size=len(data),
            blob_sha256=sha256,
            folder_id=folder_id,
            message_id=message_id,
            conversation_id=conversation_id,
            uploaded_by=uploaded_by,
        )
        # Committed before the parse, which takes minutes: holding a transaction
        # across it would pin a connection, and the row is also what gives the
        # blob a reference before its GC grace period runs out.
        session.commit()

    try:
        chunk_count = _index(
            data,
            document_id=document.id,
            filename=filename,
            folder_id=folder_id,
            conversation_id=conversation_id,
            namespace=namespace,
            parsed=parsed,
            max_tokens=max_tokens,
        )
    except Exception as error:
        with session_scope() as session:
            DocumentRepository(session).mark_failed(
                document.id, error=f"{type(error).__name__}: {error}"
            )
            session.commit()
        raise

    with session_scope() as session:
        DocumentRepository(session).mark_indexed(document.id, chunk_count=chunk_count)
        session.commit()

    return document.id


def _index(
    data: bytes,
    *,
    document_id: UUID,
    filename: str,
    folder_id: UUID | None,
    conversation_id: UUID | None,
    namespace: Namespace,
    parsed: DoclingDocument | None,
    max_tokens: int,
) -> int:
    document = parsed or DoclingClient().parse_bytes(data, filename=filename)
    chunks = FileChunker(max_tokens=max_tokens).chunk(
        document,
        doc_id=str(document_id),
        filename=filename,
        folder_id=str(folder_id) if folder_id is not None else None,
        conversation_id=str(conversation_id) if conversation_id is not None else None,
    )

    client = get_qdrant_client()
    ensure_collection(client, settings.qdrant_collection)
    index_chunks(
        client,
        chunks,
        collection_name=settings.qdrant_collection,
        embeddings=get_embeddings(),
        sparse_embedder=get_sparse_embedder(),
        namespace=str(namespace),
    )
    # Re-indexing an edited document upserts in place, but a shorter version
    # produces fewer chunks; the leftovers would keep being retrieved.
    prune_orphans(
        client,
        settings.qdrant_collection,
        scope={"namespace": str(namespace), "doc_id": str(document_id)},
        keep=[chunk.point_id for chunk in chunks],
    )
    return len(chunks)


def delete_document(document_id: UUID) -> None:
    """Remove a document: its vectors first, then its row and ACL grants
    together, then its blob.

    The order matters. If the row went first, a process dying in between would
    leave points in Qdrant with no trace of them anywhere in the database. The
    row and its ACL rows are deleted in the same transaction -- there is no FK
    cascade on ``acl_entries.resource_id``, so a document row committed
    without its grants would leave them orphaned.

    Raises:
        DocumentNotFoundError: no document with this id.
    """
    with session_scope() as session:
        document = DocumentRepository(session).get(document_id)
    if document is None:
        msg = f"no document {document_id}"
        raise DocumentNotFoundError(msg)

    prune_orphans(
        get_qdrant_client(),
        settings.qdrant_collection,
        scope={"namespace": document.namespace, "doc_id": str(document_id)},
        keep=[],
    )

    with session_scope() as session:
        repository = DocumentRepository(session)
        repository.delete(document_id)
        AclRepository(session).delete_for_resources(folder_ids=set(), document_ids={document_id})
        session.commit()
        remaining = repository.count_by_blob(document.blob_sha256)

    # Kept when another row still points at it: the same contract may sit in
    # "Vzory" and in a client folder, sharing one blob.
    if remaining == 0:
        get_blob_store().delete(document.blob_sha256)


def sweep_unreferenced_blobs() -> SweepStats:
    """Delete blobs no document references -- the safety net, not the main path.

    Covers a process that died between ``BlobStore.put`` and the ``INSERT``.
    """
    with session_scope() as session:
        repository = DocumentRepository(session)
        return sweep_blobs(
            get_blob_store(),
            is_referenced=lambda sha: repository.count_by_blob(sha) > 0,
        )


def sweep_unbound_attachments(
    grace: timedelta = timedelta(hours=24), now: datetime | None = None
) -> SweepStats:
    """Delete drafts nobody ever claimed.

    A user who closes the tab before sending anything leaves a document row
    with no folder and no conversation; ``delete_document`` already removes
    its Qdrant points, its row and -- if unreferenced -- its blob.
    """
    cutoff = (now or datetime.now(UTC)) - grace
    with session_scope() as session:
        stale = DocumentRepository(session).list_unbound(older_than=cutoff)
    for document in stale:
        delete_document(document.id)
    return SweepStats(scanned=len(stale), deleted=len(stale), kept_referenced=0, kept_young=0)


def _mime_for(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or _MIME_FALLBACK
