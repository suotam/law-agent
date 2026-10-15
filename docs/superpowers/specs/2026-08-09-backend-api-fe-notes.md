# API notes for the FE

_Companion to `2026-08-09-backend-api-design.md` — condensed points a frontend implementation
needs to know, not a spec of its own._

## Auth

- `POST /auth/login` with `{email, password}` → `{access_token, token_type: "bearer"}`. Store it;
  send `Authorization: Bearer <token>` on every other request.
- Token is valid for 1 week and cannot be refreshed or revoked — expect a `401` when it expires
  and send the user back to login. No silent refresh to build.
- No self-registration screen needed. Admins create accounts through the `/admin/users`
  endpoints (admin-only pages/routes in the FE).
- **The identity is the email address; there is no username.** The login form must validate as
  an email, because a malformed one is rejected by schema validation (`422`) before the
  credentials are ever checked — a different code path from a wrong password (`401`).
- A wrong password and an unknown address return the identical `401` body on purpose. Don't
  build UI that distinguishes them; the API deliberately cannot tell you which it was.
- `GET /auth/me` → `{id, email, role, created_at}` for the token's holder. Primary use is
  verifying a stored token on app start: `200` means it is still good, `401` means send the user
  back to login. It reads the account row, so a role an admin has changed shows up here even
  though the token's own `role` claim is stale — prefer this over decoding the JWT client-side.
- A token that is validly signed but whose account no longer exists is `401`, not `404`.
- The `403` from the server stays the real authority on access; `/auth/me` only decides which
  nav to render.

## Admin endpoints

- `POST /admin/users` with `{email, password, role}` where `role` is `"admin"` or `"member"` →
  `201` with `{id, email, role, created_at}`. Re-using an address is `409`.
- `GET /admin/users` → the same object in a list, oldest first. No update, delete, or password
  reset endpoint exists.
- Both are `403` for a member — including the `GET`, so guard the whole admin route, not just
  the create form.

## Conversations

- Don't create a conversation on page load. Call `POST /conversations` lazily, at whichever
  happens first in a new chat: the first file attached, or the first message sent. Store the
  returned `id` and reuse it for every subsequent call in that chat. Never generate the id
  client-side.
- `POST /conversations` takes `{}` (or `{scope, limit}` if you ever build a source picker) and
  returns `{id, title, created_at, updated_at}`. The retrieval scope is frozen onto the thread
  at creation and is never sent again on later calls.
- `ConversationCreate` also takes two optional narrowing fields,
  `org_files_folder_ids: UUID[] | null` and `org_files_document_ids: UUID[] | null` — the chat
  org files scope picker's selection, sent alongside `scope` exactly the same way. `null`/omitted
  means "no narrowing, search everything the user is allowed to see" (today's behaviour
  unchanged); a concrete list narrows `org_files` retrieval to that subset for this conversation's
  whole life. **The server intersects whatever you send with the caller's actual access ceiling
  before freezing it** — a stale or tampered id outside that ceiling is silently dropped, never
  rejected, so there is no error path to handle for a narrowing that turns out too wide. These two
  fields are write-only: they are not returned by `GET /conversations/{id}` (see History, below),
  so the FE's own store is the source of truth for restoring the picker's selection.
- **Titling moved to creation time.** `POST /conversations` now accepts an optional `title`
  (truncated server-side to 30 characters, ellipsis on overflow) and `attachment_ids`
  (`UUID[]`, default `[]`). Sending no `title` leaves the conversation `""` forever — the server
  no longer names it from the first question. If the sidebar needs an auto-derived name, compute
  one client-side and send it as `title`; there is no rename endpoint to fix it up later.
- `attachment_ids` on creation claims each id for this conversation immediately (see Attachments,
  below, for what "claim" means). An id that fails — someone else's, already placed, unknown —
  makes the whole call `404`, but **the conversation row is not rolled back**: retry by sending
  the id in the first message instead of assuming the conversation never got created.
- `GET /conversations` (sidebar list) may currently include empty/untitled conversations (e.g.
  a file was attached but no message ever sent). This is a known, accepted gap for now, not a
  bug to work around on the FE.
- The list is the current user's own threads only, newest-activity first, and **capped at 50**
  with no pagination. Older threads are simply not reachable yet.
- `DELETE /conversations/{id}` → `204`, and it is a soft delete: the thread leaves the list but
  its messages and attachments stay on the server. Nothing to undo it through the API.
- Somebody else's conversation is `404`, never `403` — deliberately, so an id cannot be probed
  for existence. Treat "404 on a thread I think I own" as "gone", not as a bug.

