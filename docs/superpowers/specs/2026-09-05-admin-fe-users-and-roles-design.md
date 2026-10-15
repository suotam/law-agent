# Admin frontend: users and roles

## The problem

The backend already exposes `/admin/users` (create, list) and, after this
spec's data-model prerequisite, `/roles` and `PATCH /admin/users/{id}`
— but nothing in `frontend/` renders any of it. `admin.files.tsx` is the only
admin screen today, gated by `AdminRoute`'s hardcoded `user.role !== "admin"`
check, which no longer describes anything once role is dynamic.

## Scope

- A frontend screen for user administration: list, create, change a user's
  role.
- A frontend screen for role administration: list, create, rename, toggle a
  role's capabilities, delete.
- Generalising the route guard from "is admin" to "has this capability" (or
  "is superuser", for the roles screen specifically).

Both screens are bundled in one spec because they are the same
capability-holder's job (`MANAGE_USERS`) and the same size of work; group/ACL
administration (a different capability, a materially bigger UI) is the next
spec. Out of scope here: anything about groups, folders, or ACL grants.

## Design

### `UserResponse` carries the caller's own authorization shape

`UserResponse` (`api/schemas.py`) changes from `role: UserRole` to a nested
role plus a flattened summary of what it grants:

```python
class RoleSummary(BaseModel):
    id: UUID
    name: str

class UserResponse(BaseModel):
    id: UUID
    email: str
    role: RoleSummary
    capabilities: list[RoleCapability]   # denormalised from role_capabilities
    is_superuser: bool
    created_at: datetime
```

This is the same endpoint shape for `/auth/me` and every row of
`/admin/users` — one response type serves "what can *I* do" (drives the FE
nav and route guards) and "list of accounts" (drives the admin table)
without a second lookup. `useAuth()`'s existing `staleTime: Infinity`
(`hooks/useAuth.ts:28`) is unchanged: a role or capability edited mid-session
does not reach that user's own screen until their next login, exactly as
today's comment already accepts ("the server's own 403 stays the real
authority — this only decides what is rendered", `AdminRoute.tsx:8`) —
consistent with spec 1's server-side check being what is actually
authoritative on every request regardless of what the client is showing.

### Route guard: `RequireCapability` replaces `AdminRoute`

```tsx
<RequireCapability capability="manage_users">
```

Same shape as today's `AdminRoute` (redirect to `/` while loading or
unauthorized, `Outlet` otherwise), parameterised by capability instead of
hardcoding `"admin"`. A second prop form, `<RequireCapability superuser>`,
gates the roles screen — role/capability administration stays superuser-only
end to end, matching spec 1's stance that it must not be grantable through
the capability system it configures.

`admin.files.tsx`'s existing guard swaps to
`<RequireCapability capability="manage_org_files_structure">` in the same
change, since `AdminRoute` is being removed, not left behind unused.

### New feature: `frontend/src/features/users/`

Mirrors `features/org-files/`'s shape:

- `api/`: `list-users.ts`, `create-user.ts`, `update-user-role.ts` (`PATCH
  /admin/users/{id}`), `query-keys.ts`.
- `components/UserTable.tsx`: email, role name, created at, and a role
  `<select>` per row wired to `update-user-role`.
- `components/CreateUserDialog.tsx`: email, password, role select — the role
  list comes from `features/roles`' own query (shared, not refetched here).
- `types.ts`: `RoleSummary`, extending the shared `UserResponse`.

### New feature: `frontend/src/features/roles/`

- `api/`: `list-roles.ts`, `create-role.ts`, `rename-role.ts`,
  `update-role-capabilities.ts` (`PUT .../capabilities`, sends the full
  set), `delete-role.ts`, `query-keys.ts`.
- `components/RoleTable.tsx`: name, superuser badge, capability chips,
  edit/delete actions.
- `components/CapabilityCheckboxes.tsx`: the three capabilities
  (`manage_users`, `manage_groups`, `manage_org_files_structure`) rendered as
  a fixed, hardcoded checkbox list — not fetched from an endpoint, since the
  set is fixed in backend code (spec 1) and the FE mirrors it the same way
  `ScopeSource`'s two values are already hardcoded in `source-scope-store.ts`
  rather than discovered from the API.
- Delete confirms and surfaces the backend's 409 (`RoleInUseError`) as an
  inline error rather than a toast, the same pattern
  `org-files/components/DeleteDialog.tsx` uses for `FolderNotEmptyError`.

### Navigation

The admin nav section (wherever `AdminRoute`'s single link lives today)
splits into per-capability links: "Users" only if `manage_users` (or
superuser), "Roles" only if superuser, "Org files" only if
`manage_org_files_structure` (or superuser) — a manager with only
`manage_groups` (next spec) sees none of these three and only the groups
link that spec adds.

## Testing

`frontend/src/app/middlewares/tests/`: `RequireCapability` — redirects while
loading, redirects a user lacking the capability, renders `Outlet` for one
who has it directly or via `is_superuser`.

`features/users/tests/`: table renders from a mocked list response; create
dialog posts and invalidates the list query; role-change select calls
`update-user-role` and reflects the new role optimistically or on
refetch — mirrors the existing MSW-based tests in
`features/org-files/tests/folder-actions.test.tsx`.

`features/roles/tests/`: capability checkboxes toggle and `PUT` the full
replacement set (not a diff); delete surfaces the 409 inline.

## Documentation

`docs/superpowers/specs/2026-08-09-backend-api-fe-notes.md`: add a Users and
Roles section describing the new `UserResponse` shape and the `/roles`
endpoints, for reference the same way the existing Org Files section serves
that feature.
