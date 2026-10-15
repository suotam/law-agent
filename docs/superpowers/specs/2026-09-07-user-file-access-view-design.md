# Per-user file access view, and splitting the ACL capability gate

## The problem

The group-centric access browser (`GroupAccessBrowser`) lets an admin open a
group and see/edit every folder/file it can reach. There is no equivalent for
a single user: to answer "what does this one person have access to", an
admin has to guess which group(s) grant it or hunt resource-by-resource
through the Share panel. The user list has no path into access management at
all.

Separately, while designing the above, a real bug surfaced: the entire ACL
API (`acl.py`) and the frontend's "Share" action are gated on `manage_groups`
only. A caller who holds `manage_users` (and file-structure write) but not
`manage_groups` cannot open the Share panel at all — even though nothing
stops them from granting access to a *user* principal, which conceptually has
nothing to do with group management. Conversely, the Share panel always
offers "share with a user" regardless of whether the caller actually holds
`manage_users`. The two axes (grant-to-group vs. grant-to-user) are currently
bundled under one capability.

## Scope

- A per-user access browser, reachable from the user list, mirroring the
  existing per-group one.
- A page heading naming the group/user on both the group and the (new) user
  access-browser pages — today neither page shows whose access is being
  edited.
- Splitting ACL capability checks by principal type (`manage_groups` for
  group grants, `manage_users` for user grants) in both the backend and the
  Share panel, so each capability independently unlocks its own half of ACL
  management.

Out of scope: any change to how retrieval resolves effective permissions,
the group-centric browser's own behavior, or introducing a new capability —
the fix reuses the two capabilities that already exist.

## Design

### Backend: split the ACL capability gate by principal type

`acl.py`'s router currently depends on `require_capability(MANAGE_GROUPS)`
for every route. Change it to a new `require_any_capability(MANAGE_GROUPS,
MANAGE_USERS)` dependency (added to `api/auth/dependencies.py`, same factory
shape as `require_capability` but passing if the caller holds *any* of the
given capabilities) — this is the floor: you need at least one ACL-adjacent
capability to reach the router at all.

`GET /acl` and `GET /acl/effective` stop there: both return a mix of group
and user grants, so viewing only needs the floor check.

`POST /acl` and `DELETE /acl/{id}` add a fine-grained check on top, in the
handler, based on the *principal type actually being touched*:

- `POST /acl`: check `payload.principal_type` before calling
  `upsert_acl_entry` — `MANAGE_GROUPS` required for a `group` grant,
  `MANAGE_USERS` for a `user` grant.
- `DELETE /acl/{acl_id}`: look the entry up first (`AclRepository(session)
  .get(acl_id)`) to learn its `principal_type`, apply the same check, then
  call `delete_acl_entry`. A missing entry is left as today's no-op delete —
  nothing to check.

A small helper, `_require_principal_capability(user: CurrentUser,
principal_type: PrincipalType) -> None`, maps `GROUP → MANAGE_GROUPS` /
`USER → MANAGE_USERS`, re-reads the caller's role the same way
`require_capability` does, and raises the router's existing 403 on mismatch.

`GET /groups/{group_id}/acl` (in `groups.py`) is unaffected — that whole
router stays `MANAGE_GROUPS`-gated, and it only ever returns group-principal
entries.

### Backend: `GET /users/{user_id}/acl`

Mirrors `GET /groups/{group_id}/acl` exactly (`AclRepository
.list_for_principal(PrincipalType.USER, user_id)`), but cannot live in
`users.py` — that router is blanket-gated on `MANAGE_USERS` for account
administration, which happens to be the right capability here, but the
association should be explicit and self-contained rather than inherited
from an unrelated router's default. It lives in a new small router in
`acl.py` (prefix `/users`, `dependencies=[Depends(require_capability
(MANAGE_USERS))]`), the same two-routers-one-module shape `auth.py` already
uses for `router` + `me_router`. Registered in `app.py` as
`app.include_router(acl.user_acl_router)`.

### Frontend: capability-aware Share panel

`FileBrowser.tsx`'s `canShare` splits into `canShareGroups` (`manage_groups`)
and `canShareUsers` (`manage_users`); the "Share" row action is offered when
either is true.

`SharePanel.tsx` reads both flags from `useAuth()` directly (no new props):

- The principal-type radio only offers "group" when `canShareGroups`, only
  "user" when `canShareUsers`. `principalType` initializes to whichever one
  is available (group preferred if both are).
