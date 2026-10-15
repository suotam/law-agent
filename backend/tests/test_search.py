"""Tests for the tool-shaped search over several namespaces at once."""

from __future__ import annotations

import importlib
from uuid import UUID, uuid4

import pytest
from qdrant_client import QdrantClient
from tests.factories import make_chunk, make_file_like_chunk
from tests.test_retriever import KeywordFakeEmbeddings

from law_agent.config import settings
from law_agent.indexing import Bm25SparseEmbedder, ensure_collection, index_chunks
from law_agent.retrieval import ScopeSource, search

search_module = importlib.import_module("law_agent.retrieval.search")

COLLECTION = settings.qdrant_collection

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")


class _CountingClient:
    """Wraps a real client to count ``query_points`` calls without changing
    its behaviour -- the spy the one-Qdrant-call test needs."""

    def __init__(self, inner: QdrantClient) -> None:
        self._inner = inner
        self.calls = 0

    def query_points(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        return self._inner.query_points(*args, **kwargs)


@pytest.fixture
def indexed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire an in-memory Qdrant with one law chunk and one file chunk into
    ``search``, in place of the real client, embedder, sparse embedder and
    role/ACL resolvers. Defaults the caller to a superuser: the three
    pre-existing tests using this fixture predate access filtering and are
    not about it -- they only need `search` to behave as before.
    """
    client = QdrantClient(":memory:")
    ensure_collection(client, COLLECTION, dense_size=4)
    embeddings = KeywordFakeEmbeddings()
    sparse = Bm25SparseEmbedder()

    index_chunks(
        client,
        [make_chunk("c1", "§ 41 převedení na jinou práci", citation="§ 41")],
        collection_name=COLLECTION,
        embeddings=embeddings,
        sparse_embedder=sparse,
        namespace="laws",
    )
    index_chunks(
        client,
        [make_file_like_chunk("f1", "směrnice o převedení na jinou práci")],
        collection_name=COLLECTION,
        embeddings=embeddings,
        sparse_embedder=sparse,
        namespace="org_files",
    )

    monkeypatch.setattr(search_module, "_client", lambda: client)
    monkeypatch.setattr(search_module, "_embeddings", lambda: embeddings)
    monkeypatch.setattr(search_module, "_sparse_embedder", lambda: sparse)
    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: True)


@pytest.mark.usefixtures("indexed")
def test_default_scope_returns_both_namespaces_in_one_ranking() -> None:
    results = search("převedení na jinou práci", user_id=uuid4())

    assert {result.chunk_id for result in results} == {"c1", "f1"}
    assert [result.score for result in results] == sorted(
        (result.score for result in results), reverse=True
    )


@pytest.mark.usefixtures("indexed")
def test_narrowed_scope_returns_only_that_namespace() -> None:
    results = search("převedení na jinou práci", scope=["laws"], user_id=uuid4())

    assert {result.chunk_id for result in results} == {"c1"}


@pytest.mark.usefixtures("indexed")
def test_limit_caps_the_number_of_results() -> None:
    results = search("převedení na jinou práci", limit=1, user_id=uuid4())

    assert len(results) == 1


@pytest.fixture
def indexed_with_folders(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str, UUID]:
    """One law chunk plus three org_files chunks: one in an allowed folder,
    one in another folder with no grant, and one (in that same ungranted
    folder) with a direct document grant -- everything the permission tests
    below need to tell "in scope" apart from "out of scope"."""
    client = QdrantClient(":memory:")
    ensure_collection(client, COLLECTION, dense_size=4)
    embeddings = KeywordFakeEmbeddings()
    sparse = Bm25SparseEmbedder()
    allowed_folder = str(uuid4())
    other_folder = str(uuid4())
    direct_doc_id = uuid4()

    index_chunks(
        client,
        [make_chunk("c1", "§ 41 převedení na jinou práci", citation="§ 41")],
        collection_name=COLLECTION,
        embeddings=embeddings,
        sparse_embedder=sparse,
        namespace="laws",
    )
    index_chunks(
        client,
        [make_file_like_chunk("f1", "převedení na jinou práci", folder_id=allowed_folder)],
        collection_name=COLLECTION,
        embeddings=embeddings,
        sparse_embedder=sparse,
        namespace="org_files",
    )
    index_chunks(
        client,
        [make_file_like_chunk("f2", "převedení na jinou práci", folder_id=other_folder)],
        collection_name=COLLECTION,
        embeddings=embeddings,
        sparse_embedder=sparse,
        namespace="org_files",
    )
    index_chunks(
        client,
        [
            make_file_like_chunk(
                "f3",
                "převedení na jinou práci",
                doc_id=str(direct_doc_id),
                folder_id=other_folder,
            )
        ],
        collection_name=COLLECTION,
        embeddings=embeddings,
        sparse_embedder=sparse,
        namespace="org_files",
    )

    monkeypatch.setattr(search_module, "_client", lambda: client)
    monkeypatch.setattr(search_module, "_embeddings", lambda: embeddings)
    monkeypatch.setattr(search_module, "_sparse_embedder", lambda: sparse)
    # Identity default: no real folder tree backs these synthetic ids, so
    # subtree expansion is a no-op unless a test overrides it to exercise
    # that behaviour specifically.
    monkeypatch.setattr(search_module, "_subtree_ids", lambda folder_ids: set(folder_ids))
    return allowed_folder, other_folder, direct_doc_id


@pytest.mark.usefixtures("indexed_with_folders")
def test_member_with_no_grants_gets_no_org_files_chunks_but_laws_still_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: False)
    monkeypatch.setattr(search_module, "_accessible_org_folder_ids", lambda _user_id: set())
    monkeypatch.setattr(search_module, "_directly_granted_document_ids", lambda _user_id: set())

    results = search("převedení na jinou práci", user_id=uuid4())

    assert {result.chunk_id for result in results} == {"c1"}


def test_member_with_a_folder_grant_gets_that_folder_not_a_sibling(
    indexed_with_folders: tuple[str, str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed_folder, _other_folder, _direct_doc_id = indexed_with_folders
    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: False)
    monkeypatch.setattr(
        search_module, "_accessible_org_folder_ids", lambda _user_id: {UUID(allowed_folder)}
    )
    monkeypatch.setattr(search_module, "_directly_granted_document_ids", lambda _user_id: set())

    results = search("převedení na jinou práci", user_id=uuid4())

    assert {result.chunk_id for result in results} == {"c1", "f1"}


def test_member_with_only_a_direct_document_grant_gets_that_documents_chunks(
    indexed_with_folders: tuple[str, str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    _allowed_folder, _other_folder, direct_doc_id = indexed_with_folders
    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: False)
    monkeypatch.setattr(search_module, "_accessible_org_folder_ids", lambda _user_id: set())
    monkeypatch.setattr(
        search_module, "_directly_granted_document_ids", lambda _user_id: {direct_doc_id}
    )

    results = search("převedení na jinou práci", user_id=uuid4())

    assert {result.chunk_id for result in results} == {"c1", "f3"}


@pytest.mark.usefixtures("indexed_with_folders")
def test_superuser_gets_every_org_files_chunk_without_calling_the_resolvers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_user_id: UUID) -> set[UUID]:
        raise AssertionError("the resolvers must not run for a superuser")

    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: True)
    monkeypatch.setattr(search_module, "_accessible_org_folder_ids", _boom)
    monkeypatch.setattr(search_module, "_directly_granted_document_ids", _boom)

    results = search("převedení na jinou práci", user_id=uuid4())

    assert {result.chunk_id for result in results} == {"c1", "f1", "f2", "f3"}


@pytest.mark.usefixtures("indexed_with_folders")
def test_a_capability_holder_gets_every_org_files_chunk_without_calling_the_resolvers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-superuser role holding MANAGE_ORG_FILES_STRUCTURE gets the same
    full-access treatment as a superuser: `_corpus_hits` only consumes the
    already-resolved `_has_full_org_files_access` boolean, so it cannot tell
    the two cases apart -- that distinction is `has_full_org_files_access`'s
    own job, covered separately in `test_access_service.py`."""

    def _boom(_user_id: UUID) -> set[UUID]:
        raise AssertionError("the resolvers must not run for a capability holder")

    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: True)
    monkeypatch.setattr(search_module, "_accessible_org_folder_ids", _boom)
    monkeypatch.setattr(search_module, "_directly_granted_document_ids", _boom)

    results = search("převedení na jinou práci", user_id=uuid4())

    assert {result.chunk_id for result in results} == {"c1", "f1", "f2", "f3"}


