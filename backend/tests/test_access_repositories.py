"""RoleRepository, GroupRepository, AclRepository and FolderRepository's
ancestor-chain walk -- the access control persistence layer."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from law_agent.access.models import (
    GroupNotFoundError,
    Permission,
    PrincipalType,
    ResourceType,
    RoleCapability,
    RoleInUseError,
    RoleNotFoundError,
)
from law_agent.db.repositories import (
    AclRepository,
    FolderRepository,
    GroupRepository,
    RoleRepository,
    UserRepository,
)


def test_a_role_is_created_with_no_capabilities(session: Session) -> None:
    role = RoleRepository(session).create("Manager")

    assert role.name == "Manager"
    assert role.is_superuser is False
    assert role.capabilities == frozenset()


def test_a_role_is_found_by_name(session: Session) -> None:
    RoleRepository(session).create("Manager")

    found = RoleRepository(session).get_by_name("Manager")

    assert found is not None
    assert found.name == "Manager"


def test_an_unknown_role_name_is_none(session: Session) -> None:
    assert RoleRepository(session).get_by_name("Ghost") is None


def test_capabilities_are_replaced_not_appended(session: Session) -> None:
    repository = RoleRepository(session)
    role = repository.create("Manager")

    repository.set_capabilities(role.id, [RoleCapability.MANAGE_GROUPS])
    repository.set_capabilities(role.id, [RoleCapability.MANAGE_USERS])

    reloaded = repository.get(role.id)
    assert reloaded is not None
    assert reloaded.capabilities == frozenset({RoleCapability.MANAGE_USERS})


def test_updating_an_unknown_role_raises(session: Session) -> None:
    with pytest.raises(RoleNotFoundError):
        RoleRepository(session).update(__import__("uuid").uuid4(), name="x")


def test_a_role_still_assigned_to_a_user_cannot_be_deleted(session: Session) -> None:
    repository = RoleRepository(session)
    role = repository.create("Manager")
    UserRepository(session).create(
        email="pouzivatel@firma.cz", password_hash="hash", role_id=role.id
    )

    with pytest.raises(RoleInUseError):
        repository.delete(role.id)


def test_an_unused_role_is_deleted(session: Session) -> None:
    repository = RoleRepository(session)
    role = repository.create("Manager")

    repository.delete(role.id)

    assert repository.get(role.id) is None


def test_a_group_is_created_and_listed(session: Session) -> None:
    repository = GroupRepository(session)
    group = repository.create("Klienti")

    assert group.name == "Klienti"
    assert group in repository.list()


def test_deleting_an_unknown_group_raises(session: Session) -> None:
    with pytest.raises(GroupNotFoundError):
        GroupRepository(session).delete(uuid4())


def test_membership_is_added_removed_and_listed(session: Session) -> None:
    groups = GroupRepository(session)
    group = groups.create("Klienti")
    user = UserRepository(session).create(
        email="clen@firma.cz",
        password_hash="hash",
        role_id=RoleRepository(session).create("Member2").id,
    )

    groups.add_member(group.id, user.id)
    assert [member.id for member in groups.members(group.id)] == [user.id]
    assert groups.groups_for_user(user.id) == {group.id}

    groups.remove_member(group.id, user.id)
    assert groups.members(group.id) == []
    assert groups.groups_for_user(user.id) == set()


def test_a_folder_with_no_parent_is_its_own_chain(session: Session) -> None:
    folder = FolderRepository(session).create("Smlouvy")

    assert FolderRepository(session).ancestor_chain(folder.id) == [folder.id]


def test_a_nested_folders_chain_runs_to_the_root(session: Session) -> None:
    folders = FolderRepository(session)
    root = folders.create("Smlouvy")
    child = folders.create("Klient A", parent_id=root.id)
    grandchild = folders.create("2026", parent_id=child.id)

    assert folders.ancestor_chain(grandchild.id) == [grandchild.id, child.id, root.id]


def test_an_unknown_folders_chain_is_empty(session: Session) -> None:
    assert FolderRepository(session).ancestor_chain(uuid4()) == []


def test_an_acl_entry_is_created(session: Session) -> None:
    folder = FolderRepository(session).create("Smlouvy")
    group = GroupRepository(session).create("Klienti")

    entry = AclRepository(session).upsert(
        resource_type=ResourceType.FOLDER,
        resource_id=folder.id,
        principal_type=PrincipalType.GROUP,
        principal_id=group.id,
        permission=Permission.READ,
    )

    assert entry.permission is Permission.READ
    listed = AclRepository(session).list_for_resource(ResourceType.FOLDER, folder.id)
    assert [e.id for e in listed] == [entry.id]


def test_upserting_the_same_grant_replaces_the_permission(session: Session) -> None:
    folder = FolderRepository(session).create("Smlouvy")
    group = GroupRepository(session).create("Klienti")
    repository = AclRepository(session)

    first = repository.upsert(
        resource_type=ResourceType.FOLDER,
        resource_id=folder.id,
        principal_type=PrincipalType.GROUP,
        principal_id=group.id,
        permission=Permission.READ,
    )
    second = repository.upsert(
        resource_type=ResourceType.FOLDER,
        resource_id=folder.id,
        principal_type=PrincipalType.GROUP,
        principal_id=group.id,
        permission=Permission.WRITE,
    )

    assert second.id == first.id
    assert second.permission is Permission.WRITE
    assert len(repository.list_for_resource(ResourceType.FOLDER, folder.id)) == 1


def test_deleting_an_acl_entry_removes_it(session: Session) -> None:
    folder = FolderRepository(session).create("Smlouvy")
    group = GroupRepository(session).create("Klienti")
    repository = AclRepository(session)
    entry = repository.upsert(
        resource_type=ResourceType.FOLDER,
        resource_id=folder.id,
        principal_type=PrincipalType.GROUP,
        principal_id=group.id,
        permission=Permission.READ,
    )

    repository.delete(entry.id)

    assert repository.list_for_resource(ResourceType.FOLDER, folder.id) == []


def test_delete_for_principal_on_resources_scopes_to_given_ids(db_engine):
    with Session(db_engine) as session:
        acl_repo = AclRepository(session)
        principal_id = uuid4()
        other_principal_id = uuid4()
        folder_id = uuid4()
        other_folder_id = uuid4()
        acl_repo.upsert(
            resource_type=ResourceType.FOLDER, resource_id=folder_id,
            principal_type=PrincipalType.USER, principal_id=principal_id, permission=Permission.READ,
        )
        acl_repo.upsert(
            resource_type=ResourceType.FOLDER, resource_id=other_folder_id,
            principal_type=PrincipalType.USER, principal_id=principal_id, permission=Permission.READ,
        )
        acl_repo.upsert(
            resource_type=ResourceType.FOLDER, resource_id=folder_id,
            principal_type=PrincipalType.USER, principal_id=other_principal_id, permission=Permission.WRITE,
        )
        session.commit()

        acl_repo.delete_for_principal_on_resources(
            PrincipalType.USER, principal_id, folder_ids={folder_id}, document_ids=set(),
        )
        session.commit()

        remaining = acl_repo.list_for_principal(PrincipalType.USER, principal_id)
        assert {entry.resource_id for entry in remaining} == {other_folder_id}
        untouched = acl_repo.list_for_principal(PrincipalType.USER, other_principal_id)
        assert len(untouched) == 1


def test_list_for_pairs_matches_only_the_given_resources(session: Session) -> None:
    folders = FolderRepository(session)
    matched = folders.create("Smlouvy")
    unmatched = folders.create("Faktury")
    group = GroupRepository(session).create("Klienti")
    repository = AclRepository(session)
    repository.upsert(
        resource_type=ResourceType.FOLDER,
        resource_id=matched.id,
        principal_type=PrincipalType.GROUP,
        principal_id=group.id,
        permission=Permission.READ,
    )
    repository.upsert(
        resource_type=ResourceType.FOLDER,
        resource_id=unmatched.id,
        principal_type=PrincipalType.GROUP,
        principal_id=group.id,
        permission=Permission.READ,
    )

    found = repository.list_for_pairs([(ResourceType.FOLDER, matched.id)])

    assert [e.resource_id for e in found] == [matched.id]
