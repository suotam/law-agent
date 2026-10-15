"""Tests for the document and folder schema, repositories and ingest service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qdrant_client import QdrantClient
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

from law_agent.conversations.blocks import text_block
from law_agent.conversations.models import ConversationMeta, Role
from law_agent.db import models as orm
from law_agent.db.repositories import (
    ConversationRepository,
    DocumentRepository,
    FolderRepository,
    MessageRepository,
)
from law_agent.documents import (
    Document,
    DocumentNotFoundError,
    DocumentStatus,
    DuplicateDocumentError,
    DuplicateFolderError,
    FolderCycleError,
    FolderNotEmptyError,
    FolderNotFoundError,
    Namespace,
)
from law_agent.documents.service import (
    delete_document,
    ingest_document,
    namespace_for,
    sweep_unbound_attachments,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
PDF = b"%PDF-1.7 fake"


def _create(
    repo: DocumentRepository,
    *,
    folder_id: UUID,
    sha: str = SHA_A,
    name: str = "smlouva.pdf",
) -> Document:
    return repo.create(
        namespace=Namespace.ORG_FILES,
        filename=name,
        mime="application/pdf",
        byte_size=1024,
        blob_sha256=sha,
        folder_id=folder_id,
    )


def test_schema_upgrades_on_a_clean_database(db_engine: Engine) -> None:
    """The fixture itself runs ``alembic upgrade head``; this asserts the result."""
    inspector = inspect(db_engine)

    assert set(inspector.get_table_names()) >= {"folders", "documents", "alembic_version"}
    assert {index["name"] for index in inspector.get_indexes("folders")} >= {
        "ux_folders_sibling_name",
        "ux_folders_root_name",
    }
    assert {index["name"] for index in inspector.get_indexes("documents")} >= {
        "ux_documents_folder_blob",
        "ix_documents_blob_sha256",
    }


def test_two_root_folders_cannot_share_a_name(session: Session) -> None:
    """NULL != NULL in Postgres, which is why the partial index exists."""
    folders = FolderRepository(session)
    folders.create("Vzory")

    with pytest.raises(DuplicateFolderError):
        folders.create("Vzory")


def test_same_name_under_different_parents_is_allowed(session: Session) -> None:
    folders = FolderRepository(session)
    vzory = folders.create("Vzory")
    klienti = folders.create("Klienti")

    first = folders.create("Smlouvy", parent_id=vzory.id)
    second = folders.create("Smlouvy", parent_id=klienti.id)

    assert first.id != second.id


def test_a_folder_is_renamed(session: Session) -> None:
    folders = FolderRepository(session)
    folder = folders.create("Vzory")

    renamed = folders.update(folder.id, name="Šablony")

    assert renamed.name == "Šablony"
    reloaded = folders.get(folder.id)
    assert reloaded is not None
    assert reloaded.name == "Šablony"


def test_renaming_to_a_taken_sibling_name_is_rejected(session: Session) -> None:
    folders = FolderRepository(session)
    folders.create("Vzory")
    other = folders.create("Klienti")

    with pytest.raises(DuplicateFolderError):
        folders.update(other.id, name="Vzory")


def test_a_folder_is_moved_under_a_new_parent(session: Session) -> None:
    folders = FolderRepository(session)
    vzory = folders.create("Vzory")
    klienti = folders.create("Klienti")
    smlouvy = folders.create("Smlouvy", parent_id=vzory.id)

    moved = folders.update(smlouvy.id, parent_id=klienti.id)

    assert moved.parent_id == klienti.id


def test_a_folder_is_moved_back_to_the_root(session: Session) -> None:
    folders = FolderRepository(session)
    vzory = folders.create("Vzory")
    smlouvy = folders.create("Smlouvy", parent_id=vzory.id)

    moved = folders.update(smlouvy.id, parent_id=None)

    assert moved.parent_id is None


def test_an_omitted_parent_leaves_the_folder_where_it_is(session: Session) -> None:
    folders = FolderRepository(session)
    vzory = folders.create("Vzory")
    smlouvy = folders.create("Smlouvy", parent_id=vzory.id)

    renamed = folders.update(smlouvy.id, name="Dohody")

    assert renamed.parent_id == vzory.id


def test_a_folder_cannot_move_into_its_own_descendant(session: Session) -> None:
    folders = FolderRepository(session)
    vzory = folders.create("Vzory")
    smlouvy = folders.create("Smlouvy", parent_id=vzory.id)

    with pytest.raises(FolderCycleError):
        folders.update(vzory.id, parent_id=smlouvy.id)


def test_a_folder_cannot_move_into_itself(session: Session) -> None:
    folders = FolderRepository(session)
    vzory = folders.create("Vzory")

    with pytest.raises(FolderCycleError):
        folders.update(vzory.id, parent_id=vzory.id)


def test_updating_an_unknown_folder_raises(session: Session) -> None:
    with pytest.raises(FolderNotFoundError):
        FolderRepository(session).update(uuid4(), name="x")


def test_an_empty_folder_is_deleted(session: Session) -> None:
    folders = FolderRepository(session)
    folder = folders.create("Vzory")

    folders.delete(folder.id)

    assert folders.get(folder.id) is None


def test_a_folder_with_children_cannot_be_deleted(session: Session) -> None:
    folders = FolderRepository(session)
    parent = folders.create("Vzory")
    folders.create("Smlouvy", parent_id=parent.id)

    with pytest.raises(FolderNotEmptyError):
        folders.delete(parent.id)


def test_a_folder_with_documents_cannot_be_deleted(session: Session) -> None:
    folders = FolderRepository(session)
    folder = folders.create("Vzory")
    _create(DocumentRepository(session), folder_id=folder.id)

    with pytest.raises(FolderNotEmptyError):
        folders.delete(folder.id)


def test_deleting_an_unknown_folder_raises(session: Session) -> None:
    with pytest.raises(FolderNotFoundError):
        FolderRepository(session).delete(uuid4())


def test_ensure_path_creates_missing_folders_and_reuses_existing(session: Session) -> None:
    folders = FolderRepository(session)

    created = folders.ensure_path(["Vzory", "Smlouvy"])
    again = folders.ensure_path(["Vzory", "Smlouvy"])

    assert created.id == again.id
    assert created.name == "Smlouvy"
    parent = folders.get(created.parent_id)
    assert parent is not None
    assert parent.name == "Vzory"


def test_the_same_file_twice_in_one_folder_is_rejected(session: Session) -> None:
    folder = FolderRepository(session).create("Vzory")
    documents = DocumentRepository(session)
    _create(documents, folder_id=folder.id)

    with pytest.raises(DuplicateDocumentError):
        _create(documents, folder_id=folder.id)


def test_the_session_survives_a_rejected_duplicate(session: Session) -> None:
    """CLI keeps going after a skipped file, so the savepoint has to hold."""
    folder = FolderRepository(session).create("Vzory")
    documents = DocumentRepository(session)
    _create(documents, folder_id=folder.id)

    with pytest.raises(DuplicateDocumentError):
        _create(documents, folder_id=folder.id)

    other = _create(documents, folder_id=folder.id, sha=SHA_B, name="dodatek.pdf")
    assert other.blob_sha256 == SHA_B


def test_the_same_file_in_another_folder_is_allowed(session: Session) -> None:
    """Deliberate: the folder is part of an org file's meaning and its citation."""
    folders = FolderRepository(session)
    documents = DocumentRepository(session)
    vzory = folders.create("Vzory")
    klienti = folders.create("Klienti")

    first = _create(documents, folder_id=vzory.id)
    second = _create(documents, folder_id=klienti.id)

    assert first.id != second.id
    assert first.blob_sha256 == second.blob_sha256


