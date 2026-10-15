# Filtering retrieval by the caller's access

## The problem

`retrieval/search.py` has no notion of who is asking. `_query()` filters
Qdrant purely by `namespace` (plus, for attachments, `conversation_id`) — any
authenticated member can retrieve any indexed `org_files` chunk, regardless of
the access model this now has (`2026-09-05-access-control-data-model-design.md`).
`chain/tools.py` already names this as the reason scope is decided by the
orchestration and not the model: "with roles, the scope is an authorisation
boundary" — that boundary needs to actually exist.

## Scope

Enforce the access ceiling from the ACL model on every `org_files` chunk a
query can return. Out of scope:

- The user narrowing that ceiling further to a chosen subset of folders/files
  for one chat (next spec) — this spec only makes the *maximum* correct; a
  narrower in-chat choice is layered on top of it later, never wider.
- `laws` (no ACL, unaffected) and `user_files`/attachments (already scoped by
  `conversation_id` and ownership, unrelated to this model).

## Design

### Two new resolver functions, `access/service.py`

Distinct from `effective_permission()` (spec 1, which answers "can this user
read *this one* resource"), retrieval needs the *whole set* a user may see,
computed once per search call:

```python
def accessible_org_folder_ids(user_id: UUID) -> set[UUID]:
def directly_granted_document_ids(user_id: UUID) -> set[UUID]:
```

`accessible_org_folder_ids`: one recursive query over `folders` — seed with
every folder that has an `acl_entries` row matching the user directly or one
of their groups, then descend via `parent_id` to every folder underneath
each seed (inheritance flows down, so a grant on a folder implies its whole
subtree). `directly_granted_document_ids`: a flat query for `acl_entries`
rows where `resource_type = 'document'` and the principal matches — this is
what makes a single deep grant reachable without its ancestor folders being
in the first set at all.

A superuser role bypasses both entirely at the call site — `search()` never
calls them for such a user, rather than calling them and discarding the
result, so an admin's query cost stays what it is today.

### Building the Qdrant filter

The chunk payload already carries `folder_id` (`documents/service.py:149`),
so the sets above translate directly into a filter: an `org_files` chunk
qualifies if its `folder_id` is in the accessible-folders set **or** its
`doc_id` is in the direct-grants set.

The one real complication: `scope` can be `laws` and `org_files` together,
resolved today in a **single** ranked Qdrant call (one RRF fusion across
both). Naively adding a `folder_id`/`doc_id` condition to that call's filter
would apply it to the whole call, and silently drop every `laws` hit too —
exactly the mistake the existing `_attachment_hits` comment already warns
about for a different field. Two ways to avoid it:

- **(A, recommended) One nested filter.** Qdrant filters compose:
  `should: [Filter(must=[namespace=laws]), Filter(must=[namespace=org_files,
  <folder/doc should-group>])]`. Both namespaces stay in the same ranked
  call — RRF still fuses them together and `limit` still bounds the combined
  total, exactly as today. `_build_filter` (`retrieval/retriever.py`) gains
  this branch only when both namespaces are requested and a permission
  filter is present; the existing flat-`must` shape stays untouched for
  every other case (single namespace, or superuser with no restriction).
- **(B) Split into two calls**, one per namespace, each filtered
  independently — simpler code, but changes retrieval behaviour: `laws` and
  `org_files` are no longer ranked against each other in one fusion, and the
  combined result can now return up to `2 × limit` chunks instead of `limit`
  total. That is a quality regression with no upside, so (A) is worth the
  extra filter-construction complexity.

`search()` gains a required keyword-only `user_id: UUID` — no default. This
is a security boundary now, not a convenience parameter; a call site that
forgets to pass it should fail loudly (a `TypeError` at the call site), not
silently search unfiltered. `ask()` (`conversations/service.py:293`) gains
the same required parameter, threaded from the router's `CurrentUser` into
its call to `search()`.

**Empty-access edge case.** A non-superuser with zero accessible folders and
zero direct document grants must return no `org_files` chunks — not skip the
filter (which would mean unfiltered) and not send Qdrant an empty `should`
list (whose match semantics for "nothing satisfies this" should not be
relied on). `search()` checks for this case explicitly and omits the
`org_files` branch of the query entirely when both sets are empty, the same
way it already omits the attachments call when `conversation_id` is `None`.

### Performance note (not solved here)

Unlike the capability check (spec 1, one row lookup per request),
`accessible_org_folder_ids` runs a recursive query over the whole folder
tree on every chat turn that has `org_files` in scope — this is genuinely
per-question, not per-login. No caching is introduced in this spec; if the
folder tree or query volume grows enough for this to matter, the natural
next step is caching the set per user, invalidated when that user's group
membership or any ACL grant changes — flagged here rather than built now,
since it is premature without a measured cost.

## Testing

`tests/test_access_service.py` (extending spec 1's file):

- `accessible_org_folder_ids` includes a grant's own folder and every
  descendant, and excludes sibling subtrees with no grant of their own.
- `directly_granted_document_ids` surfaces a document whose entire ancestor
  chain has no grant.

`tests/test_search.py` (new or extended):

- A member with no grants and `org_files` in scope gets zero `org_files`
  chunks back, even when matching ones exist and `laws` chunks are still
  returned for the same call.
- A member with a grant on folder `F` gets chunks from `F` and its
  descendants, not from a sibling folder with equally good text matches.
- A member with only a direct grant on one document, no folder grants at
  all, gets that document's chunks.
- A superuser gets every `org_files` chunk a matching, ungated query would
  today — no behaviour change for the existing admin path.
- Scope `[laws, org_files]` together still issues one Qdrant call (assert
  the fake client is invoked once, not twice) — locks in approach (A) over
  (B) so a future edit doesn't quietly regress into the two-call shape.

## Documentation

`docs/ARCHITECTURE.md`: drop "role-based retrieval filtering over org files"
from "Open decisions" — this spec, once implemented, closes it. Update the
"Auth" bullet's closing sentence ("retrieval itself is not role-filtered")
to describe the new filtered behaviour.
