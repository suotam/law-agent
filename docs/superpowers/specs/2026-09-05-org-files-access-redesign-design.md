# Org files access redesign: read/write on folders, path-to-root, one file browser

## The problem

The ACL model shipped in `2026-09-05-access-control-data-model-design.md` works,
but using it exposed four rough edges:

1. **`WRITE` is dead weight.** It exists as an enum (`access/models.py:65`) and
   ranks above `read` (`access/service.py:26`), but nothing enforces it:
   retrieval gates on *any* grant, and every mutating endpoint (upload, delete,
   move) is gated by the `MANAGE_ORG_FILES_STRUCTURE` capability, not the ACL.
   The UI offers "write" on files and folders without it meaning anything.
2. **Direct grants leave invisible residue.** A direct grant on one document is
   independent of folder grants (union-only). Revoke a group's access to a
   folder and the file it was granted directly stays accessible — correct by the
   union design, but nothing surfaces *why*, and the permission offered on a
   file ("write") made the residue look like a bug.
3. **A deeply shared file is unreachable by browsing.** A direct grant on a
   nested document surfaces only as a text breadcrumb in a separate "shared
   directly with you" section (`access/member_view.py:list_shared_documents`);
   the ancestors are not clickable, so the user cannot navigate to the file
   through the tree.
4. **The chat scope picker under-matches.** Checking an unopened folder does
   not pull in documents inside its unopened subfolders (`docs/ARCHITECTURE.md`,
   open decisions), so the frozen narrowing matches less than the UI implies.

This spec redesigns the permission semantics, the navigation model, and
unifies the file UI. Primary concern is the member-facing UX; the admin views
follow the same model.

## Decisions

### 1. Permissions: read/write on folders only; documents are read-only

| Resource | Permission | Meaning |
| --- | --- | --- |
| folder | `read` | see the folder's contents (subject to filtered traversal below) |
| folder | `write` | upload documents into it, delete documents in it |
| document | `read` only | view metadata, download the original file |

- `write` on a folder does **not** include structure operations: creating,
  renaming, moving or deleting folders stays behind
  `MANAGE_ORG_FILES_STRUCTURE`. A member with `write` manages *content* only.
- A direct document grant exists in one flavour: `read`. `POST /acl` rejects
  `permission=write` with `resource_type=document` (422).
- `write` implies `read` (unchanged: `effective_permission` still returns the
  highest grant on the chain, and rank `{READ: 0, WRITE: 1}` already encodes
  that).
- One new Alembic migration (next revision after `0005_access_control`):
  downgrade every existing `acl_entries` row with
  `resource_type='document' AND permission='write'` to `read`. No schema
  change — the column stays a free `Text`; the constraint is code-level.

### 2. `MANAGE_ORG_FILES_STRUCTURE` = full org-files access

The capability stops being "may edit the tree" and becomes "may do anything
with org files": see the whole tree regardless of ACL, upload, delete, manage
folders, and retrieve without the ACL filter. This mirrors the existing
superuser bypass at the same call sites (`retrieval/search.py:search()`,
`access/member_view.py`, `conversations/service.py:_narrow_org_files_selection`)
— a capability check, not a role check, resolved per request like every other
capability check. The superuser boundary is unchanged: it still bypasses
*everything* (users, roles), the capability only covers org files.

A folder's or document's response therefore carries the caller's
`effective_permission` (plus `is_structure_manager`, i.e. capability held), so
the UI renders actions without a second lookup.

### 3. Cascading prune: a folder grant replaces per-file exceptions

Setting **or removing** a folder permission for a principal deletes that
principal's direct grant rows on the folder's entire subtree; setting then
upserts the new row.

- Rule, in one sentence a UI can quote: **"Setting or removing access on a
  folder clears this recipient's individual grants inside it."** This covers
  the original complaint — revoking a folder's access wholesale also clears
  the per-file residue.