## Attachments

- Attachments no longer require a conversation to exist first. `POST /attachments` (multipart,
  field named **`file`**, plus an optional `conversation_id` form field) replaces the old
  `POST /conversations/{id}/attachments`. Drop a file before the user has typed anything: upload
  it with no `conversation_id`, hold the returned id in component state, and either create the
  conversation with it in `attachment_ids` or send it with the first message — either path
  "claims" it. There is no third option where an upload is simply lost as long as you hold the id.
- One upload request per file, same as before — several files dropped at once is several
  requests. The response is `201` with `{id, filename, mime, byte_size, status}`, `status` being
  `pending` / `indexed` / `failed`.
- Each request still blocks until the file is fully parsed and indexed; drive "uploading…" →
  "ready" off that request's own lifecycle.
- Cancel mid-upload by aborting the request (`AbortController`). Remove an uploaded file —
  claimed or not — with `DELETE /attachments/{attachment_id}` (no `conversation_id` in the path
  any more). An attachment already used by a sent message cannot be removed: `404`, same as an
  unknown id.
- UX we settled on: keep the send button enabled while uploads are in flight. Queue the
  `sendMessage` call until every pending upload for that turn resolves, then fire it automatically.
- **There is still no endpoint that lists a user's pending attachments.** Upload response ids are
  the only record the FE has; hold them in component state until sent or the conversation is
  created. A page reload before either loses the chips — the files stay on the server as orphans,
  swept up automatically after 24 hours. Accepted for now, same as before.
- Upload is synchronous and unbounded: allow for tens of seconds of OCR in FE fetch/proxy timeouts.
- **A replayed question carries the files it was sent with.** In `GET /history`, a user message
  whose turn had attachments has a `data-attachments` part *before* its `text` part:
  `{"type":"data-attachments","data":{"items":[{id, filename, mime, byte_size}]}}`. A question sent
  without files has no such part — never an empty `items`. An upload nothing has claimed appears
  against no message, so this does not bring back the lost draft chips.
- **The stream never sends that part, and cannot:** a `data-*` frame is appended to the message
  being streamed, which is the answer, while these files belong to the question. `useChat` builds
  the user message on the client anyway — compose the same part there out of the upload responses
  you are holding, and the chip renders identically live and after a reload. That is what `mime` on
  the upload response is for: the four fields of an item are exactly the four you get back.

## Org files

New, admin-only — build the file manager behind the same route guard as `/admin/*`. Every route
below is `403` for a non-admin.

- `POST /folders` `{name, parent_id}` (`parent_id` omitted or `null` for a root folder) → `201`
  with `{id, parent_id, name, created_at}`. A sibling with the same name is `409`.
- `PATCH /folders/{id}` `{name?, parent_id?}` — send only what changes; a field left out is left
  alone. Renaming into a taken sibling name, or moving a folder into itself or one of its own
  descendants, is `409`.
- `GET /folders?parent_id=` → that folder's direct children (`omit parent_id` for the roots).
  There is no "whole tree" endpoint — walk it by following `parent_id`.
- `DELETE /folders/{id}` → `204`, only for an empty folder (no child folders, no documents):
  otherwise `409`. Move the documents out (re-upload elsewhere, then delete the originals) before
  deleting a folder that still holds any.
- `POST /folders/{id}/files` — multipart, field **`file`**, synchronous like a chat attachment
  upload. Response is the same `{id, filename, mime, byte_size, status}` shape attachments use.
  The same blob twice in one folder is `409`; the same file in two different folders is fine —
  the folder is part of what the file means there.
- `GET /folders/{id}/files` → that folder's documents, same shape as the upload response, as a
  list.