def test_a_superusers_narrowed_conversation_is_respected_not_searched_unfiltered(
    indexed_with_folders: tuple[str, str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A superuser conversation frozen with an explicit selection (chat org
    files scope picker) must still narrow the search -- only the *unnarrowed*
    case is meant to skip straight to an unfiltered query."""
    allowed_folder, _other_folder, _direct_doc_id = indexed_with_folders

    def _boom(_user_id: UUID) -> set[UUID]:
        raise AssertionError("the ACL resolvers must not run for a superuser")

    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: True)
    monkeypatch.setattr(search_module, "_accessible_org_folder_ids", _boom)
    monkeypatch.setattr(search_module, "_directly_granted_document_ids", _boom)

    results = search(
        "převedení na jinou práci",
        user_id=uuid4(),
        org_files_folder_ids=[UUID(allowed_folder)],
    )

    assert {result.chunk_id for result in results} == {"c1", "f1"}


def test_a_narrower_conversation_selection_returns_only_that_subset(
    indexed_with_folders: tuple[str, str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed_folder, other_folder, _direct_doc_id = indexed_with_folders
    # The user's full ceiling covers both folders...
    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: False)
    monkeypatch.setattr(
        search_module,
        "_accessible_org_folder_ids",
        lambda _user_id: {UUID(allowed_folder), UUID(other_folder)},
    )
    monkeypatch.setattr(search_module, "_directly_granted_document_ids", lambda _user_id: set())

    # ...but this conversation was frozen with only one of them.
    results = search(
        "převedení na jinou práci",
        user_id=uuid4(),
        org_files_folder_ids=[UUID(allowed_folder)],
    )

    assert {result.chunk_id for result in results} == {"c1", "f1"}


def test_folder_narrowing_excludes_direct_document_grants_outside_it(
    indexed_with_folders: tuple[str, str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Narrowing is one decision about the whole selection: once the user
    checked a folder, the untouched document side contributes nothing --
    leaving it as "no narrowing" would keep the user's unrelated direct
    document grants (``f3`` here) searchable inside this conversation."""
    allowed_folder, _other_folder, direct_doc_id = indexed_with_folders
    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: False)
    monkeypatch.setattr(
        search_module, "_accessible_org_folder_ids", lambda _user_id: {UUID(allowed_folder)}
    )
    monkeypatch.setattr(
        search_module, "_directly_granted_document_ids", lambda _user_id: {direct_doc_id}
    )

    results = search(
        "převedení na jinou práci",
        user_id=uuid4(),
        org_files_folder_ids=[UUID(allowed_folder)],
    )

    assert {result.chunk_id for result in results} == {"c1", "f1"}


def test_document_narrowing_excludes_folder_ceiling_outside_it(
    indexed_with_folders: tuple[str, str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mirror image: narrowing by document only must not leave every
    ceiling-accessible folder searchable next to the selected documents."""
    _allowed_folder, _other_folder, direct_doc_id = indexed_with_folders
    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: False)
    monkeypatch.setattr(
        search_module, "_accessible_org_folder_ids", lambda _user_id: {UUID(_allowed_folder)}
    )
    monkeypatch.setattr(
        search_module, "_directly_granted_document_ids", lambda _user_id: {direct_doc_id}
    )

    results = search(
        "převedení na jinou práci",
        user_id=uuid4(),
        org_files_document_ids=[direct_doc_id],
    )

    assert {result.chunk_id for result in results} == {"c1", "f3"}


def test_search_org_files_narrowing_expands_unopened_subfolders(
    indexed_with_folders: tuple[str, str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chat scope picker sends only the id of a checked-but-unopened
    folder, not its unopened subfolders. ``_corpus_hits`` must expand that
    id to its whole subtree before intersecting with the ceiling, or a
    document sitting in an unopened subfolder silently drops out of scope
    even though the ceiling already grants it.

    ``other_folder`` stands in for that unopened child here: the ceiling
    (``_accessible_org_folder_ids``) already covers it -- exactly as the real
    resolver would, since a folder grant's ceiling always includes its whole
    subtree -- but the client's narrowing names only the checked parent.
    """
    allowed_folder, other_folder, _direct_doc_id = indexed_with_folders
    parent_id = UUID(allowed_folder)
    child_id = UUID(other_folder)
    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: False)
    monkeypatch.setattr(
        search_module, "_accessible_org_folder_ids", lambda _user_id: {parent_id, child_id}
    )
    monkeypatch.setattr(search_module, "_directly_granted_document_ids", lambda _user_id: set())
    monkeypatch.setattr(search_module, "_subtree_ids", lambda _folder_ids: {parent_id, child_id})

    results = search(
        "převedení na jinou práci",
        user_id=uuid4(),
        org_files_folder_ids=[parent_id],
    )

    # f2 and f3 both live under `other_folder` (child_id); once the subtree
    # expansion pulls child_id into the intersected folder_ids, both match
    # via the folder_id condition regardless of f3's separate direct grant.
    assert {result.chunk_id for result in results} == {"c1", "f1", "f2", "f3"}


def test_combined_scope_with_a_permission_filter_still_issues_one_qdrant_call(
    indexed_with_folders: tuple[str, str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed_folder, _other_folder, _direct_doc_id = indexed_with_folders
    monkeypatch.setattr(search_module, "_has_full_org_files_access", lambda _user_id: False)
    monkeypatch.setattr(
        search_module, "_accessible_org_folder_ids", lambda _user_id: {UUID(allowed_folder)}
    )
    monkeypatch.setattr(search_module, "_directly_granted_document_ids", lambda _user_id: set())
    spy = _CountingClient(search_module._client())
    monkeypatch.setattr(search_module, "_client", lambda: spy)

    search(
        "převedení na jinou práci",
        scope=[ScopeSource.LAWS, ScopeSource.ORG_FILES],
        user_id=uuid4(),
    )

    assert spy.calls == 1