- Trigger: `POST /acl` with `resource_type='folder'`, and `DELETE /acl/{id}`
  when the deleted entry's resource is a folder. Implementation:
  `AclRepository` deletes entries whose principal matches and whose resource
  is any folder or document in the folder's subtree (recursive CTE
  `subtree_ids` already exists in `db/repositories.py`); the upsert path then
  writes the new row.
- A direct document grant outside any touched folder is unaffected — the prune
  is scoped to the subtree of the folder being changed.
- Consequence accepted and documented in the UI (a confirm note on the Share
  panel when granting on a folder): the operation is destructive and
  irreversible — restoring individual grants afterwards means recreating them
  by hand. Composing "read the folder, write one subfolder" therefore has a
  required order: grant the folder first, then the subfolder.
- **Orphan cleanup:** deleting a folder or document deletes its `acl_entries`
  rows (and, for a folder, the rows of every resource in its subtree). The
  non-FK design (`db/models.py:231`) means this must be explicit application
  code, same trade-off the tables already make.

### 4. Navigation: path-to-root with filtered traversal

Two distinct resolver sets, computed in `access/service.py`:

- **Retrievable folders** — unchanged semantics: subtrees of folders with a
  grant, plus directly granted documents (`accessible_org_folder_ids`,
  `directly_granted_document_ids`). This is the retrieval ceiling; `search()`
  is untouched by this spec.
- **Visible folders** — the retrievable set **plus** every ancestor (path to
  the root) of every directly granted document. New resolver, used only by
  `member_view` and the scope picker.

A folder is visible if it is retrievable or on the path to a granted
document. A folder on the path (not itself retrievable) is *traversable but
filtered*: its listing shows only children the caller can see. Child
visibility follows the same two-set logic:

- subfolders: shown iff they are in the visible set;
- documents: all of them if the folder itself is retrievable (the folder
  grant covers its whole subtree); only the directly granted ones if the
  folder is merely on a path.