- Each row in the "own" (editable) grants list gets a remove button only if
  the caller holds the capability matching that entry's `principal_type` —
  a caller with only `manage_users` sees existing group grants (read-only,
  no remove control) alongside their own editable user grants, same
  transparency the "inherited" section already gives for read-only context.

The panel is never opened by a caller with neither capability (the row
action itself is gated the same way `RequireCapability` gates routes: not
reachable, not rendered), so there is no "both hidden" state to design for.

### Frontend: per-user access browser

Generalizes `GroupAccessBrowser` into a principal-agnostic `AccessBrowser`
(same file, renamed) taking `principalType`, `principalId`, `principalName`,
and the ACL query result as props, instead of calling `useGroupAcl`
internally — the tree/toggle/inheritance logic (folder walk, cycle-permission
button, "via `<ancestor>`" inherited label) is unchanged, only the data
source and the `principal_type` written on `POST /acl` move to props. Both
call sites now render a heading with `principalName` above the browser,
which is also how the group page picks up the name it was missing.

- `features/users/api/list-user-acl.ts`: new `useUserAcl(userId)`, same
  shape as `useGroupAcl`, hitting `GET /users/{id}/acl`.
- `frontend/src/app/routes/admin.users.$id.access.tsx`: new page, resolves
  the user's name via the already-loaded `useUsers()` list (same pattern
  `SharePanel`'s `principalLabel` uses), passes `principalType="user"` down.
- `admin.groups.$id.access.tsx`: passes `principalType="group"` and its
  resolved name down; `useGroupAcl` is now called at this page level
  instead of inside the browser component.
- `router.tsx`: new route `/admin/users/:id/access`, nested under
  `RequireCapability capability="manage_users"` → `RequireCapability
  capability="manage_org_files_structure"` (both needed, mirroring why the
  group route needs `manage_groups` + `manage_org_files_structure`: seeing
  the full org tree to grant against requires structure access, on top of
  whichever principal-management capability applies).
- `UserTable.tsx`: adds a `FolderLock` icon button per row (same icon
  `GroupTable` uses), linking to `/admin/users/{id}/access`, rendered only
  when the caller has `manage_users` **and** `manage_org_files_structure` —
  the same "not linked, not reachable" rule `RequireCapability` documents.

### i18n

The existing `groups.access*` keys (`accessLoadError`, `accessInheritedLabel`,
`accessToggleLabel`, `accessLevel.*`, `accessLegendTitle`,
`accessCascadeWarning`) are already principal-agnostic text — only their
namespace assumed a group. Move them to a new `access.*` namespace shared by
both pages. `groups.accessLabel` ("Přístup skupiny {{name}}", the row-icon
tooltip) stays put; add a `users.accessLabel` ("Přístup uživatele {{name}}")
equivalent for the new `UserTable` icon. New page headings use the moved
`access.*` namespace plus the passed-in `principalName`.

## Testing

- `acl.py`: a caller with only `manage_users` can `POST`/`DELETE` a `user`
  grant but gets 403 on a `group` grant, and vice versa for
  `manage_groups`; a caller with either can `GET`/`GET /effective`; a caller
  with neither gets 403 everywhere in the router (the existing case,
  unchanged in outcome).
- `GET /users/{id}/acl`: requires `manage_users`; 403 without it; returns the
  same grants `GET /acl?resource_type=&resource_id=` would show for that
  principal.
- `SharePanel`: with only `manage_groups`, the "user" radio is absent and
  existing user grants show without a remove button; with only
  `manage_users`, the reverse; with both, unchanged from today.
- `AccessBrowser` (renamed from `GroupAccessBrowser`): existing
  `GroupAccessBrowser.test.tsx` cases still pass against a `principalType="group"`
  instance; new cases mirror them for `principalType="user"` (toggling posts
  `principal_type: "user"`, inherited-row display is identical).
- `UserTable`: the access icon renders only for a caller holding both
  `manage_users` and `manage_org_files_structure`.

## Documentation

`docs/superpowers/specs/2026-08-09-backend-api-fe-notes.md`: add
`GET /users/{id}/acl`, the capability split on `POST /acl`/`DELETE
/acl/{id}`, and the per-user access browser feature, for the same reference
purpose as the existing sections.

`docs/ARCHITECTURE.md`: the ACL bullet under "Authorization & accounts"
currently reads "ACL grants ... gate org files" without naming which
capability administers them — add a line noting that granting access is
split by principal type (`manage_groups` for group grants, `manage_users`
for user grants), both of which additionally require full org-files access
(`manage_org_files_structure` or superuser) to browse the tree being granted
against.