def test_a_new_document_starts_pending(session: Session) -> None:
    folder = FolderRepository(session).create("Vzory")

    document = _create(DocumentRepository(session), folder_id=folder.id)

    assert document.status is DocumentStatus.PENDING
    assert document.chunk_count is None


def test_mark_indexed_and_mark_failed(session: Session) -> None:
    folder = FolderRepository(session).create("Vzory")
    documents = DocumentRepository(session)
    document = _create(documents, folder_id=folder.id)

    documents.mark_indexed(document.id, chunk_count=7)
    indexed = documents.get(document.id)
    assert indexed is not None
    assert (indexed.status, indexed.chunk_count) == (DocumentStatus.INDEXED, 7)
    assert indexed.indexed_at is not None

    documents.mark_failed(document.id, error="docling-serve timed out")
    failed = documents.get(document.id)
    assert failed is not None
    assert failed.status is DocumentStatus.FAILED
    assert failed.error == "docling-serve timed out"


def test_count_by_blob_and_delete(session: Session) -> None:
    folders = FolderRepository(session)
    documents = DocumentRepository(session)
    first = _create(documents, folder_id=folders.create("Vzory").id)
    _create(documents, folder_id=folders.create("Klienti").id)

    assert documents.count_by_blob(SHA_A) == 2

    documents.delete(first.id)

    assert documents.count_by_blob(SHA_A) == 1
    assert documents.get(first.id) is None


