# Dynamic roles, groups and per-resource access control

## The problem

Today authorization is two flat, hardcoded roles (`UserRole.ADMIN` /
`UserRole.MEMBER`, `users/models.py`) baked into the JWT itself
(`TokenClaims.role`). A role only gates whole *management* endpoints
(`require_role` on `/admin` and the org files router) — it is all-or-nothing,
cannot be extended without a code change, and has no idea about individual
folders or documents. Retrieval is not filtered by it at all: any
authenticated member can search every indexed org file
(`docs/ARCHITECTURE.md`, "Open decisions").

This spec replaces that with a data model that supports:

- Admin-defined roles (system capabilities: who may manage users, groups, or
  the org files folder tree), not just the two built-in ones.
- Admin-defined groups (who can *see* which org files), independent of role.
- Per-folder and per-file access grants, inherited down the folder tree, with
  the ability to grant a group or a single user direct access to one deeply
  nested file without granting the whole path to it.

## Scope

This spec covers the data model and the admin HTTP API to manage it: roles,
capabilities, groups, group membership, and ACL grants. Out of scope, each
its own later spec:

- Wiring the resolved access set into `retrieval/search.py` (next spec).
- Any frontend (admin screens, the chat source picker).
- Non-org-files resources: `user_files` (conversation attachments) keep their
  existing ownership-based access unchanged — ACL only ever applies to
  `folders` and `documents` rows that belong to the `org_files` namespace.

## Data model

One new Alembic migration, `0005_access_control`.

### Roles and capabilities

```
roles              (id, name, is_superuser, created_at)
role_capabilities  (role_id → roles.id, capability)      -- composite PK
```

`capability` is a fixed, code-level enum (`RoleCapability` in
`access/models.py`) — `MANAGE_USERS`, `MANAGE_GROUPS`,
`MANAGE_ORG_FILES_STRUCTURE`. It is a plain `Text` column, not FK'd to a
table: the set of things the app can actually check is defined by what code
exists to check it, so a table of "possible capabilities" would only ever
mirror the enum. New capabilities are a code change (a new value the checked
dependency understands); which *roles* have which capabilities is the part
that is genuinely admin-configurable, and that lives in
`role_capabilities`.

`is_superuser` on `roles`, not a capability: a superuser role bypasses the
capability check entirely, so it does not need — and cannot forget — every
capability enumerated. Role and capability administration itself
(`/admin/roles/*`) is gated on `is_superuser` directly, never on a
capability. Letting a capability grant "manage roles" would let a
non-superuser role hand itself more capabilities than it started with; the
bootstrap must stay outside the thing it configures.

`users` gains `role_id` (FK → `roles.id`, `NOT NULL`) and loses its `role`
text column. The migration seeds two rows in `roles` — `Admin`
(`is_superuser=true`) and `Member` (`is_superuser=false`, no capabilities) —
and backfills every user's `role_id` from their old `role` string before
dropping the column. Behaviour for existing accounts is unchanged: today's
`admin` keeps every capability (via `is_superuser`), today's `member` keeps
none.

A user has exactly one role. Multiple roles per user is not needed here —
system capabilities are coarse and few; if a user needs several, that is a
sign a new role bundling both should exist, not that the user needs a second
row.

### Groups

```
groups         (id, name, created_at)
group_members  (group_id → groups.id, user_id → users.id)   -- composite PK
```

No capabilities, no `is_superuser` — a group is purely a named set of users
for the purpose of granting data access. Fully admin-creatable, no seeded
rows. A user can belong to any number of groups.

### Access grants

```
acl_entries (
  id,
  resource_type    text   -- 'folder' | 'document'
  resource_id      uuid   -- folders.id or documents.id
  principal_type   text   -- 'group' | 'user'
  principal_id     uuid   -- groups.id or users.id
  permission       text   -- 'read' | 'write'
  created_at
)
```

