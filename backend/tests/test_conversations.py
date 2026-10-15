"""Tests for the conversation archive: schema, repositories and ask()."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from law_agent.conversations import ConversationMeta, Role
from law_agent.conversations import service as conversation_service
from law_agent.conversations.blocks import offered_items, text_block
from law_agent.conversations.models import AttachmentNotFoundError
from law_agent.conversations.service import (
    ConversationNotFoundError,
    ask,
    create_conversation,
    history,
)
from law_agent.db import models as orm
from law_agent.db import session_scope as session_scope_for_test
from law_agent.db.repositories import ConversationRepository, MessageRepository
from law_agent.retrieval import RetrievedChunk


def test_schema_upgrades_on_a_clean_database(db_engine: Engine) -> None:
    """The fixture itself runs ``alembic upgrade head``; this asserts the result."""
    inspector = inspect(db_engine)

    assert set(inspector.get_table_names()) >= {"conversations", "messages"}
    assert {index["name"] for index in inspector.get_indexes("conversations")} >= {
        "ix_conversations_owner_updated"
    }
    assert {index["name"] for index in inspector.get_indexes("messages")} >= {
        "ux_messages_conversation_seq"
    }
    # Promoted now that the table it points at exists.
    foreign_keys = inspector.get_foreign_keys("documents")
    assert any(key["referred_table"] == "messages" for key in foreign_keys)
    assert "conversation_id" in {column["name"] for column in inspector.get_columns("documents")}


def test_a_new_conversation_keeps_its_source_selection(session: Session) -> None:
    """Continuing an old conversation must run over the scope it was answered
    from, so the selection is frozen with it rather than passed in each time."""
    repository = ConversationRepository(session)

    created = repository.create(
        "admin", title="Odstoupení", meta=ConversationMeta(scope=["laws"], limit=5)
    )
    loaded = repository.get(created.id)

    assert loaded is not None
    assert loaded.meta == ConversationMeta(scope=["laws"], limit=5)


def test_messages_get_consecutive_seq_and_read_back_in_order(session: Session) -> None:
    conversation = ConversationRepository(session).create(
        "admin", title="T", meta=ConversationMeta()
    )
    messages = MessageRepository(session)

    messages.append(conversation.id, role=Role.USER, blocks=[text_block("otázka")])
    messages.append(conversation.id, role=Role.ASSISTANT, blocks=[text_block("odpověď")])

    rows = messages.list(conversation.id)
    assert [(row.seq, row.role) for row in rows] == [(1, Role.USER), (2, Role.ASSISTANT)]


def test_two_messages_cannot_share_a_seq(session: Session) -> None:
    conversation = ConversationRepository(session).create(
        "admin", title="T", meta=ConversationMeta()
    )
    MessageRepository(session).append(conversation.id, role=Role.USER, blocks=[text_block("a")])

    session.add(
        orm.Message(
            id=uuid4(),
            conversation_id=conversation.id,
            seq=1,
            role="user",
            blocks=[text_block("b")],
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_concurrent_appends_to_the_same_conversation_both_land(db_engine: Engine) -> None:
    """A double-click on send, or two open panels over the same conversation,
    starts two ``append`` calls that compute the same ``seq`` before either
    commits. The retry-on-conflict loop must give each a distinct one instead
    of letting the second crash."""
    with Session(bind=db_engine) as setup_session:
        conversation = ConversationRepository(setup_session).create(
            "concurrent-test-owner", title="T", meta=ConversationMeta()
        )
        setup_session.commit()
        conversation_id = conversation.id

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def append_one(text: str) -> None:
        with Session(bind=db_engine) as thread_session:
            barrier.wait()
            try:
                MessageRepository(thread_session).append(
                    conversation_id, role=Role.USER, blocks=[text_block(text)]
                )
                thread_session.commit()
            except Exception as error:  # noqa: BLE001
                errors.append(error)

    threads = [threading.Thread(target=append_one, args=(t,)) for t in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with Session(bind=db_engine) as verify_session:
        rows = MessageRepository(verify_session).list(conversation_id)
    assert sorted(row.seq for row in rows) == [1, 2]


def test_a_soft_deleted_conversation_leaves_the_list(session: Session) -> None:
    repository = ConversationRepository(session)
    kept = repository.create("admin", title="Zůstává", meta=ConversationMeta())
    gone = repository.create("admin", title="Mizí", meta=ConversationMeta())

    repository.soft_delete(gone.id)

    assert [item.id for item in repository.list("admin")] == [kept.id]
    deleted = repository.get(gone.id)
    assert deleted is not None
    assert deleted.deleted_at is not None


def test_conversations_are_listed_newest_first(session: Session) -> None:
    repository = ConversationRepository(session)
    first = repository.create("admin", title="První", meta=ConversationMeta())
    second = repository.create("admin", title="Druhá", meta=ConversationMeta())

    repository.touch(first.id)

    assert [item.id for item in repository.list("admin")] == [first.id, second.id]


def test_another_owner_sees_nothing(session: Session) -> None:
    ConversationRepository(session).create("admin", title="T", meta=ConversationMeta())

    assert ConversationRepository(session).list("nekdo-jiny") == []


class TurnModel(BaseChatModel):
    """A model that calls ``search`` once and then answers with ``answer``.

    ``bind_tools`` returns ``self`` because ``GenericFakeChatModel`` cannot bind
    tools at all, and binding is part of the flow under test.
    """

    answer: str = "Do 14 dnů [1]."
    fail_on_stream: bool = False

    @property
    def _llm_type(self) -> str:
        return "turn"

    def bind_tools(  # type: ignore[override]
        self,
        tools: Sequence[Any],  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> TurnModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],  # noqa: ARG002
        stop: Any = None,  # noqa: ARG002
        run_manager: Any = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ChatResult:
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search",
                    "args": {"query": "odstoupení od smlouvy"},
                    "id": "call_a1",
                    "type": "tool_call",
                }
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: list[BaseMessage],  # noqa: ARG002
        stop: Any = None,  # noqa: ARG002
        run_manager: Any = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> Iterator[ChatGenerationChunk]:
        for word in self.answer.split(" "):
            if self.fail_on_stream:
                msg = "stream died"
                raise RuntimeError(msg)
            yield ChatGenerationChunk(message=AIMessageChunk(content=word + " "))


def _fake_search(*args: Any, **kwargs: Any) -> list[RetrievedChunk]:  # noqa: ARG001
    return [
        RetrievedChunk(
            score=0.9,
            chunk_id="c1",
            citation="§ 1829 obč. zák.",
            text="Spotřebitel má právo odstoupit od smlouvy do 14 dnů.",
            payload={
                "namespace": "laws",
                "chunk_id": "c1",
                "law_id": "/eli/x",
                "anchor_fragment_id": "/eli/x/par_1829",
            },
        )
    ]


@pytest.fixture
def stub_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversation_service, "search", _fake_search)


@pytest.fixture
def stub_engine(monkeypatch: pytest.MonkeyPatch, db_engine: Engine) -> None:
    """Point the service's ``session_scope`` at the test database."""
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr("law_agent.db.engine.get_sessionmaker", lambda: factory)