Siblings' contents are never
exposed; the information leak is limited to the names of folders on the
path, which is accepted (in a law firm's tree the folder names — "Smlouvy /
2025" — are not the secret; the contents are).

`access/member_view.py` is reworked accordingly:

- `list_roots` returns the topmost **visible** folders (visible folders whose
  parent is not visible) — the virtual-roots concept survives, but now the
  tree contains everything, including individually shared files.
- `folder_contents` filters children by the visible set instead of returning
  raw children (correct today only because a retrievable folder's whole
  subtree is retrievable; with path folders in the set that is no longer true).
- `list_shared_documents` and `SharedDocument`/`ancestor_path` are deleted —
  the picker's "shared directly with you" section disappears because the
  documents now appear inside their filtered path.
- `visible_folder_ids(user_id)` is the new member_view-facing resolver;
  retrievable stays retrieval's. Keeping them separate is the load-bearing
  rule of this section: **visible ≠ retrievable** — a path folder never
  widens what `search()` can reach.

### 5. One file browser for everyone

One UI surface replaces "admin-only FileBrowser + member scope picker" as the
place to *work with* org files. The chat scope picker remains, but only as a
selection context (see below).

- The tree's roots are the caller's topmost visible folders (a capability
  holder sees the whole real tree, roots included).
- Actions per node follow the node's `effective_permission` sent by the
  server: `read` → preview metadata / download original; folder `write` →
  upload documents, delete documents; capability → structure management
  (create/rename/move/delete folders) on top.
- The admin `frontend/src/features/org-files/` FileBrowser and the new member
  browser converge into one component driven by `/me/org-files/*` responses;
  the capability-gated `/folders`, `/org-files/*` admin endpoints stay for
  structure operations only.

New/changed member endpoints (`api/routers/me_org_files.py`, capability-free
router, every route gated by the caller's own resolved access):

- `GET /me/org-files/roots` — reworked (visible roots, no `ancestor_path`).
- `GET /me/org-files/folders/{id}` — filtered contents + per-node permission.
- `POST /me/org-files/folders/{id}/documents` — member upload; requires
  `effective_permission == write` on the folder, else 403 (file size/type
  limits shared with the admin upload path).
- `DELETE /me/org-files/documents/{id}` — requires `write` on the document's
  containing folder.
- `GET /me/org-files/documents/{id}/download` — requires `read` on the
  document (directly granted, or inside a retrievable folder). Reading the
  stored blob via `storage/blobs.py`; no re-indexing side effects.

### 6. Chat scope picker semantics

- **A checked folder means its whole retrievable subtree.** At conversation
  creation (`_narrow_org_files_selection`) the selected folder ids are
  expanded via `subtree_ids` before intersecting with the retrievable ceiling,
  and `search()` re-expands the same way — an unopened folder now contributes
  its unopened subfolders' documents, fixing the under-match bug.
- Children of a checked folder render checked-and-disabled: selecting files
  inside an already-selected folder is a no-op by definition (union of the
  subtree already includes them), and the UI stops implying otherwise.
- Selecting a path-only folder (visible but not retrievable) selects only the
  retrievable content below it — the granted documents on paths through it.
  The UI communicates this by rendering such a folder's non-accessible
  children as absent, exactly as the file browser does.
- Narrowing stays frozen per conversation and can only ever narrow the ACL
  ceiling (unchanged).

### 7. Grant management UI

- Share panel (`frontend/src/features/groups/components/SharePanel.tsx`) keeps
  the `own` vs `inherited` split and gains the cascade confirm note (Decision
  3). Document rows offer `read` only.
- GroupAccessBrowser (`frontend/src/features/groups/components/`
  `GroupAccessBrowser.tsx`) gets the same rules and, importantly, shows when a
  folder's grant shadows deeper direct grants (the cascade deletes them —
  state it before it happens, not after).

## Out of scope / deferred

- Caching the folder-set resolvers (explicitly flagged as "natural next step,
  not built here" in the original spec; unchanged).
- Audit log of ACL changes.
- Member self-sharing (a member with `write` granting access further) —
  sharing stays `MANAGE_GROUPS`-only; revisit on a real request.
- Inline document preview (PDF rendering) — download only for now.
- Persistent `user_files` namespace (existing roadmap item).

## Testing

`tests/test_access_service.py` (or its successor):

- Document grant with `write` is downgraded to `read` by the migration.
- `POST /acl` on a folder prunes the same principal's direct grants on the
  subtree's folders *and* documents; other principals' grants survive.
- Deleting an ACL entry does not cascade.
- `visible_folder_ids` includes path ancestors of a directly granted document;
  `accessible_org_folder_ids` (retrievable) does not.
- A capability holder resolves to full access without any grant rows.

API tests:

- `POST /acl` with `write` on a document → 422.
- Member upload into a `read` folder → 403; into a `write` folder → 201, and
  the document is retrievable by that user's `search()`.
- Member delete of a document in a `write` folder → 204; in a `read` folder →
  403.
- Member download: direct grant on a nested doc → 200; no grant → 404 (no
  existence confirmation).
- `GET /me/org-files/folders/{id}` on a path folder returns only the accessible
  children (no siblings of the granted document).
- Folder deletion removes ACL rows of the whole subtree (no orphans).

Picker/narrowing:

- Creating a conversation with an unopened checked folder matches documents
  from its unopened subfolders in `search()` (the under-match regression test).
- A tampered conversation narrowing still cannot widen the ceiling.

## Documentation

`docs/ARCHITECTURE.md`:

- "Authorization & accounts": add the read/write-on-folders semantics, the
  capability-equals-full-access rule, path-to-root navigation, and the
  visible-vs-retrievable distinction.
- Module map: `access/member_view.py` description ("shapes the ceiling into
  the tree view") stays, but the flow bullet about the separate shared
  section is dropped.
- "Open decisions": remove the scope-picker under-match entry (fixed here).