`resource_type`/`resource_id` and `principal_type`/`principal_id` are
deliberately not FK columns — a single FK can't point at two different
tables, and a `CHECK` re-pointing them is the same trade-off `documents`
already makes for "folder file vs. chat file" (`db/models.py:63`). A unique
index on the four identifying columns (`resource_type, resource_id,
principal_type, principal_id`) stops the same grant being written twice;
writing `write` over an existing `read` for the same principal/resource
*replaces* the row rather than adding a second one.

**No deny, no override — only union.** A resource with no `acl_entries` row
of its own simply inherits whatever its ancestors grant. A resource with its
own row(s) does not replace what it inherits — it adds to it. Granting a
single user direct `read` on one deeply nested document, with no grant
anywhere on its parent folders, is exactly this mechanism used at the
document level instead of the folder level: one more explicit grant, unioned
in like any other. There is no way to carve a single file back out of a
folder's grant — moving it to a folder that isn't shared with that group is
the only way to restrict it further, which keeps "who can see X" a single
question (walk the ancestor chain, collect grants) instead of two (grants,
then exceptions).

### Effective access resolution

`access/service.py`:

```python
def effective_permission(
    user_id: UUID, resource_type: ResourceType, resource_id: UUID
) -> Permission | None:
```

For a document, the resource chain is: the document itself, its folder, and
that folder's ancestors up to a root (`parent_id IS NULL`). For a folder,
it's the folder and its ancestors. The function loads every `acl_entries`
row whose `(resource_type, resource_id)` is in that chain, keeps the ones
whose principal is either `user_id` directly or one of the user's groups
(`group_members`), and returns the highest permission found (`write` >
`read`), or `None` if nothing matched — default deny.

A superuser role short-circuits this entirely at the call site (see
**Authorization** below) rather than inside the resolver: the resolver
answers "what does the ACL say", not "does this user need to ask it".

### Rollout

`acl_entries` starts empty. Every existing org file and folder becomes
invisible to every non-superuser account the moment this ships, until an
admin assigns groups to them — this is the intended behaviour (least
privilege by default), not a migration bug, but it means **granting the
existing org files tree to at least one group is a required deployment step
for this change**, not an optional cleanup. This should be called out
explicitly when this ships (a runbook note, or a one-off admin action before
the first login after deploy) — no code needs to do it automatically, since
this feature's entire premise is that the admin should choose.

## Authorization