@pytest.mark.usefixtures("stub_engine")
def test_a_given_title_is_truncated_to_thirty_characters() -> None:
    long_title = "x" * 200
    conversation_id = create_conversation("admin", user_id=uuid4(), title=long_title)

    with session_scope_for_test() as session:
        conversation = ConversationRepository(session).get(conversation_id)
    assert conversation is not None
    assert len(conversation.title) == 30
    assert conversation.title.endswith("…")


@pytest.mark.usefixtures("stub_engine")
def test_asking_an_unknown_conversation_raises() -> None:
    with pytest.raises(ConversationNotFoundError):
        ask(uuid4(), "dotaz", user_id=uuid4())


@pytest.mark.usefixtures("stub_engine", "stub_search")
def test_one_question_leaves_four_rows() -> None:
    conversation_id = create_conversation("admin", user_id=uuid4(), title="T")

    answer = ask(conversation_id, "Kdy můžu odstoupit?", model=TurnModel(), user_id=uuid4())
    text = "".join(answer)

    assert [item.ref for item in answer.items] == [1]
    assert "14 dnů" in text
    rows = history(conversation_id)
    assert [row.role for row in rows] == [Role.USER, Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert rows[1].blocks[0]["type"] == "tool_use"
    assert rows[1].blocks[0]["args"]["query"] == "odstoupení od smlouvy"
    assert rows[2].blocks[0]["items"][0]["label"] == "§ 1829 obč. zák."


@pytest.mark.usefixtures("stub_engine", "stub_search")
def test_the_items_are_available_before_the_first_token() -> None:
    """The UI needs the source panel before it starts streaming."""
    conversation_id = create_conversation("admin", user_id=uuid4(), title="T")

    answer = ask(conversation_id, "dotaz", model=TurnModel(), user_id=uuid4())

    assert answer.items
    assert history(conversation_id)[-1].role is Role.USER  # nothing written yet


@pytest.mark.usefixtures("stub_engine", "stub_search")
def test_a_broken_stream_leaves_only_the_question() -> None:
    """Nothing is written until the answer is whole, which is why there is no
    ``status`` column: an interrupted turn cannot leave a broken shape."""
    conversation_id = create_conversation("admin", user_id=uuid4(), title="T")

    answer = ask(conversation_id, "dotaz", model=TurnModel(fail_on_stream=True), user_id=uuid4())
    with pytest.raises(RuntimeError, match="stream died"):
        list(answer)

    rows = history(conversation_id)
    assert [row.role for row in rows] == [Role.USER]


@pytest.mark.usefixtures("stub_engine", "stub_search")
def test_a_rediscovered_chunk_keeps_its_ref_across_turns() -> None:
    """``_fake_search`` returns the same chunk every time; two numbers for it
    would make one paragraph look like two sources."""
    conversation_id = create_conversation("admin", user_id=uuid4(), title="T")
    list(ask(conversation_id, "první", model=TurnModel(), user_id=uuid4()))

    second = ask(conversation_id, "druhý", model=TurnModel(), user_id=uuid4())
    list(second)

    assert [item.ref for item in second.items] == [1]
    assert sorted(offered_items(history(conversation_id))) == [1]


@pytest.mark.usefixtures("stub_engine", "stub_search")
def test_the_second_turn_sees_the_first_turn_s_cited_material() -> None:
    """The whole point: question three can cite what question one retrieved."""
    conversation_id = create_conversation("admin", user_id=uuid4(), title="T")
    list(ask(conversation_id, "první", model=TurnModel(), user_id=uuid4()))

    seen: list[list[BaseMessage]] = []

    class RecordingModel(TurnModel):
        def _stream(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
            seen.append(list(messages))
            return super()._stream(messages, stop, run_manager, **kwargs)

    list(ask(conversation_id, "druhý", model=RecordingModel(), user_id=uuid4()))

    # seen[0] starts with the SystemMessage the chain prepends, so pick the
    # tool messages out rather than indexing into the list.
    results = [message for message in seen[0] if isinstance(message, ToolMessage)]
    assert len(results) == 2
    assert "Spotřebitel má právo odstoupit" in str(results[0].text)
    assert "uvedeno výše" in str(results[1].text)


@pytest.fixture
def stub_ingest(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Records ingest calls instead of parsing and indexing.

    The real path needs docling-serve and Qdrant; what these tests are about is
    the bookkeeping around it -- which conversation the row lands in and which
    message claims it.
    """
    calls: list[dict[str, Any]] = []

    def fake_ingest(data: bytes, **kwargs: Any) -> UUID:
        from law_agent.db import DocumentRepository, session_scope
        from law_agent.documents.models import Namespace

        calls.append({"data": data, **kwargs})
        with session_scope() as session:
            document = DocumentRepository(session).create(
                namespace=Namespace.USER_FILES,
                filename=str(kwargs["filename"]),
                mime="application/pdf",
                byte_size=len(data),
                blob_sha256=uuid4().hex * 2,
                conversation_id=kwargs.get("conversation_id"),
                message_id=kwargs.get("message_id"),
            )
            session.commit()
        return document.id

    monkeypatch.setattr(conversation_service, "ingest_document", fake_ingest)
    return calls


@pytest.mark.usefixtures("stub_engine")
def test_an_attachment_is_uploaded_against_the_conversation(
    stub_ingest: list[dict[str, Any]],
) -> None:
    conversation_id = create_conversation("admin", user_id=uuid4())

    document = conversation_service.add_attachment(
        b"pdf-bytes", filename="smlouva.pdf", conversation_id=conversation_id
    )

    assert document.conversation_id == conversation_id
    assert document.message_id is None
    assert stub_ingest[0]["conversation_id"] == conversation_id
    assert [item.id for item in conversation_service.attachments(conversation_id)] == [document.id]


@pytest.mark.usefixtures("stub_engine")
def test_uploading_to_an_unknown_conversation_raises(stub_ingest: list[dict[str, Any]]) -> None:
    with pytest.raises(ConversationNotFoundError):
        conversation_service.add_attachment(b"pdf", filename="x.pdf", conversation_id=uuid4())
    assert stub_ingest == []


@pytest.mark.usefixtures("stub_engine", "stub_search")
def test_the_referenced_attachment_is_claimed_by_the_question(
    stub_ingest: list[dict[str, Any]],  # noqa: ARG001
) -> None:
    """This is what makes the archive's citations resolvable: after the turn,
    the file is on the message that used it, not floating in the conversation."""
    conversation_id = create_conversation("admin", user_id=uuid4())
    document = conversation_service.add_attachment(
        b"pdf", filename="s.pdf", conversation_id=conversation_id
    )

    list(
        ask(
            conversation_id,
            "Co je ve smlouvě?",
            attachment_ids=[document.id],
            model=TurnModel(),
            user_id=uuid4(),
        )
    )

    assert conversation_service.attachments(conversation_id) == []
    question = history(conversation_id)[0]
    with session_scope_for_test() as session:
        from law_agent.db import DocumentRepository

        claimed = DocumentRepository(session).get(document.id)
    assert claimed is not None
    assert claimed.message_id == question.id


@pytest.mark.usefixtures("stub_engine", "stub_search")
def test_an_attachment_from_another_conversation_is_refused(
    stub_ingest: list[dict[str, Any]],  # noqa: ARG001
) -> None:
    mine = create_conversation("admin", user_id=uuid4())
    theirs = create_conversation("nekdo-jiny", user_id=uuid4())
    document = conversation_service.add_attachment(b"pdf", filename="s.pdf", conversation_id=theirs)

    with pytest.raises(AttachmentNotFoundError):
        ask(mine, "dotaz", attachment_ids=[document.id], model=TurnModel(), user_id=uuid4())


@pytest.mark.usefixtures("stub_engine", "stub_search")
def test_an_untitled_conversation_stays_untitled_after_its_first_turn() -> None:
    """Titling moved to creation time -- ask() no longer names the thread."""
    conversation_id = create_conversation("admin", user_id=uuid4())

    list(ask(conversation_id, "Kdy můžu odstoupit od smlouvy?", model=TurnModel(), user_id=uuid4()))

    with session_scope_for_test() as session:
        conversation = ConversationRepository(session).get(conversation_id)
    assert conversation is not None
    assert conversation.title == ""


@pytest.mark.usefixtures("stub_engine")
def test_narrow_org_files_selection_expands_unopened_subfolders() -> None:
    """A checked-but-unopened parent folder is what the client actually sends
    -- ``_narrow_org_files_selection`` intersects it against the ceiling
    as-is and lets it through unchanged, since it's within the ceiling. The
    subtree-expansion fix for the real under-match bug lives in `search()`'s
    own narrowing branch (see `test_search_org_files_narrowing_expands_unopened_subfolders`
    in test_search.py): this test only documents that this layer does not
    need to know about subtrees at all."""
    from law_agent.access.models import Permission, PrincipalType, ResourceType
    from law_agent.access.service import upsert_acl_entry
    from law_agent.conversations.service import _narrow_org_files_selection
    from law_agent.db import (
        DocumentRepository,
        FolderRepository,
        RoleRepository,
        UserRepository,
        session_scope,
    )
    from law_agent.documents.models import Namespace, ScopeSource

    with session_scope() as session:
        role = RoleRepository(session).create(f"role-{uuid4().hex[:8]}")
        user = UserRepository(session).create(
            email=f"{uuid4().hex}@firma.cz", password_hash="hash", role_id=role.id
        )
        folder_repo = FolderRepository(session)
        parent = folder_repo.create(f"parent-{uuid4().hex[:8]}")
        unopened_child = folder_repo.create(f"child-{uuid4().hex[:8]}", parent_id=parent.id)
        DocumentRepository(session).create(
            namespace=Namespace.ORG_FILES,
            filename="a.pdf",
            mime="application/pdf",
            byte_size=1,
            blob_sha256=uuid4().hex,
            folder_id=unopened_child.id,
        )
        session.commit()

    upsert_acl_entry(
        resource_type=ResourceType.FOLDER,
        resource_id=parent.id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.READ,
    )

    meta = ConversationMeta(
        scope=[ScopeSource.ORG_FILES],
        org_files_folder_ids=[parent.id],
        org_files_document_ids=None,
    )
    narrowed = _narrow_org_files_selection(meta, user.id)

    assert narrowed.org_files_folder_ids == [parent.id]


def test_org_files_folder_ids_outside_the_accessible_set_is_silently_dropped(
    monkeypatch: pytest.MonkeyPatch,
    stub_engine: None,
) -> None:
    allowed = uuid4()
    stale = uuid4()
    # No full org-files access, so the intersection actually runs against the
    # mocked ceiling below rather than being trusted as-is.
    monkeypatch.setattr(
        "law_agent.conversations.service.has_full_org_files_access", lambda _user_id: False
    )
    monkeypatch.setattr(
        "law_agent.conversations.service.accessible_org_folder_ids",
        lambda _user_id: {allowed},
    )
    monkeypatch.setattr(
        "law_agent.conversations.service.directly_granted_document_ids",
        lambda _user_id: set(),
    )

    conversation_id = create_conversation(
        "admin",
        user_id=uuid4(),
        title="T",
        meta=ConversationMeta(org_files_folder_ids=[allowed, stale]),
    )

    with session_scope_for_test() as session:
        stored = ConversationRepository(session).get(conversation_id)
    assert stored is not None
    assert stored.meta.org_files_folder_ids == [allowed]


def test_a_superusers_org_files_selection_is_preserved_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
    stub_engine: None,
) -> None:
    """A superuser holds no personal ACL rows, so intersecting their
    narrowing against `accessible_org_folder_ids`/`directly_granted_document_ids`
    would silently wipe it out -- their explicit selection must be trusted
    as-is instead, mirroring how `search()` already treats full access."""
    folder_id = uuid4()
    document_id = uuid4()

    def _boom(_user_id: UUID) -> set[UUID]:
        raise AssertionError("the ACL resolvers must not run for a superuser")

    monkeypatch.setattr(
        "law_agent.conversations.service.has_full_org_files_access", lambda _user_id: True
    )
    monkeypatch.setattr("law_agent.conversations.service.accessible_org_folder_ids", _boom)
    monkeypatch.setattr("law_agent.conversations.service.directly_granted_document_ids", _boom)

    conversation_id = create_conversation(
        "admin",
        user_id=uuid4(),
        title="T",
        meta=ConversationMeta(
            org_files_folder_ids=[folder_id], org_files_document_ids=[document_id]
        ),
    )

    with session_scope_for_test() as session:
        stored = ConversationRepository(session).get(conversation_id)
    assert stored is not None
    assert stored.meta.org_files_folder_ids == [folder_id]
    assert stored.meta.org_files_document_ids == [document_id]


def test_a_capability_holders_org_files_selection_is_preserved_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
    stub_engine: None,
) -> None:
    """A non-superuser role holding MANAGE_ORG_FILES_STRUCTURE gets the same
    treatment as a superuser: `_narrow_org_files_selection` only consumes the
    already-resolved `has_full_org_files_access` boolean, so it cannot tell
    the two cases apart -- that distinction is `has_full_org_files_access`'s
    own job, covered separately in `test_access_service.py`."""
    folder_id = uuid4()
    document_id = uuid4()

    def _boom(_user_id: UUID) -> set[UUID]:
        raise AssertionError("the ACL resolvers must not run for a capability holder")

    monkeypatch.setattr(
        "law_agent.conversations.service.has_full_org_files_access", lambda _user_id: True
    )
    monkeypatch.setattr("law_agent.conversations.service.accessible_org_folder_ids", _boom)
    monkeypatch.setattr("law_agent.conversations.service.directly_granted_document_ids", _boom)

    conversation_id = create_conversation(
        "admin",
        user_id=uuid4(),
        title="T",
        meta=ConversationMeta(
            org_files_folder_ids=[folder_id], org_files_document_ids=[document_id]
        ),
    )

    with session_scope_for_test() as session:
        stored = ConversationRepository(session).get(conversation_id)
    assert stored is not None
    assert stored.meta.org_files_folder_ids == [folder_id]
    assert stored.meta.org_files_document_ids == [document_id]