def test_ingest_rejects_both_locations() -> None:
    with pytest.raises(ValueError, match="cannot also belong"):
        ingest_document(PDF, filename="smlouva.pdf", folder_id=uuid4(), conversation_id=uuid4())


def test_namespace_follows_the_location() -> None:
    assert namespace_for(uuid4(), None) is Namespace.ORG_FILES


def test_delete_of_an_unknown_document_raises() -> None:
    with pytest.raises(DocumentNotFoundError):
        delete_document(uuid4())


def test_delete_document_removes_its_acl_rows_in_the_same_transaction(
    db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no FK cascade on ``acl_entries.resource_id``, so
    ``delete_document`` must delete a document's ACL rows itself -- and in the
    same transaction as the row, so a process dying between the two commits
    can never leave an orphaned grant behind.

    Uses a real, committed ``Session(bind=db_engine)`` rather than the
    ``session`` fixture's rolled-back savepoint, same reasoning as
    ``test_sweep_unbound_attachments_removes_only_old_drafts`` below:
    ``delete_document`` opens its own ``session_scope()``, a fresh connection
    from the global sessionmaker that cannot see uncommitted data.
    """
    from sqlalchemy.orm import sessionmaker

    from law_agent.access.models import Permission, PrincipalType, ResourceType
    from law_agent.access.service import upsert_acl_entry
    from law_agent.db import AclRepository, session_scope

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    monkeypatch.setattr(
        "law_agent.documents.service.get_qdrant_client", lambda: QdrantClient(":memory:")
    )
    with session_scope() as session:
        folder = FolderRepository(session).create(f"Vzory-{uuid4().hex[:8]}")
        document = _create(DocumentRepository(session), folder_id=folder.id)
        session.commit()

    entry = upsert_acl_entry(
        resource_type=ResourceType.DOCUMENT,
        resource_id=document.id,
        principal_type=PrincipalType.USER,
        principal_id=uuid4(),
        permission=Permission.READ,
    )

    delete_document(document.id)

    with session_scope() as session:
        assert DocumentRepository(session).get(document.id) is None
        assert AclRepository(session).get(entry.id) is None


def test_blob_is_kept_while_another_document_references_it(session: Session) -> None:
    """Two folders may hold the same file; deleting one must not touch the blob."""
    folders = FolderRepository(session)
    documents = DocumentRepository(session)
    first = _create(documents, folder_id=folders.create("Vzory").id)
    _create(documents, folder_id=folders.create("Klienti").id)

    documents.delete(first.id)

    assert documents.count_by_blob(SHA_A) == 1


def test_an_attachment_may_belong_to_a_conversation_before_any_message(session: Session) -> None:
    """The API indexes an upload before the message that references it exists,
    so a document must be locatable by conversation alone."""
    conversation = ConversationRepository(session).create(
        "admin", title="T", meta=ConversationMeta()
    )

    document = DocumentRepository(session).create(
        namespace=Namespace.USER_FILES,
        filename="smlouva.pdf",
        mime="application/pdf",
        byte_size=10,
        blob_sha256="a" * 64,
        conversation_id=conversation.id,
    )

    assert document.conversation_id == conversation.id
    assert document.message_id is None
    listed = DocumentRepository(session).list_by_conversation(conversation.id)
    assert [item.id for item in listed] == [document.id]


def test_an_attachment_is_claimed_by_the_message_that_uses_it(session: Session) -> None:
    conversation = ConversationRepository(session).create(
        "admin", title="T", meta=ConversationMeta()
    )
    message = MessageRepository(session).append(
        conversation.id, role=Role.USER, blocks=[text_block("otázka")]
    )
    repository = DocumentRepository(session)
    document = repository.create(
        namespace=Namespace.USER_FILES,
        filename="smlouva.pdf",
        mime="application/pdf",
        byte_size=10,
        blob_sha256="b" * 64,
        conversation_id=conversation.id,
    )

    repository.attach_to_message([document.id], message_id=message.id)

    claimed = repository.get(document.id)
    assert claimed is not None
    assert claimed.message_id == message.id


def test_a_conversation_location_indexes_into_user_files() -> None:
    assert namespace_for(None, None, uuid4()) is Namespace.USER_FILES


def test_a_document_with_no_location_at_all_is_a_draft() -> None:
    assert namespace_for(None, None, None) is Namespace.USER_FILES


def test_an_org_file_cannot_also_sit_in_a_conversation() -> None:
    with pytest.raises(ValueError, match="cannot also belong"):
        namespace_for(uuid4(), None, uuid4())


def test_claim_binds_a_document_to_a_conversation(session: Session) -> None:
    conversation = ConversationRepository(session).create(
        "admin", title="T", meta=ConversationMeta()
    )
    documents = DocumentRepository(session)
    draft = documents.create(
        namespace=Namespace.USER_FILES,
        filename="draft.pdf",
        mime="application/pdf",
        byte_size=10,
        blob_sha256="e" * 64,
    )

    documents.claim([draft.id], conversation_id=conversation.id)

    claimed = documents.get(draft.id)
    assert claimed is not None
    assert claimed.conversation_id == conversation.id


def test_list_by_folder_returns_that_folders_documents_only(session: Session) -> None:
    folders = FolderRepository(session)
    documents = DocumentRepository(session)
    mine = folders.create("Vzory")
    theirs = folders.create("Klienti")
    _create(documents, folder_id=mine.id)
    _create(documents, folder_id=theirs.id, sha=SHA_B, name="jine.pdf")

    listed = documents.list_by_folder(mine.id)

    assert [item.filename for item in listed] == ["smlouva.pdf"]


def test_list_unbound_finds_only_old_fully_unlocated_documents(session: Session) -> None:
    documents = DocumentRepository(session)
    now = datetime.now(UTC)
    old_draft = orm.Document(
        id=uuid4(),
        namespace=str(Namespace.USER_FILES),
        filename="old.pdf",
        mime="application/pdf",
        byte_size=1,
        blob_sha256="f" * 64,
        status="indexed",
        uploaded_at=now - timedelta(hours=25),
    )
    young_draft = orm.Document(
        id=uuid4(),
        namespace=str(Namespace.USER_FILES),
        filename="young.pdf",
        mime="application/pdf",
        byte_size=1,
        blob_sha256="0" * 64,
        status="indexed",
        uploaded_at=now - timedelta(hours=1),
    )
    session.add_all([old_draft, young_draft])
    session.flush()
    folder = FolderRepository(session).create("Vzory")
    _create(documents, folder_id=folder.id, sha=SHA_B, name="placed.pdf")

    unbound = documents.list_unbound(older_than=now - timedelta(hours=24))

    assert [item.filename for item in unbound] == ["old.pdf"]


def test_sweep_unbound_attachments_removes_only_old_drafts(
    db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``sweep_unbound_attachments`` opens its own ``session_scope()``, a
    fresh connection from the global sessionmaker -- unlike the ``session``
    fixture's rolled-back savepoint, that connection cannot see uncommitted
    data, so setup and verification here go through a real, committed
    ``Session(bind=db_engine)`` instead."""
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    monkeypatch.setattr(
        "law_agent.documents.service.get_qdrant_client", lambda: QdrantClient(":memory:")
    )
    now = datetime.now(UTC)
    old_draft = orm.Document(
        id=uuid4(),
        namespace=str(Namespace.USER_FILES),
        filename="old.pdf",
        mime="application/pdf",
        byte_size=1,
        blob_sha256="1" * 64,
        status="indexed",
        uploaded_at=now - timedelta(hours=25),
    )
    young_draft = orm.Document(
        id=uuid4(),
        namespace=str(Namespace.USER_FILES),
        filename="young.pdf",
        mime="application/pdf",
        byte_size=1,
        blob_sha256="2" * 64,
        status="indexed",
        uploaded_at=now - timedelta(hours=1),
    )
    old_draft_id, young_draft_id = old_draft.id, young_draft.id
    with Session(bind=db_engine) as setup_session:
        setup_session.add_all([old_draft, young_draft])
        folder = FolderRepository(setup_session).create("Vzory")
        _create(
            DocumentRepository(setup_session), folder_id=folder.id, sha=SHA_B, name="placed.pdf"
        )
        setup_session.commit()

    stats = sweep_unbound_attachments(now=now)

    assert stats.deleted == 1
    with Session(bind=db_engine) as verify_session:
        remaining = DocumentRepository(verify_session)
        remaining_names = {
            row.filename
            for row_id in (old_draft_id, young_draft_id)
            if (row := remaining.get(row_id))
        }
    assert remaining_names == {"young.pdf"}
