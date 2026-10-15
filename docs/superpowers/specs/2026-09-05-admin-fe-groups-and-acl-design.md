# Admin frontend: groups and access grants

## The problem

Spec 1 gives groups and ACL grants an API; nothing lets an admin actually use
it. Two different jobs need two different views, per the earlier design
discussion: bulk-assigning a group's access across many folders at once
(group-centric), and checking or fixing who can see one specific
folder/file (resource-centric). Neither exists.

## Scope

- Group administration: list, create, rename, delete, membership.
- The group-centric view: open a group, browse the folder tree, toggle
  access per folder/file.
- The resource-centric view: a "Share" panel on an existing folder/file row
  in `admin.files.tsx`, listing and editing who has access to that one item.
- Two small additions to spec 1's API surface, needed by these screens (see
  below) — not a data model change, just read/write endpoints shaped for
  this UI.

Out of scope: the chat-side "which of what I'm allowed to see do I want to
search" picker (next spec) — this is entirely the admin's side.

## Design

### Two API additions to spec 1's surface

- `GET /groups/{id}/acl` → `list[AclEntryResponse]` — every grant held
  by one group, across every folder and file, in one call. The
  group-centric browser needs to mark, while navigating, which rows already
  have a grant; asking `GET /acl?resource_type=&resource_id=` once per
  visited row would be an N+1 the group already knows the answer to as a
  whole.
- `GET /acl/effective?resource_type=&resource_id=` →
  `{own: list[AclEntryResponse], inherited: list[AclEntryResponse]}` — for
  the Share panel: `own` is this resource's explicit grants (editable),
  `inherited` is what it receives from ancestor folders (read-only context,
  computed by walking the same ancestor chain `effective_permission`
  already walks, but returning the grants themselves rather than one
  resolved permission). Without this split, an admin opening a file with no
  grants of its own would see an empty panel and have no way to tell "no one
  can see this" apart from "everyone in the parent folder's group already
  can" — leading them to add duplicate grants.

### Group administration: `frontend/src/features/groups/`

Same shape as `features/users/` (spec 3): `api/` (list, create, rename,
delete, list-members, add-member, remove-member, query-keys),
`components/GroupTable.tsx`, `CreateGroupDialog.tsx`,
`MembershipEditor.tsx` (a user multi-select scoped to one group, reusing
whatever user-search input `features/users` already built for role
assignment rather than a second implementation).

### Group-centric browser: reuses `FileBrowser`'s navigation, not its actions

`FileBrowser` (`features/org-files/components/FileBrowser.tsx`) already does
exactly the navigation this needs — `useFolderPath`, `Breadcrumb`,
`ItemList` drilling one folder level at a time. A new
`GroupAccessBrowser.tsx` (`features/groups/components/`) reuses those three
directly, parameterised by `groupId`, and swaps `renderFolderActions`/
`renderFileActions` for a single access toggle per row instead of
rename/delete/download: a checkbox or switch, checked when that row's id
appears in the group's `GET /groups/{id}/acl` result (fetched once for
the whole tree, kept in a `Set<string>` for O(1) row lookup while
navigating), read/write chosen via a small dropdown next to it. Toggling
posts to `POST /acl` / `DELETE /acl/{id}` (spec 1) exactly as
the resource-centric panel does below — the two views write through the
same endpoints, they only differ in which axis (principal vs. resource) is
fixed while browsing.

A row with an *inherited* grant (visible via the same
`GET /groups/{id}/acl` set, since an inherited folder's own explicit
row is what's inherited from) shows as checked-and-disabled with a short
label ("via <ancestor folder name>") rather than a plain checked box — this
prevents an admin from thinking they need to also check a child folder that
is already covered, and from unchecking it here with no visible effect
(unchecking an inherited row does nothing, since there is no grant *here*
to remove — see spec 1's no-deny decision).

### Resource-centric panel: a new action on existing rows

`FileBrowser`'s `renderFolderActions`/`renderFileActions`
(`FileBrowser.tsx:91-128`) gain one more `RowAction`, "Share", opening
`SharePanel.tsx` (`features/groups/components/`, despite living next to the
group feature it is invoked from org-files' rows — cross-feature, so it
takes `resourceType`/`resourceId` as props rather than importing anything
folder-specific). Fetches `GET /acl/effective`, renders `inherited` as
a read-only list ("Litigation (folder) grants: Paralegals — read"), `own`
as an editable list with remove buttons, and an "Add" row: a
principal-type toggle (group/user), a search-select fed by
`features/groups`' and `features/users`' existing list queries, a
permission select, `POST /acl`.

### Navigation

The "Groups" admin nav link (added to the split introduced in spec 3)
appears for `manage_groups` or superuser.

## Testing

`features/groups/tests/`:

- `GroupTable`/`CreateGroupDialog`/`MembershipEditor`: same MSW-mocked CRUD
  pattern as `features/users/tests/`.
- `GroupAccessBrowser`: a folder with a direct grant renders checked; a
  child folder with no grant of its own but an ancestor grant renders
  checked-and-disabled with the ancestor's name; toggling an unchecked row
  posts the expected `POST /acl` body; toggling a checked, *own*
  (non-inherited) row deletes it.
- `SharePanel`: renders `own` and `inherited` in visibly distinct sections;
  removing an `own` entry calls `DELETE`; adding one via the search-select
  calls `POST` with the chosen principal/permission; an `inherited` entry
  has no remove control.

## Documentation

`docs/superpowers/specs/2026-08-09-backend-api-fe-notes.md`: add the two new
endpoints (`GET /groups/{id}/acl`, `GET /acl/effective`) and the
Groups feature, for the same reference purpose as the existing sections.
