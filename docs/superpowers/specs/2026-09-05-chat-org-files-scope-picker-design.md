# Chat-side org files scope picker

## The problem

`SourceChips` toggles `org_files` on or off as a whole namespace
(`source-scope-store.ts`) — there is no way to narrow a chat to a subset of
folders/files. Once spec 2 makes "everything I'm allowed to see" the
ceiling, this spec lets a user pick a smaller scope within that ceiling for
one conversation, and surfaces the deeply-nested-direct-grant case (spec 1's
additive ACL model) in a way that does not leak folder names the user has no
other access to (per the earlier design discussion: individually-shared
files get a breadcrumb, but only their own path, not a browsable parent).

## Scope

- Three new member-facing, capability-free read endpoints describing "what
  can I see" (not "what does everyone see" — that stays admin-only).
- A folder/file picker in the chat source panel, shown once `org_files` is
  toggled on, narrowing (never widening) what spec 2 already allows.
- The narrowed selection frozen onto the conversation the same way `scope`
  already is.

Out of scope: anything about granting access — this spec only ever narrows
within what the user already has.

## Design

### Member-facing read endpoints (new, no capability required)

Any authenticated user may call these; each answers strictly within their
own `accessible_org_folder_ids` / `directly_granted_document_ids` (spec 2).

- `GET /me/org-files/roots` → the user's own **virtual roots**: the
  topmost folders in their accessible set (a folder whose real parent is
  *not* in the set, because inheritance only flows down — see below).
  Each entry carries its real ancestor path as plain text for context (the
  same breadcrumb trade-off already accepted for individually-shared
  files, applied consistently here too: a name is shown, browsing further
  up is not offered).
- `GET /me/org-files/folders/{id}` → the real children (folders and files)
  of one accessible folder. No further filtering is needed below a
  virtual root — once a folder is in the accessible set, its whole subtree
  is, by construction of `accessible_org_folder_ids`.
- `GET /me/org-files/shared-documents` → the flat list from
  `directly_granted_document_ids`, each with its ancestor path as text, for
  the "shared directly with you" section.

**Why virtual roots, not the real tree from the true root.** Access is
granted on a folder and flows down, never up — a grant on `Litigation`
never implies anything about `Litigation`'s parent. A member with access to
`Litigation` therefore cannot browse from the true root down to it (every
folder above it may be one they have no grant on at all); `Litigation`
itself has to be presented as if it *were* a root, which is exactly what
`GET /me/org-files/roots` computes. The alternative — silently granting
read access to every ancestor folder's *name* just so navigation works —
was rejected the same way an unrestricted breadcrumb on inaccessible
ancestors was already rejected for individual files, for the same reason.

### `conversation.meta` gains a narrowing, not a replacement

```python
class ConversationCreate(BaseModel):
    scope: list[ScopeSource] | None = None
    org_files_folder_ids: list[UUID] | None = None
    org_files_document_ids: list[UUID] | None = None
    ...
```

`None` on either (the default — an FE with no picker, or a user who never
opens it) means "no narrowing, search the full ceiling", identical to
today's behaviour. A concrete list is **intersected** with the ceiling at
creation time, not trusted outright: `create_conversation()` filters both
lists down to what `accessible_org_folder_ids`/`directly_granted_document_ids`
actually allow for that user before freezing them into `meta`, the same way
a stale or tampered client selection can only ever narrow, never widen,
what search already enforces server-side.

`search()` (spec 2) gains this as one more optional intersection: when
`org_files_folder_ids`/`org_files_document_ids` are present on the
conversation, the ceiling sets computed in spec 2 are intersected with
them before the Qdrant filter is built; when absent, spec 2's behaviour is
unchanged.

### Frontend: `OrgFilesScopePicker`

Added to `features/sources/`, rendered under `SourceChips` once
`org_files` is toggled on — reuses the drill-down navigation pattern a
third time (after the admin group browser in the previous spec), this time
read-only-access-wise and checkbox-driven:

- A checkbox tree seeded from `/me/org-files/roots`, expanding into
  `/me/org-files/folders/{id}` on open. Checking a folder checks it and,
  by default, everything currently under it — consistent with what
  selecting it will actually search — but a user may then uncheck
  individual children, which only narrows *this conversation's* query and
  never touches anyone's access grants. An indeterminate state on a folder
  reflects "some but not all children selected", the standard tree-checkbox
  convention.
- A separate "Shared directly with you" flat section from
  `/me/org-files/shared-documents`, each row showing its breadcrumb text
  and its own checkbox, outside the tree (it may not be reachable through
  it at all).
- `useSourceScopeStore` (or a sibling store, `org-files-scope-store.ts`) adds
  the two id lists, cleared whenever `org_files` is toggled off, sent as
  `org_files_folder_ids`/`org_files_document_ids` on
  `POST /conversations`, exactly alongside today's `scope`.
- Locked once the conversation exists, the same way `scope` already is
  (`isLocked` in the existing store) — a frozen conversation cannot change
  what it searches mid-thread.

## Testing

`tests/api/test_me_org_files_api.py`:

- `/me/org-files/roots` returns a folder granted directly, and does not
  return its parent even when the parent has no grant of its own.
- A folder two levels below a grant appears correctly in
  `/me/org-files/folders/{id}` without needing its own grant.
- `/me/org-files/shared-documents` returns a document with no folder
  access at all, with a correct ancestor-name path.
- A user with no grants gets empty results from all three, not an error.

`tests/test_conversations.py`:

- `org_files_folder_ids` containing an id outside the caller's accessible
  set is silently dropped, not rejected — the conversation is created with
  whatever remained valid.

`tests/test_search.py` (extends spec 2's cases):

- A conversation frozen with a narrower `org_files_folder_ids` than the
  user's full ceiling only returns chunks from the narrower set, even
  though the ceiling would allow more.

Frontend `features/sources/tests/`: `OrgFilesScopePicker` — checking a
folder selects its already-loaded children; unchecking one child leaves the
folder indeterminate; the shared-documents section renders independently of
the tree; toggling `org_files` off clears both id lists.

## Documentation

`docs/superpowers/specs/2026-08-09-backend-api-fe-notes.md`: document the
three `/me/org-files/*` endpoints and the two new `ConversationCreate`
fields.
