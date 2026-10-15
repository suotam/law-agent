"""Who may see what: role lookups for auth, and the ACL resolver for
retrieval filtering.

Both re-read the database on every call rather than caching -- an admin
edit to ``role_capabilities`` or a new ``acl_entries`` row must take effect
on the very next request, not after some cache's TTL.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from law_agent.access.models import (
    AclEntry,
    InvalidAclGrantError,
    Permission,
    PrincipalType,
    ResourceType,
    Role,
    RoleCapability,
)
from law_agent.db import (
    AclRepository,
    DocumentRepository,
    FolderRepository,
    GroupRepository,
    RoleRepository,
    UserRepository,
    session_scope,
)

_PERMISSION_RANK = {Permission.READ: 0, Permission.WRITE: 1}


def role_for_user(user_id: UUID) -> Role | None:
    """The role currently assigned to ``user_id``, capabilities included."""
    with session_scope() as session:
        user = UserRepository(session).get(user_id)
        if user is None:
            return None
        return RoleRepository(session).get(user.role_id)


def effective_permission(
    user_id: UUID, resource_type: ResourceType, resource_id: UUID
) -> Permission | None:
    """The highest permission ``user_id`` holds on ``resource_id`` via any
    grant on it or any of its ancestors, through their own account or any
    group they belong to.

    No deny, no override -- only union: every matching grant on the whole
    chain is a candidate, and the highest one wins.

    Returns:
        ``None`` if nothing on the chain grants this user access -- default
        deny.
    """
    return effective_permissions(user_id, [(resource_type, resource_id)])[
        (resource_type, resource_id)
    ]


def effective_permissions(
    user_id: UUID, pairs: Sequence[tuple[ResourceType, UUID]]
) -> dict[tuple[ResourceType, UUID], Permission | None]:
    """Batched :func:`effective_permission`: one session, one entries query
    and one group lookup for the whole set.

    A folder listing used to pay this ancestor walk once per child row
    (N children × D ancestors, each with its own ACL and group queries) --
    listing N children must not cost N×D round trips.
    """
    unique_pairs = list(dict.fromkeys(pairs))
    if not unique_pairs:
        return {}
    with session_scope() as session:
        chains: dict[tuple[ResourceType, UUID], list[tuple[ResourceType, UUID]]] = {
            pair: _resource_chain(session, pair[0], pair[1]) for pair in unique_pairs
        }
        chain_pairs = {chain_pair for chain in chains.values() for chain_pair in chain}
        entries = AclRepository(session).list_for_pairs(list(chain_pairs))
        group_ids = GroupRepository(session).groups_for_user(user_id)

        applicable_by_pair: dict[tuple[ResourceType, UUID], list[Permission]] = {}
        for entry in entries:
            granted_to_caller = (
                entry.principal_type is PrincipalType.USER and entry.principal_id == user_id
            ) or (entry.principal_type is PrincipalType.GROUP and entry.principal_id in group_ids)
            if granted_to_caller:
                applicable_by_pair.setdefault((entry.resource_type, entry.resource_id), []).append(
                    entry.permission
                )

        return {
            pair: _highest(
                [
                    permission
                    for chain_pair in chains[pair]
                    for permission in applicable_by_pair.get(chain_pair, [])
                ]
            )
            for pair in unique_pairs
        }


def _highest(permissions: list[Permission]) -> Permission | None:
    """The strongest of the caller's grants on one chain; ``None`` (default
    deny) when there are none."""
    if not permissions:
        return None
    return max(permissions, key=lambda permission: _PERMISSION_RANK[permission])


def accessible_org_folder_ids(user_id: UUID) -> set[UUID]:
    """Every folder ``user_id`` may see: one with a direct grant to them or
    one of their groups, plus its whole subtree -- inheritance flows down.

    Re-reads the database on every call, same as :func:`effective_permission`
    and for the same reason. Unlike that one-row lookup, this walks the whole
    folder tree, so it is a per-question cost, not a per-login one; caching
    it (invalidated on group membership or ACL changes) is the natural next
    step if that cost ever needs it, not built here.
    """
    with session_scope() as session:
        group_ids = GroupRepository(session).groups_for_user(user_id)
        seeds = AclRepository(session).resource_ids_for_principals(
            ResourceType.FOLDER, user_id=user_id, group_ids=group_ids
        )
        return FolderRepository(session).subtree_ids(list(seeds))


def directly_granted_document_ids(user_id: UUID) -> set[UUID]:
    """Documents granted directly to ``user_id`` or one of their groups --
    reachable even when no ancestor folder is in
    :func:`accessible_org_folder_ids` at all."""
    with session_scope() as session:
        group_ids = GroupRepository(session).groups_for_user(user_id)
        return AclRepository(session).resource_ids_for_principals(
            ResourceType.DOCUMENT, user_id=user_id, group_ids=group_ids
        )


def visible_folder_ids(user_id: UUID) -> set[UUID]:
    """Retrievable folders plus every ancestor of a directly granted
    document -- the navigation ceiling for the file browser and chat scope
    picker. Strictly wider than :func:`accessible_org_folder_ids`
    (retrieval's ceiling): a path folder here never widens what
    :func:`retrieval.search.search` can reach -- keep the two resolvers
    distinct, that separation is load-bearing.
    """
    return folder_access_sets(user_id).visible_folders


@dataclass(frozen=True)
class FolderAccessSets:
    """The three resolver sets the browser-shaped views consume, resolved in
    one pass: callers needing more than one of them would otherwise re-run
    the same ACL queries per call (``folder_contents`` used to)."""

    retrievable_folders: set[UUID]
    granted_documents: set[UUID]
    visible_folders: set[UUID]


def folder_access_sets(user_id: UUID) -> FolderAccessSets:
    """Retriever ceiling, direct document grants and the navigation ceiling,
    from one pass over the ACL resolvers."""
    retrievable = accessible_org_folder_ids(user_id)
    granted_documents = directly_granted_document_ids(user_id)
    with session_scope() as session:
        folder_repo = FolderRepository(session)
        document_repo = DocumentRepository(session)
        ancestors: set[UUID] = set()
        for document_id in granted_documents:
            document = document_repo.get(document_id)
            if document is None or document.folder_id is None:
                continue
            ancestors.update(folder_repo.ancestor_chain(document.folder_id))
    return FolderAccessSets(
        retrievable_folders=retrievable,
        granted_documents=granted_documents,
        visible_folders=retrievable | ancestors,
    )


def has_full_org_files_access(user_id: UUID) -> bool:
    """``True`` for a superuser or a role holding
    ``MANAGE_ORG_FILES_STRUCTURE`` -- the capability now means full org-files
    access (bypass every ACL resolver), not just "may edit the tree"."""
    role = role_for_user(user_id)
    if role is None:
        return False
    return role.is_superuser or RoleCapability.MANAGE_ORG_FILES_STRUCTURE in role.capabilities


def inherited_acl_entries(resource_type: ResourceType, resource_id: UUID) -> list[AclEntry]:
    """Grants ``resource_id`` receives from an ancestor folder -- the same
    chain :func:`effective_permission` walks, minus the resource's own node.

    Used by the Share panel to show "inherited" context separately from a
    resource's own explicit grants, so an admin can tell "no one can see
    this" apart from "everyone in the parent folder's group already can".
    """
    with session_scope() as session:
        chain = _resource_chain(session, resource_type, resource_id)
        ancestors = [pair for pair in chain if pair != (resource_type, resource_id)]
        return AclRepository(session).list_for_pairs(ancestors)


def folders_with_nested_grant(principal_type: PrincipalType, principal_id: UUID) -> set[UUID]:
    """Folders that hold no grant of their own for this principal, but
    contain one somewhere deeper in their subtree.

    The principal-centric access browser already marks a folder's own grant,
    and a folder with no own grant that inherits one from an ancestor -- this
    is the third state: nothing here, nothing inherited, but still worth
    descending into. A folder that already has its own grant is excluded,
    since that state is shown some other way already.
    """
    with session_scope() as session:
        entries = AclRepository(session).list_for_principal(principal_type, principal_id)
        folder_repo = FolderRepository(session)
        document_repo = DocumentRepository(session)
        contributing: set[UUID] = set()
        for entry in entries:
            if entry.resource_type is ResourceType.FOLDER:
                # Every proper ancestor of a granted folder contains it --
                # the folder's own id (chain[0]) is excluded below instead.
                contributing.update(folder_repo.ancestor_chain(entry.resource_id)[1:])
            else:
                document = document_repo.get(entry.resource_id)
                if document is not None and document.folder_id is not None:
                    contributing.update(folder_repo.ancestor_chain(document.folder_id))
        own_folder_ids = {
            entry.resource_id for entry in entries if entry.resource_type is ResourceType.FOLDER
        }
        return contributing - own_folder_ids


def upsert_acl_entry(
    *,
    resource_type: ResourceType,
    resource_id: UUID,
    principal_type: PrincipalType,
    principal_id: UUID,
    permission: Permission,
) -> AclEntry:
    """Create or replace one grant. Documents only ever support ``read``.

    Setting a folder grant first prunes that principal's own direct grants
    on the folder's whole subtree (folders and documents) -- a folder grant
    replaces per-file exceptions, it does not layer on top of them.
    """
    if resource_type is ResourceType.DOCUMENT and permission is Permission.WRITE:
        msg = "documents only support 'read' grants; write belongs on the containing folder"
        raise InvalidAclGrantError(msg)
    with session_scope() as session:
        if resource_type is ResourceType.FOLDER:
            _prune_principal_subtree(session, principal_type, principal_id, resource_id)
        entry = AclRepository(session).upsert(
            resource_type=resource_type,
            resource_id=resource_id,
            principal_type=principal_type,
            principal_id=principal_id,
            permission=permission,
        )
        session.commit()
        return entry


def delete_acl_entry(acl_id: UUID) -> None:
    """Delete one grant. Removing a folder grant also prunes that principal's
    direct grants on the folder's whole subtree -- same rule as setting one."""
    with session_scope() as session:
        acl_repo = AclRepository(session)
        entry = acl_repo.get(acl_id)
        if entry is None:
            return
        acl_repo.delete(acl_id)
        if entry.resource_type is ResourceType.FOLDER:
            _prune_principal_subtree(
                session, entry.principal_type, entry.principal_id, entry.resource_id
            )
        session.commit()


def delete_folder_cascading(folder_id: UUID) -> None:
    """Delete a folder and every ACL row on it and its (now-empty) subtree.

    ``FolderRepository.delete`` still raises ``FolderNotEmptyError`` for a
    non-empty folder -- deletion succeeds only once children are already
    gone, so by the time a folder is actually removed its subtree is just
    itself. Both steps sit in one ``session_scope()``, so a raised
    ``FolderNotEmptyError`` rolls back the whole thing, touching no ACL row.
    """
    with session_scope() as session:
        folder_ids = FolderRepository(session).subtree_ids([folder_id])
        FolderRepository(session).delete(folder_id)
        AclRepository(session).delete_for_resources(folder_ids=folder_ids, document_ids=set())
        session.commit()


def _prune_principal_subtree(
    session: Session, principal_type: PrincipalType, principal_id: UUID, folder_id: UUID
) -> None:
    """Prune ``principal_id``'s grants strictly inside ``folder_id``.

    Documents directly in ``folder_id`` are included -- a folder grant
    supersedes exceptions on the files it contains. Descendant *folders* are
    pruned too, but ``folder_id`` itself is excluded: its own row is the one
    the caller is upserting (or has just deleted) in place, and
    ``subtree_ids`` returns the seed folder along with its descendants, so
    including it here would delete that row out from under an in-place
    upsert instead of updating it.
    """
    subtree = FolderRepository(session).subtree_ids([folder_id])
    document_ids = DocumentRepository(session).ids_in_folders(list(subtree))
    descendant_folder_ids = subtree - {folder_id}
    AclRepository(session).delete_for_principal_on_resources(
        principal_type, principal_id, folder_ids=descendant_folder_ids, document_ids=document_ids
    )


def _resource_chain(
    session: Session, resource_type: ResourceType, resource_id: UUID
) -> list[tuple[ResourceType, UUID]]:
    """The resource itself (if a document) plus its folder chain up to a root."""
    if resource_type is ResourceType.DOCUMENT:
        document = DocumentRepository(session).get(resource_id)
        if document is None or document.folder_id is None:
            return []
        folder_ids = FolderRepository(session).ancestor_chain(document.folder_id)
        if not folder_ids:
            return []
        return [(ResourceType.DOCUMENT, resource_id)] + [
            (ResourceType.FOLDER, folder_id) for folder_id in folder_ids
        ]

    folder_ids = FolderRepository(session).ancestor_chain(resource_id)
    return [(ResourceType.FOLDER, folder_id) for folder_id in folder_ids]