`TokenClaims` narrows to `user_id` only — `role` is dropped from the JWT.
Capabilities can change (an admin edits a role's `role_capabilities`, or
reassigns a user's `role_id`) and should take effect on that user's very
next request, not after their token expires days later; keeping capability
data out of the token and re-reading `role_id → role_capabilities` from the
database on every check is what makes that true. This does cost a query per
protected request, in exchange for the whole point of making roles
admin-editable at runtime — trading a little of the existing stateless-JWT
purity (already an accepted MVP compromise per `docs/ARCHITECTURE.md`) for
roles that are actually dynamic.

`require_role` is replaced by `require_capability(capability: RoleCapability)`
in `api/auth/dependencies.py`, same factory shape as today: loads the
caller's role, passes if `role.is_superuser` or `capability` is in its
`role_capabilities`, else 403. `admin.py`'s user endpoints move to
`require_capability(MANAGE_USERS)`; `org_files.py`'s router-level dependency
moves to `require_capability(MANAGE_ORG_FILES_STRUCTURE)`. New endpoints
below use `require_capability(MANAGE_GROUPS)`, except role/capability
administration, which is superuser-only (see above).

## API

Not nested under `/admin` — that prefix (`admin.py`) predates capability-based
gating and today happens to mean "admin role" only because the two coincide.
Once `MANAGE_GROUPS` can sit on a non-superuser role (a "Manager" who is not
an admin), a path like `/admin/groups` would be actively misleading: the URL
would claim admin-only while a non-admin genuinely calls it. `org_files.py`
already sets the actual precedent — its routes are plain `/folders`,
`/folders/{id}/files`, gated entirely by the router-level dependency, not by
a URL segment. Roles, groups and ACL follow that precedent: `/roles`,
`/groups`, `/acl`, each gated by the dependency stated below. `/admin/users`
keeps its existing path unchanged (renaming a shipped endpoint is out of
scope here); the inconsistency between it and the new resources is accepted
rather than fixed retroactively.

**Roles** (superuser-only):
- `POST /roles` `{name}` → `RoleResponse`
- `GET /roles` → `list[RoleResponse]`
- `PATCH /roles/{id}` `{name?}`
- `PUT /roles/{id}/capabilities` `{capabilities: list[RoleCapability]}`
  — replaces the full set
- `DELETE /roles/{id}` — 409 (`RoleInUseError`) if any user still holds
  it, same pattern as `FolderNotEmptyError`

**Users** (`MANAGE_USERS`; existing endpoints, updated shape):
- `UserCreate`/`UserResponse` swap `role: UserRole` for `role_id: UUID`
  (`UserResponse` nests the role's `id` and `name`, not just the id, so a
  client can render it without a second lookup)
- `PATCH /admin/users/{id}` `{role_id}` — new, reassign a user's role

**Groups** (`MANAGE_GROUPS`):
- `POST /groups` `{name}` → `GroupResponse`
- `GET /groups` → `list[GroupResponse]`
- `PATCH /groups/{id}` `{name}`
- `DELETE /groups/{id}`
- `POST /groups/{id}/members` `{user_id}`
- `DELETE /groups/{id}/members/{user_id}`
- `GET /groups/{id}/members` → `list[UserResponse]`

**Access grants** (`MANAGE_GROUPS`):
- `POST /acl` `{resource_type, resource_id, principal_type,
  principal_id, permission}` → `AclEntryResponse`. Upserts on the four-column
  unique index (see above).
- `DELETE /acl/{id}`
- `GET /acl?resource_type=&resource_id=` → `list[AclEntryResponse]` —
  the *explicit* grants on exactly this resource (not the resolved effective
  set), for a "who has access to this one folder/file" panel.

No HTTP endpoint for `effective_permission` in this spec — it is a plain
function, consumed directly by the retrieval spec that follows and by
whatever later spec exposes an effective-access view in the frontend.

## Testing

`tests/test_access_service.py` — the resolver is the part worth the most
test weight:

- No grants anywhere on the chain → `None`.
- Grant on an ancestor folder via the user's group → inherited correctly at
  a child folder and at a document several levels down.
- Direct grant on a single document, with none on any ancestor → resolves
  from that one row alone.
- Two grants at different levels (`read` on the folder, `write` directly on
  one document) → the document resolves to `write`, siblings still resolve
  to `read`.
- `write` and `read` granted to the same principal/resource → the write
  wins.
- A user with no groups and no direct grant → `None`, even if their group
  membership changes elsewhere in the same test.

`tests/api/test_admin_roles_api.py`, `test_admin_groups_api.py`,
`test_admin_acl_api.py`:

- Non-superuser gets 403 on every `/admin/roles/*` route, including one that
  holds every other capability.
- Deleting a role in use → 409; deleting an unused one succeeds.
- `PUT .../capabilities` replaces rather than appends (write two different
  sets in sequence, assert the second wins).
- Duplicate `POST /admin/acl` for the same resource/principal updates the
  permission in place rather than erroring or duplicating.
- `require_capability` reads a fresh grant on the very next request after an
  admin edits `role_capabilities` mid-test (no caching layer to invalidate).

## Documentation

`docs/ARCHITECTURE.md`: replace the "Auth" bullet's description of the two
flat roles with the roles/capabilities/groups/ACL model above; update "Open
decisions" to drop "role-based retrieval filtering over org files" once the
follow-up retrieval spec lands (still open after this spec alone, since this
one only builds the model, not the filtering).
