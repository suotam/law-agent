"""Search over several namespaces in one retrieval call.

Written tool-shaped on purpose: flat, serializable arguments and a docstring
that will become the model-facing tool description once the chain grows into
an agent. Clients are module-level singletons rather than parameters for the
same reason -- a tool signature has no room for a Qdrant handle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from qdrant_client import QdrantClient, models

from law_agent.access.service import (
    accessible_org_folder_ids,
    directly_granted_document_ids,
    has_full_org_files_access,
)
from law_agent.config import settings
from law_agent.core.embeddings import OpenRouterEmbeddings, get_embeddings
from law_agent.db import FolderRepository, session_scope
from law_agent.documents.models import DEFAULT_SCOPE, Namespace, ScopeSource
from law_agent.indexing import Bm25SparseEmbedder, get_qdrant_client, get_sparse_embedder
from law_agent.retrieval.retriever import RetrievedChunk, query_chunks


def search(
    query: str,
    *,
    scope: Sequence[ScopeSource] = DEFAULT_SCOPE,
    limit: int = 10,
    conversation_id: UUID | None = None,
    user_id: UUID,
    org_files_folder_ids: Sequence[UUID] | None = None,
    org_files_document_ids: Sequence[UUID] | None = None,
) -> list[RetrievedChunk]:
    """Search the indexed sources and return the best matching chunks.

    Args:
        query: What to look for, in natural language or as a literal citation.
        scope: Namespaces to search: ``laws`` for Czech legislation,
            ``org_files`` for the organisation's own documents.
        limit: Maximum number of chunks to return per source.
        conversation_id: When given, the files attached to that conversation are
            searched as well.
        user_id: Whose access ceiling gates ``org_files`` results. Required,
            no default -- this is a security boundary, not a convenience
            parameter, and a call site that forgets it must fail loudly rather
            than search unfiltered.
        org_files_folder_ids: When given, further narrows the caller's
            ``org_files`` ceiling to this subset -- a conversation's frozen
            selection (``ConversationMeta``), never trusted wider than what
            the ceiling itself allows.
        org_files_document_ids: The same narrowing for direct document grants.

        Narrowing is one decision about the whole org-files selection, not
        one per field: if *either* argument is given the conversation is
        narrowed, and the other argument then means "narrowed to nothing on
        that side" -- ``None`` only means "no narrowing at all" when both
        are absent. A caller passing just the folder ids must not leave its
        unrelated direct document grants searchable.

    Returns:
        Chunks ordered best first. Attachments come first as a separate block:
        their hits are ranked in their own call and the two RRF scores are not
        comparable, and a file the user just attached is what the question is
        usually about.
    """
    attachments = _attachment_hits(query, conversation_id, limit) if conversation_id else []
    corpus = (
        _corpus_hits(
            query,
            scope=scope,
            limit=limit,
            user_id=user_id,
            org_files_folder_ids=org_files_folder_ids,
            org_files_document_ids=org_files_document_ids,
        )
        if scope
        else []
    )
    return [*attachments, *corpus]


def _attachment_hits(query: str, conversation_id: UUID, limit: int) -> list[RetrievedChunk]:
    """A separate call, because the conversation filter is conjunctive.

    Folded into the main query it would apply to every namespace at once and
    silently drop every statute and org file.
    """
    return _query(
        query,
        namespace=str(Namespace.USER_FILES),
        limit=limit,
        extra_filter={"conversation_id": str(conversation_id)},
    )


def _corpus_hits(
    query: str,
    *,
    scope: Sequence[ScopeSource],
    limit: int,
    user_id: UUID,
    org_files_folder_ids: Sequence[UUID] | None = None,
    org_files_document_ids: Sequence[UUID] | None = None,
) -> list[RetrievedChunk]:
    scope_list = list(scope)
    if ScopeSource.ORG_FILES not in scope_list:
        return _query(query, namespace=scope_list, limit=limit)

    has_full_access = _has_full_org_files_access(user_id)
    # One decision for the whole selection: either field present means the
    # conversation narrowed, and the absent side then contributes nothing --
    # treating it per-field as "no narrowing" would keep unrelated direct
    # grants searchable next to a checked folder (or vice versa).
    narrowed = org_files_folder_ids is not None or org_files_document_ids is not None

    if has_full_access and not narrowed:
        # The common full-access case (superuser, or a role holding
        # MANAGE_ORG_FILES_STRUCTURE): no narrowing at all, so there is
        # nothing to filter by and the resolvers below are skipped entirely
        # -- an admin's query cost stays what it is today.
        return _query(query, namespace=scope_list, limit=limit)

    if has_full_access:
        # Full access means no "ceiling" to intersect the narrowing against
        # -- the caller's own conversation's explicit selection (chat org
        # files scope picker) is trusted as-is, without calling the ACL
        # resolvers (which would only return their *personal* grants,
        # typically none, and would otherwise wipe the selection out instead
        # of honouring it).
        folder_ids = set(org_files_folder_ids or ())
        document_ids = set(org_files_document_ids or ())
    else:
        folder_ids = _accessible_org_folder_ids(user_id)
        document_ids = _directly_granted_document_ids(user_id)
        # A conversation frozen with a narrower selection than the full
        # ceiling (chat org files scope picker design doc) intersects here.
        # The narrowing ids are expanded to their whole subtree first: a
        # folder checked without being expanded in the picker still carries
        # its unopened subfolders' documents, and intersecting the bare id
        # against the ceiling would otherwise drop them even though the
        # ceiling itself grants them.
        if org_files_folder_ids is not None:
            folder_ids &= _subtree_ids(org_files_folder_ids)
        elif narrowed:
            folder_ids = set()
        if org_files_document_ids is not None:
            document_ids &= set(org_files_document_ids)
        elif narrowed:
            document_ids = set()

    if not folder_ids and not document_ids:
        # Not "skip the filter" (that would mean unfiltered) and not an empty
        # `should` sent to Qdrant (whose "nothing satisfies this" semantics
        # should not be relied on) -- the org_files branch is left out of the
        # query entirely, the same way `_attachment_hits` is skipped when
        # there is no `conversation_id`.
        remaining = [value for value in scope_list if value != ScopeSource.ORG_FILES]
        return _query(query, namespace=remaining, limit=limit) if remaining else []

    condition = _org_files_condition(folder_ids, document_ids)
    return _query(
        query,
        namespace=scope_list,
        limit=limit,
        scoped_filter=(str(ScopeSource.ORG_FILES), condition),
    )


def _org_files_condition(folder_ids: set[UUID], document_ids: set[UUID]) -> models.Condition:
    should: list[models.Condition] = []
    if folder_ids:
        should.append(
            models.FieldCondition(
                key="folder_id",
                match=models.MatchAny(any=[str(folder_id) for folder_id in folder_ids]),
            )
        )
    if document_ids:
        should.append(
            models.FieldCondition(
                key="doc_id",
                match=models.MatchAny(any=[str(document_id) for document_id in document_ids]),
            )
        )
    return models.Filter(should=should)


def _query(
    query: str,
    *,
    namespace: str | Sequence[str],
    limit: int,
    extra_filter: Mapping[str, str] | None = None,
    scoped_filter: tuple[str, models.Condition] | None = None,
) -> list[RetrievedChunk]:
    return query_chunks(
        _client(),
        query,
        collection_name=settings.qdrant_collection,
        embeddings=_embeddings(),
        sparse_embedder=_sparse_embedder(),
        namespace=namespace,
        limit=limit,
        extra_filter=extra_filter,
        scoped_filter=scoped_filter,
    )


# Thin names over the shared cached accessors, kept as module attributes so
# tests can swap them out for fakes without touching the shared caches.
def _client() -> QdrantClient:
    return get_qdrant_client()


def _embeddings() -> OpenRouterEmbeddings:
    return get_embeddings()


def _sparse_embedder() -> Bm25SparseEmbedder:
    return get_sparse_embedder()


def _has_full_org_files_access(user_id: UUID) -> bool:
    return has_full_org_files_access(user_id)


def _accessible_org_folder_ids(user_id: UUID) -> set[UUID]:
    return accessible_org_folder_ids(user_id)


def _directly_granted_document_ids(user_id: UUID) -> set[UUID]:
    return directly_granted_document_ids(user_id)


def _subtree_ids(folder_ids: Sequence[UUID]) -> set[UUID]:
    with session_scope() as session:
        return FolderRepository(session).subtree_ids(list(folder_ids))