- `DELETE /org-files/{id}` → `204`.
- `GET /org-files/{id}/download` → the original file's bytes, with `Content-Disposition:
  attachment; filename="…"` and the stored mime type. This is the only download endpoint in the
  API — chat attachments stay display-only and are never fetched back this way.

## Member org files views (chat scope picker)

Three read-only, **capability-free** endpoints under `/me/org-files/*` — any authenticated user
may call them, unlike everything under "Org files" above. Each answers strictly "what can I see",
scoped to the caller's own access ceiling (folders they or a group they're in are granted on,
plus documents granted to them directly) — never the admin's full tree.

- `GET /me/org-files/roots` → `list[{id, name, ancestor_path}]` — the caller's own **virtual
  roots**: the topmost folders in their accessible set. `ancestor_path` is the real folder chain
  above it as plain text, for context only — there is no way to browse further up from here, by
  design (a grant on a folder never implies anything about that folder's own parent).
- `GET /me/org-files/folders/{id}` → `{folders: list[FolderResponse], files: list[DocumentResponse]}`
  — one accessible folder's real children, for expanding a tree node. `404` if `id` is outside the
  caller's accessible set (not `403` — same "don't confirm it exists" reasoning as a conversation
  that isn't yours). No further access filtering is needed below a virtual root: the whole subtree
  of an accessible folder is accessible too.
- `GET /me/org-files/shared-documents` → `list[{id, filename, mime, byte_size, status,
  ancestor_path}]` — documents granted to the caller directly, with no folder access needed at
  all. This is the flat "shared directly with you" section, separate from the tree.
- A user with no grants anywhere gets `[]` from all three, never an error.

Frontend: `frontend/src/features/sources/components/OrgFilesScopePicker.tsx`, rendered under
`SourceChips` once `org_files` is toggled on — a checkbox tree seeded from `roots`/`folders/{id}`
(indeterminate when some but not all loaded children are checked) plus the flat shared-documents
section. Selection lives in `org-files-scope-store.ts`, cleared when `org_files` is toggled off,
and sent as `org_files_folder_ids`/`org_files_document_ids` on `POST /conversations` (see
Conversations, above). Locked once the conversation exists, the same way `scope` already is.

## Users and Roles

`GET /auth/me` and every row of `GET /admin/users` return the same `UserResponse` shape — this
is the accounts admin table's rows and the currently-signed-in user's own authorization
snapshot at once, without a second lookup:

```json
{
  "id": "uuid",
  "email": "user@firma.cz",
  "role": { "id": "uuid", "name": "Admin" },
  "capabilities": ["manage_users", "manage_org_files_structure"],
  "is_superuser": false,
  "created_at": "2026-08-01T00:00:00Z"
}
```

`capabilities` and `is_superuser` denormalise the caller's own role onto their own account row,
so the FE can drive nav and route guards from `useAuth()` alone (cached with
`staleTime: Infinity` — a role edited mid-session reaches that user's own screen only on their
next login).

`POST /admin/users` takes `{email, password, role_id}` and returns `201` with the shape above;
re-using an address is `409`. `PATCH /admin/users/{id}` takes `{role_id}` and returns the
updated `UserResponse`; an unknown `role_id` on either endpoint is `404`.

`GET /users` alone is reachable with `MANAGE_GROUPS` too, not just `MANAGE_USERS` — a group
manager picking whom to add needs the list (`MembershipEditor.tsx`) without needing account
administration. Registered from a second router (`users.py:list_users_router`), same shape as
`acl.py`'s `user_acl_router`; every other endpoint here stays `MANAGE_USERS`-only.

Role administration lives at `/roles` and is **not gated by any capability — superuser-only end
to end**, the same way group/ACL grants are the one thing a capability can never unlock, because
a role's own capability set is what the capability system configures:

- `GET /roles` → `list[RoleResponse]`, `RoleResponse = {id, name, is_superuser, capabilities,
  created_at}`.
- `POST /roles` `{name}` → `201` with `RoleResponse`.
- `PATCH /roles/{id}` `{name}` → `RoleResponse`.
- `PUT /roles/{id}/capabilities` `{capabilities}` → `RoleResponse`. Always send the **full**
  replacement set, never a diff — this is what `frontend/src/features/roles/components/
  CapabilityCheckboxes.tsx` does on every single toggle.
- `DELETE /roles/{id}` → `204`, or `409` (`RoleInUseError`) if the role is still assigned to at
  least one user — surface this inline in the confirm dialog, the same pattern
  `org-files/components/DeleteDialog.tsx` uses for a non-empty folder, not as a toast.

Frontend: `frontend/src/features/users/` and `frontend/src/features/roles/`, mirroring
`features/org-files/`'s shape (`api/` one file per endpoint + `query-keys.ts`, `components/`,
`types.ts`, `index.ts`). The route guard is `RequireCapability`
(`frontend/src/app/middlewares/RequireCapability.tsx`), used as
`<RequireCapability capability="manage_users" />` or `<RequireCapability superuser />` — it
replaced the old hardcoded-`"admin"` `AdminRoute`, which no longer described anything once role
became dynamic.

## Groups and access control

- `GET /groups` / `POST /groups` / `PATCH /groups/{id}` / `DELETE /groups/{id}`
  — group CRUD, `MANAGE_GROUPS`-gated, same shape as roles.
- `POST /groups/{id}/members` `{user_id}` / `DELETE /groups/{id}/members/{user_id}`
  / `GET /groups/{id}/members` → `list[UserResponse]` — membership.
- `POST /acl` `{resource_type, resource_id, principal_type, principal_id,
  permission}` → upserts on the four-column identity; `DELETE /acl/{id}`.
  Both require the capability matching *this entry's* `principal_type` —
  `MANAGE_GROUPS` for a `group` grant, `MANAGE_USERS` for a `user` grant —
  not just any ACL-adjacent capability; `GET /acl` and `GET /acl/effective`
  admit either.
- `GET /acl?resource_type=&resource_id=` → the explicit grants on exactly
  one resource.
- `GET /groups/{id}/acl` / `GET /users/{id}/acl` →
  `{entries: list[AclEntryResponse], folders_with_nested_grant: list[UUID]}`
  — every grant the principal holds, across every folder and file, in one
  call (fetched once by the principal-centric access browser instead of once
  per row while navigating), plus the folders that hold none of their own
  but have one somewhere deeper inside (`access/service.py:
  folders_with_nested_grant`) — the browser's "worth descending into"
  marker for a folder that would otherwise look indistinguishable from an
  actually-empty one. The user variant covers direct grants only (not via
  group membership) and is `MANAGE_USERS`-gated, registered from a second
  router in `acl.py` sharing the `/users` prefix with `users.py`'s
  account-management routes.
- `GET /acl/effective?resource_type=&resource_id=` →
  `{own: list[AclEntryResponse], inherited: list[AclEntryResponse]}` — `own`
  is this resource's explicit grants (editable), `inherited` is what it
  receives from ancestor folders (read-only context). Without this split a
  resource with no grants of its own looks identical whether "no one can see
  it" or "the parent folder's group already can" — this is what tells them
  apart in the Share panel.
- No deny, no override, only union — the same rule spec 1's data model
  documents: a resource with its own grant rows adds to what it inherits, it
  never replaces it. There is no way to unshare a child from its parent's
  grant except moving it elsewhere.

Frontend: `frontend/src/features/groups/`, mirroring `features/users/` and
`features/roles/`'s shape. Two access views reuse the same write endpoints
from different angles: `AccessBrowser` (principal-centric — one component
serving both a group and a user, `principalType`/`principalId`/
`principalName` as props; reuses `features/org-files`' `useFolderPath`/
`Breadcrumb`/`ItemList` navigation with a per-row access toggle in place of
file actions, rendered at `/admin/groups/:id/access` and
`/admin/users/:id/access`) and `SharePanel` (resource-centric, a "Share" row
action on `FileBrowser`, gating its own group/user radio and each grant's
remove control by whichever of `manage_groups`/`manage_users` the caller
holds). The "Groups" admin nav link and `/admin/groups` route are gated the
same way `/admin/users` is — `manage_groups` or superuser; the per-user
access route additionally requires `manage_org_files_structure`, same as the
per-group one.

This makes `features/org-files` and `features/groups` depend on each other —
`FileBrowser` imports `SharePanel`, `GroupAccessBrowser` imports org-files'
navigation primitives. Deliberate, not an oversight: there is no runtime
import cycle (each direction bottoms out in leaf modules, never back through
the other feature's barrel), and splitting `SharePanel` into a third shared
module purely to avoid the coupling would cost more than it buys for two
features this tightly related by the feature itself (org file rows sharing
their access).

## Sending a message / streaming

- `POST /conversations/{id}/messages` — question text plus only fully-resolved attachment ids
  (never ones still uploading). The body is `{"question": "...", "attachment_ids": []}`: the
  field is **`question`**, not `message` or `text`, and an empty string is `422`.
- Responses use the Vercel AI SDK **data stream protocol** — use `DefaultChatTransport`, not
  `TextStreamChatTransport`. The response carries `x-vercel-ai-ui-message-stream: v1`, which is
  what the SDK's transport negotiates on; any proxy in front of the API must not strip it, nor
  buffer the body.
- Citations arrive as structured parts, not inline `[ref]` markers to parse out of text — but
  the answer text still contains the `[n]` marks, and `n` matches `ref` in the sources part.
  Rendering them as links is the FE's job.
- **A `ref` is unique for the whole conversation, not for one turn.** Accumulate the
  `ref → source` map across every `data-sources` part the thread has produced and resolve marks
  against that map, not against the current message's part. An answer may cite a source first
  offered several questions ago, and a source found again comes back under the ref it already
  had — so writing into the map is idempotent.
- A failure partway through generation shows up as an error part inside the stream, not as an
  HTTP error status (by that point headers are already sent and the status can't change). The
  `errorText` is a fixed Czech sentence safe to display verbatim; it never carries server detail.
- The failure modes that *do* arrive as a status, because they are resolved before the first
  token: `404` for an unknown conversation or an attachment id that isn't a pending attachment
  of this conversation, `422` for a malformed body, `401` for a dead token.
- The whole turn is written to the archive only once the stream completes. An aborted stream
  leaves the question stored with no answer, and the next `GET /history` will show exactly that.

### Frame sequence

Every turn is this sequence, one SSE `data:` line per frame:

```
{"type":"start","messageId":"<uuid>"}
{"type":"data-sources","data":{"items":[{"ref":1,"kind":"law","label":"§ 1829 obč. zák.","content":{…}}]}}
{"type":"text-start","id":"answer"}
{"type":"text-delta","id":"answer","delta":"Do 14 "}
…
{"type":"text-end","id":"answer"}
{"type":"error","errorText":"Odpověď se nepodařilo dokončit."}   ← only when generation died
{"type":"finish"}
[DONE]
```

- `data-sources` is a **custom** data part, so in `useChat` it surfaces as a part of type
  `data-sources` — not one of the SDK's built-in `source-*` parts. `kind` is `law` or `document`
  and tells the FE how to resolve the link; `content` is opaque and shaped by the tool.
- `messageId` is generated per response and is *not* the archived message's id. Don't key
  anything persistent off it — after a reload, `GET /history` hands out different ids.
- `text-end` is emitted even when generation failed, so whatever text arrived settles instead of
  hanging in a streaming state.

## History

- `GET /conversations/{id}/history` returns the full message list for a conversation — use it to
  hydrate `useChat`'s initial messages when opening an existing chat, not just for a new one.
- The shape is already the SDK's: `[{id, role, parts}]`, with `role` only ever `"user"` or
  `"assistant"`. The search round the model ran is machinery and is filtered out — you will not
  see `tool`-role messages or tool parts.
- An assistant message's `parts` is `[{type:"text",text:"…"}]`, plus the turn's `data-sources`
  part listing what that turn's search *found* — not only what the answer cited, and not the
  conversation's whole map. It is **byte-identical to what the live stream sends**, so the
  citation renderer is written once and works for both paths, and the accumulated map is built
  the same way whether the thread was streamed or hydrated from history.
- `id` here *is* the stored message's id and is stable across reloads.
- `GET /conversations/{id}` returns `{id, title, created_at, updated_at, scope, limit}` — the
  same fields as the list plus the retrieval settings frozen onto the thread at creation. Use it
  when opening a thread from history to restore the source picker; the messages themselves still
  come from `/history`, which this endpoint does not include.
- `scope` and `limit` are read-only. There is no endpoint that changes them: a thread answers
  from the sources it was created with, for its whole life.

## Status codes and error bodies

| Code | When | Body |
|---|---|---|
| `401` | missing, malformed or expired token | `{"detail":"not authenticated"}` |
| `401` | bad login credentials | `{"detail":"invalid email or password"}` |
| `403` | a member hitting an admin route | `{"detail":"insufficient role"}` |
| `404` | unknown *or* someone else's conversation/attachment, or an unknown folder/org file | `{"detail":"…"}` |
| `409` | admin creating a duplicate email, a duplicate folder name, a non-empty folder delete, a folder move that would create a cycle, or a duplicate file in a folder | `{"detail":"…"}` |
| `422` | schema validation | FastAPI's array form, see below |
| `500` | anything unexpected | `{"detail":"internal server error"}` |

`detail` is a **string on every code except `422`**, where it is FastAPI's array of field errors:

```json
{"detail":[{"type":"string_too_short","loc":["body","question"],
            "msg":"String should have at least 1 character","input":"","ctx":{"min_length":1}}]}
```

A shared error handler must branch on that, or it will render `[object Object]`. `500` never
leaks server detail — there is nothing useful in it to show the user.

## Deployment

- CORS is driven by the API's `CORS_ORIGINS` env var and defaults to `http://localhost:3000`
  only. **The Vercel preview and production domains have to be added there**, or every request
  from the deployed FE fails at the preflight. Credentials are allowed, all methods and headers.
- Timestamps are ISO-8601 UTC with a `Z` suffix (`2026-08-09T11:31:57.529044Z`).
- The interactive OpenAPI schema is at `/docs` — the authoritative reference for anything this
  document is vaguer about.
