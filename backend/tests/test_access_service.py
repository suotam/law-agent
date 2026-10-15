"""effective_permission: the resolver retrieval filtering will depend on."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from law_agent.access.member_view import folder_contents, list_roots
from law_agent.access.models import Permission, PrincipalType, ResourceType, RoleCapability
from law_agent.access.service import (
    accessible_org_folder_ids,
    directly_granted_document_ids,
    effective_permission,
    role_for_user,
)
from law_agent.db.repositories import (
    AclRepository,
    DocumentRepository,
    FolderRepository,
    GroupRepository,
    RoleRepository,
    UserRepository,
)


def _make_user(engine, *, role_name: str = "Member2"):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        role = RoleRepository(session).create(role_name)
        user = UserRepository(session).create(
            email=f"{uuid4().hex}@firma.cz", password_hash="hash", role_id=role.id
        )
        session.commit()
    return user


def test_no_grants_anywhere_on_the_chain_is_none(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = _make_user(db_engine)
    with factory() as session:
        folder = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        session.commit()

    assert effective_permission(user.id, ResourceType.FOLDER, folder.id) is None


def test_a_grant_on_an_ancestor_folder_is_inherited_by_a_deep_document(
    db_engine, monkeypatch
) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = _make_user(db_engine)
    with factory() as session:
        root = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        child = FolderRepository(session).create("Klient A", parent_id=root.id)
        group = GroupRepository(session).create(f"grp-{uuid4().hex[:8]}")
        GroupRepository(session).add_member(group.id, user.id)
        AclRepository(session).upsert(
            resource_type=ResourceType.FOLDER,
            resource_id=root.id,
            principal_type=PrincipalType.GROUP,
            principal_id=group.id,
            permission=Permission.READ,
        )
        document = DocumentRepository(session).create(
            namespace="org_files",
            filename="smlouva.pdf",
            mime="application/pdf",
            byte_size=1,
            blob_sha256=uuid4().hex,
            folder_id=child.id,
        )
        session.commit()

    assert effective_permission(user.id, ResourceType.FOLDER, child.id) is Permission.READ
    assert effective_permission(user.id, ResourceType.DOCUMENT, document.id) is Permission.READ


def test_a_direct_grant_on_one_document_needs_no_ancestor_grant(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = _make_user(db_engine)
    with factory() as session:
        folder = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        document = DocumentRepository(session).create(
            namespace="org_files",
            filename="tajne.pdf",
            mime="application/pdf",
            byte_size=1,
            blob_sha256=uuid4().hex,
            folder_id=folder.id,
        )
        AclRepository(session).upsert(
            resource_type=ResourceType.DOCUMENT,
            resource_id=document.id,
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            permission=Permission.READ,
        )
        session.commit()

    assert effective_permission(user.id, ResourceType.DOCUMENT, document.id) is Permission.READ


def test_a_write_grant_wins_over_a_read_grant_on_the_same_principal(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = _make_user(db_engine)
    with factory() as session:
        folder = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        document = DocumentRepository(session).create(
            namespace="org_files",
            filename="smlouva.pdf",
            mime="application/pdf",
            byte_size=1,
            blob_sha256=uuid4().hex,
            folder_id=folder.id,
        )
        sibling = DocumentRepository(session).create(
            namespace="org_files",
            filename="jina.pdf",
            mime="application/pdf",
            byte_size=1,
            blob_sha256=uuid4().hex,
            folder_id=folder.id,
        )
        AclRepository(session).upsert(
            resource_type=ResourceType.FOLDER,
            resource_id=folder.id,
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            permission=Permission.READ,
        )
        AclRepository(session).upsert(
            resource_type=ResourceType.DOCUMENT,
            resource_id=document.id,
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            permission=Permission.WRITE,
        )
        session.commit()

    assert effective_permission(user.id, ResourceType.DOCUMENT, document.id) is Permission.WRITE
    assert effective_permission(user.id, ResourceType.DOCUMENT, sibling.id) is Permission.READ


def test_a_user_with_no_groups_and_no_direct_grant_is_none(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = _make_user(db_engine)
    with factory() as session:
        folder = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        other_group = GroupRepository(session).create(f"jina-{uuid4().hex[:8]}")
        AclRepository(session).upsert(
            resource_type=ResourceType.FOLDER,
            resource_id=folder.id,
            principal_type=PrincipalType.GROUP,
            principal_id=other_group.id,
            permission=Permission.READ,
        )
        session.commit()

    assert effective_permission(user.id, ResourceType.FOLDER, folder.id) is None


def test_role_for_user_reflects_the_current_role(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as session:
        role = RoleRepository(session).create(f"Manager-{uuid4().hex[:8]}")
        RoleRepository(session).set_capabilities(role.id, [RoleCapability.MANAGE_GROUPS])
        user = UserRepository(session).create(
            email=f"{uuid4().hex}@firma.cz", password_hash="hash", role_id=role.id
        )
        session.commit()

    found = role_for_user(user.id)

    assert found is not None
    assert found.capabilities == frozenset({RoleCapability.MANAGE_GROUPS})


def test_role_for_user_is_none_for_an_unknown_user(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    assert role_for_user(uuid4()) is None


def test_subtree_ids_includes_seed_and_descendants_but_not_a_sibling(db_engine) -> None:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as session:
        root = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        child = FolderRepository(session).create("Klient A", parent_id=root.id)
        grandchild = FolderRepository(session).create("Smlouvy", parent_id=child.id)
        sibling = FolderRepository(session).create("Klient B", parent_id=root.id)
        session.commit()

        result = FolderRepository(session).subtree_ids([child.id])

    assert result == {child.id, grandchild.id}
    assert sibling.id not in result


def test_subtree_ids_of_no_seeds_is_empty(db_engine) -> None:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as session:
        assert FolderRepository(session).subtree_ids([]) == set()


def test_resource_ids_for_principals_matches_user_or_group_not_a_stranger(db_engine) -> None:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = _make_user(db_engine)
    with factory() as session:
        granted = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        ungranted = FolderRepository(session).create(f"other-{uuid4().hex[:8]}")
        group = GroupRepository(session).create(f"grp-{uuid4().hex[:8]}")
        GroupRepository(session).add_member(group.id, user.id)
        AclRepository(session).upsert(
            resource_type=ResourceType.FOLDER,
            resource_id=granted.id,
            principal_type=PrincipalType.GROUP,
            principal_id=group.id,
            permission=Permission.READ,
        )
        AclRepository(session).upsert(
            resource_type=ResourceType.FOLDER,
            resource_id=ungranted.id,
            principal_type=PrincipalType.USER,
            principal_id=uuid4(),
            permission=Permission.READ,
        )
        session.commit()

        result = AclRepository(session).resource_ids_for_principals(
            ResourceType.FOLDER, user_id=user.id, group_ids={group.id}
        )

    assert result == {granted.id}


def test_accessible_org_folder_ids_includes_grant_and_descendants_excludes_sibling(
    db_engine, monkeypatch
) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = _make_user(db_engine)
    with factory() as session:
        root = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        child = FolderRepository(session).create("Klient A", parent_id=root.id)
        sibling = FolderRepository(session).create("Klient B", parent_id=root.id)
        AclRepository(session).upsert(
            resource_type=ResourceType.FOLDER,
            resource_id=child.id,
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            permission=Permission.READ,
        )
        session.commit()

    result = accessible_org_folder_ids(user.id)

    assert result == {child.id}
    assert sibling.id not in result


def test_directly_granted_document_ids_surfaces_a_document_with_no_ancestor_grant(
    db_engine, monkeypatch
) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = _make_user(db_engine)
    with factory() as session:
        folder = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        document = DocumentRepository(session).create(
            namespace="org_files",
            filename="tajne.pdf",
            mime="application/pdf",
            byte_size=1,
            blob_sha256=uuid4().hex,
            folder_id=folder.id,
        )
        AclRepository(session).upsert(
            resource_type=ResourceType.DOCUMENT,
            resource_id=document.id,
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            permission=Permission.READ,
        )
        session.commit()

    assert directly_granted_document_ids(user.id) == {document.id}


def test_accessible_org_folder_ids_is_empty_with_no_grants(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    user = _make_user(db_engine)
    assert accessible_org_folder_ids(user.id) == set()
    assert directly_granted_document_ids(user.id) == set()


def test_list_roots_returns_a_granted_folder_but_not_its_ungranted_parent(
    db_engine, monkeypatch
) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = _make_user(db_engine)
    with factory() as session:
        root = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        litigation = FolderRepository(session).create("Litigation", parent_id=root.id)
        AclRepository(session).upsert(
            resource_type=ResourceType.FOLDER,
            resource_id=litigation.id,
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            permission=Permission.READ,
        )
        session.commit()

    roots = list_roots(user.id)

    assert [item.folder.id for item in roots] == [litigation.id]
    assert roots[0].ancestor_path == root.name


def test_folder_contents_reaches_a_folder_two_levels_below_a_grant(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = _make_user(db_engine)
    with factory() as session:
        granted = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        mid = FolderRepository(session).create("2026", parent_id=granted.id)
        deep = FolderRepository(session).create("Q1", parent_id=mid.id)
        AclRepository(session).upsert(
            resource_type=ResourceType.FOLDER,
            resource_id=granted.id,
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            permission=Permission.READ,
        )
        session.commit()

    contents = folder_contents(user.id, mid.id)

    assert contents is not None
    assert [item.id for item in contents.folders] == [deep.id]


def test_folder_contents_is_none_outside_the_accessible_set(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = _make_user(db_engine)
    with factory() as session:
        other = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        session.commit()

    assert folder_contents(user.id, other.id) is None


def test_a_user_with_no_grants_gets_empty_results_everywhere(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    user = _make_user(db_engine)

    assert list_roots(user.id) == []


def test_folder_contents_on_path_only_folder_shows_only_granted_document(
    db_engine, monkeypatch
) -> None:
    from law_agent.access.service import upsert_acl_entry
    from law_agent.db import DocumentRepository, FolderRepository, session_scope
    from law_agent.documents.models import Namespace

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    user = _make_user(db_engine)
    with session_scope() as session:
        folder_repo = FolderRepository(session)
        root = folder_repo.create(f"root-{uuid4().hex[:8]}")
        granted_doc = DocumentRepository(session).create(
            namespace=Namespace.ORG_FILES,
            filename="granted.pdf",
            mime="application/pdf",
            byte_size=1,
            blob_sha256=uuid4().hex,
            folder_id=root.id,
        )
        DocumentRepository(session).create(
            namespace=Namespace.ORG_FILES,
            filename="other.pdf",
            mime="application/pdf",
            byte_size=1,
            blob_sha256=uuid4().hex,
            folder_id=root.id,
        )
        folder_repo.create(f"sibling-{uuid4().hex[:8]}", parent_id=root.id)
        session.commit()

    upsert_acl_entry(
        resource_type=ResourceType.DOCUMENT,
        resource_id=granted_doc.id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.READ,
    )

    contents = folder_contents(user.id, root.id)

    assert contents is not None
    assert [d.id for d in contents.documents] == [granted_doc.id]
    assert contents.folders == []  # sibling_folder is not visible: no grant anywhere under it


def test_list_roots_includes_virtual_root_for_path_only_ancestor(db_engine, monkeypatch) -> None:
    from law_agent.access.service import upsert_acl_entry
    from law_agent.db import DocumentRepository, FolderRepository, session_scope
    from law_agent.documents.models import Namespace

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    user = _make_user(db_engine)
    with session_scope() as session:
        folder_repo = FolderRepository(session)
        root = folder_repo.create(f"root-{uuid4().hex[:8]}")
        leaf = folder_repo.create(f"leaf-{uuid4().hex[:8]}", parent_id=root.id)
        document = DocumentRepository(session).create(
            namespace=Namespace.ORG_FILES,
            filename="a.pdf",
            mime="application/pdf",
            byte_size=1,
            blob_sha256=uuid4().hex,
            folder_id=leaf.id,
        )
        session.commit()

    upsert_acl_entry(
        resource_type=ResourceType.DOCUMENT,
        resource_id=document.id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.READ,
    )

    roots = list_roots(user.id)

    assert {r.folder.id for r in roots} == {root.id}


def test_upsert_acl_entry_rejects_write_on_document(db_engine):
    from law_agent.access.models import InvalidAclGrantError
    from law_agent.access.service import upsert_acl_entry

    user = _make_user(db_engine)
    with pytest.raises(InvalidAclGrantError):
        upsert_acl_entry(
            resource_type=ResourceType.DOCUMENT,
            resource_id=uuid4(),
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            permission=Permission.WRITE,
        )


def test_upsert_acl_entry_on_folder_prunes_same_principal_subtree_grants(db_engine, monkeypatch):
    from law_agent.access.service import upsert_acl_entry
    from law_agent.db import FolderRepository, session_scope

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    user = _make_user(db_engine)
    other_user = _make_user(db_engine)
    with session_scope() as session:
        folder_repo = FolderRepository(session)
        root = folder_repo.create(f"root-{uuid4().hex[:8]}")
        child = folder_repo.create(f"child-{uuid4().hex[:8]}", parent_id=root.id)
        session.commit()

    # user has a direct grant on the child, deeper than the root grant about to be set
    upsert_acl_entry(
        resource_type=ResourceType.FOLDER,
        resource_id=child.id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.WRITE,
    )
    # a different principal's grant on the same child must survive
    upsert_acl_entry(
        resource_type=ResourceType.FOLDER,
        resource_id=child.id,
        principal_type=PrincipalType.USER,
        principal_id=other_user.id,
        permission=Permission.READ,
    )

    upsert_acl_entry(
        resource_type=ResourceType.FOLDER,
        resource_id=root.id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.READ,
    )

    assert effective_permission(user.id, ResourceType.FOLDER, root.id) is Permission.READ
    # the child's direct WRITE grant for `user` was pruned -- root's READ now governs
    assert effective_permission(user.id, ResourceType.FOLDER, child.id) is Permission.READ
    # other_user's grant on child is untouched
    assert effective_permission(other_user.id, ResourceType.FOLDER, child.id) is Permission.READ


def test_delete_acl_entry_on_folder_prunes_subtree_grants(db_engine, monkeypatch):
    from law_agent.access.service import delete_acl_entry, upsert_acl_entry
    from law_agent.db import FolderRepository, session_scope

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    user = _make_user(db_engine)
    with session_scope() as session:
        folder_repo = FolderRepository(session)
        root = folder_repo.create(f"root-{uuid4().hex[:8]}")
        child = folder_repo.create(f"child-{uuid4().hex[:8]}", parent_id=root.id)
        session.commit()

    root_entry = upsert_acl_entry(
        resource_type=ResourceType.FOLDER,
        resource_id=root.id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.READ,
    )
    upsert_acl_entry(
        resource_type=ResourceType.FOLDER,
        resource_id=child.id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.WRITE,
    )

    delete_acl_entry(root_entry.id)

    assert effective_permission(user.id, ResourceType.FOLDER, root.id) is None
    assert effective_permission(user.id, ResourceType.FOLDER, child.id) is None


def test_delete_acl_entry_does_not_cascade_for_document_resource(db_engine, monkeypatch):
    from law_agent.access.service import delete_acl_entry, upsert_acl_entry
    from law_agent.db import FolderRepository, session_scope

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    user = _make_user(db_engine)
    with session_scope() as session:
        root = FolderRepository(session).create(f"root-{uuid4().hex[:8]}")
        session.commit()

    upsert_acl_entry(
        resource_type=ResourceType.FOLDER,
        resource_id=root.id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.READ,
    )
    document_id = uuid4()
    doc_entry = upsert_acl_entry(
        resource_type=ResourceType.DOCUMENT,
        resource_id=document_id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.READ,
    )
    delete_acl_entry(doc_entry.id)
    # deleting a document-scoped entry must not touch the folder grant
    assert effective_permission(user.id, ResourceType.FOLDER, root.id) is Permission.READ


def test_delete_folder_cascading_removes_subtree_acl_rows(db_engine, monkeypatch):
    from law_agent.access.service import delete_folder_cascading, upsert_acl_entry
    from law_agent.db import AclRepository, FolderRepository, session_scope

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    user = _make_user(db_engine)
    with session_scope() as session:
        folder_repo = FolderRepository(session)
        folder = folder_repo.create(f"leaf-{uuid4().hex[:8]}")
        session.commit()

    entry = upsert_acl_entry(
        resource_type=ResourceType.FOLDER,
        resource_id=folder.id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.READ,
    )

    delete_folder_cascading(folder.id)

    with session_scope() as session:
        assert AclRepository(session).get(entry.id) is None


def test_delete_folder_cascading_on_a_non_empty_folder_still_raises(db_engine, monkeypatch):
    from law_agent.access.service import delete_folder_cascading
    from law_agent.db import FolderRepository, session_scope
    from law_agent.documents.models import FolderNotEmptyError

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    with session_scope() as session:
        folder_repo = FolderRepository(session)
        parent = folder_repo.create(f"root-{uuid4().hex[:8]}")
        folder_repo.create(f"child-{uuid4().hex[:8]}", parent_id=parent.id)
        session.commit()

    with pytest.raises(FolderNotEmptyError):
        delete_folder_cascading(parent.id)


def test_upsert_acl_entry_allows_read_on_document(db_engine, monkeypatch):
    from law_agent.access.service import upsert_acl_entry

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    user = _make_user(db_engine)
    document_id = uuid4()
    entry = upsert_acl_entry(
        resource_type=ResourceType.DOCUMENT,
        resource_id=document_id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.READ,
    )
    assert entry.permission is Permission.READ
    assert entry.resource_id == document_id


def test_visible_folder_ids_includes_ancestors_of_directly_granted_document(db_engine, monkeypatch):
    from law_agent.access.service import (
        accessible_org_folder_ids,
        upsert_acl_entry,
        visible_folder_ids,
    )
    from law_agent.db import DocumentRepository, FolderRepository, session_scope
    from law_agent.documents.models import Namespace

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    user = _make_user(db_engine)
    with session_scope() as session:
        folder_repo = FolderRepository(session)
        root = folder_repo.create(f"root-{uuid4().hex[:8]}")
        leaf = folder_repo.create(f"leaf-{uuid4().hex[:8]}", parent_id=root.id)
        document = DocumentRepository(session).create(
            namespace=Namespace.ORG_FILES,
            filename="a.pdf",
            mime="application/pdf",
            byte_size=1,
            blob_sha256=uuid4().hex,
            folder_id=leaf.id,
        )
        session.commit()

    upsert_acl_entry(
        resource_type=ResourceType.DOCUMENT,
        resource_id=document.id,
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        permission=Permission.READ,
    )

    visible = visible_folder_ids(user.id)
    assert {root.id, leaf.id} <= visible
    # not retrievable: no folder grant exists, only the document grant
    assert leaf.id not in accessible_org_folder_ids(user.id)


def test_has_full_org_files_access_true_for_capability_holder(db_engine, monkeypatch):
    from law_agent.access.service import has_full_org_files_access
    from law_agent.db import RoleRepository, UserRepository, session_scope

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    with session_scope() as session:
        role_repo = RoleRepository(session)
        role = role_repo.create(f"structure-manager-{uuid4().hex[:6]}")
        role_repo.set_capabilities(role.id, [RoleCapability.MANAGE_ORG_FILES_STRUCTURE])
        user = UserRepository(session).create(
            email=f"{uuid4().hex[:8]}@example.com",
            password_hash="x",
            role_id=role.id,
        )
        session.commit()

    assert has_full_org_files_access(user.id) is True


def test_has_full_org_files_access_false_without_capability(db_engine, monkeypatch):
    from law_agent.access.service import has_full_org_files_access

    monkeypatch.setattr(
        "law_agent.db.engine.get_sessionmaker",
        lambda: sessionmaker(bind=db_engine, expire_on_commit=False),
    )
    user = _make_user(db_engine)
    assert has_full_org_files_access(user.id) is False
