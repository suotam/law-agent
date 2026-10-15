# Freestanding attachments and an org files API

## The problem

Today `POST /conversations/{id}/attachments` requires a conversation to already
exist. The FE therefore calls `POST /conversations` as soon as a user drops a
file into a new chat — before any message is sent. If the user leaves without
sending one, an empty, titleless conversation is left behind in the sidebar.

Separately, org files (the `folders` tree and the documents inside it) have no
HTTP surface at all. `FolderRepository.ensure_path` is a developer-only CLI
path; there is no way for the app itself to create a folder, upload into one,
list its contents, or fetch a file back.

## Scope

- An attachment can be uploaded before any conversation exists. It becomes
  part of a conversation either when that conversation is created
  (`attachment_ids` on `POST /conversations`) or when it is first referenced
  in a message.
- A full HTTP interface for org files: folders (create, rename/move, list,
  delete) and the documents inside them (upload, list, delete, download).

Out of scope:

- Moving an existing org file between folders (re-upload if it needs to move).
- Any change to how retrieval scopes or ranks results.
- A non-admin role for managing org files (see **Authorization** below for how
  this stays cheap to loosen later).

## Data model

No migration. `documents.folder_id`, `.message_id` and `.conversation_id` are
already nullable (migration `0004_document_conversation`), so a document with
all three `NULL` — an uploaded-but-not-yet-placed attachment — is already a
representable row.

`namespace_for()` (`documents/service.py`) currently raises when it sees no
`folder_id` and no `conversation_id`. It gains a fourth case: all three `None`
resolves to `Namespace.USER_FILES`, the same namespace an in-chat attachment
already uses. It is not indexed under any conversation until one claims it, so
nothing can retrieve it in the meantime — see **Indexing and claiming**.

## Attachments

### Upload: one endpoint, optional binding

`POST /attachments` (new top-level router, not nested under `/conversations`)
replaces `POST /conversations/{id}/attachments`. Multipart body: `file`, plus
an optional `conversation_id` form field.

- `conversation_id` given: resolved and ownership-checked the same way
  `owned_conversation` does today (404 if it is not this user's, or does not
  exist). The document is created with that `conversation_id` set directly —
  this is the "adding a file to an ongoing chat" path, unchanged in spirit
  from today's nested endpoint, just moved.
- `conversation_id` omitted: the document is created with `conversation_id =
  NULL`, `uploaded_by` = the caller. A draft, owned by the uploader, not yet
  placed anywhere.

Both cases stay synchronous and blocking, exactly as today: the response is
only sent once the file is parsed, chunked and indexed.

`DELETE /attachments/{id}` replaces `DELETE
/conversations/{id}/attachments/{id}`. Removes a draft no message has used
yet (`message_id IS NULL`), whether or not it already carries a
`conversation_id`. Authorization is `document.uploaded_by == current_user`
directly, rather than through conversation ownership — the one check that
covers both states.

### Indexing and claiming

An unbound upload is chunked and indexed immediately, under `USER_FILES`,
with no `conversation_id` in the Qdrant payload (the chunker already omits
the key rather than writing a null — see `ChunkLike.to_payload`). Since
`search()` only ever queries attachment hits scoped to one concrete
`conversation_id`, a draft is unreachable by construction until something
gives it one. No new state or status is needed to express "not searchable
yet."

**Claiming** a draft — writing its `conversation_id` — never re-parses or
re-chunks. It is a metadata move in two places:

1. `DocumentRepository.claim(document_ids, *, conversation_id)`: sets the
   column.
2. A new `indexing.retag_conversation(client, collection_name, *, doc_id,
   conversation_id)`: `client.set_payload(...)` filtered on the chunk
   payload's `doc_id`, adding `conversation_id` to every point of that
   document. Payload-only; no embeddings touched.

A shared service helper, `_claim(document_id, *, conversation, owner) ->
Document`, does both, after checking the draft exists, is unbound
(`conversation_id IS NULL`, `folder_id IS NULL`), is not yet referenced by a
message, and `uploaded_by == owner`. Anything else — someone else's draft, an
already-placed one, an unknown id — raises `AttachmentNotFoundError`, the same
error every other attachment-id mistake already raises.

Two call sites use it:

- **`POST /conversations`** (see below): claims every id in `attachment_ids`
  against the conversation it just created.
- **`ask()`**: for each `attachment_id`, if it already belongs to this
  conversation, nothing changes (the common case — uploaded with
  `conversation_id` set, or claimed earlier); if it is an unbound draft owned
  by the conversation's owner, it is claimed now, in place of today's
  read-only `_require_pending_attachment` check.

This means a client never has to think about *when* a draft gets bound — it
uploads once, then either creates a conversation with the id in
`attachment_ids`, or sends a message with it, and either path claims it.

### Conversation creation carries attachments and a title

`ConversationCreate` gains:

```python
title: str | None = None
attachment_ids: list[UUID] = Field(default_factory=list)
```

`create_conversation()` truncates a given title to 30 characters, ellipsis on
overflow — the same shape `title_from()` already uses for the 80-character
auto-title from the first question, factored into one shared `_truncate(text,
limit)` so the two don't drift. An empty or omitted title leaves the
conversation untitled.

**Titling moves entirely to creation time.** `ask()` currently names an
untitled conversation from the first question it sees
(`ConversationRepository.set_title(conversation_id, title_from(question))`).
That call is deleted: a conversation's title is now whatever `POST
/conversations` was given — the client's `title`, or an empty string forever
if none was sent. `title_from()` itself is unaffected by this change, only
unused by `ask()` going forward. An API client wanting an auto-derived title
now computes it itself and sends it as `title`, since there is no separate
rename endpoint. This is a behaviour change for any existing conversation
created with an empty title through the HTTP API: it used to acquire a name
on the first turn and now will not.

After the row is created, each id in `attachment_ids` is claimed against it.
An id that fails the claim check (wrong owner, already placed, already used,
unknown) raises `AttachmentNotFoundError` → 404, and the conversation is
**not** rolled back — the row already committed, so a client that gets a 404
here should retry the claim by sending a message instead, not assume the
conversation vanished. This mirrors how `ask()` already treats a partially
failed turn: the question survives even when what follows does not.

### Response shape

`AttachmentResponse` is renamed `DocumentResponse` and shared verbatim with
org files (below) — both are the same four fields projected off the same
`Document` model, and giving them two names would only mean two schemas to
keep in step for no behavioural difference.

### Orphaned drafts

A draft nobody ever claims (the user closes the tab before sending anything)
is now the thing left behind, instead of an empty conversation. Cleaned up by
a new `sweep_unbound_attachments(grace: timedelta = timedelta(hours=24), now:
datetime | None = None) -> SweepStats` in `documents/service.py`, mirroring
`sweep_unreferenced_blobs`: finds documents with `folder_id IS NULL AND
conversation_id IS NULL` older than the grace period and runs the existing
`delete_document()` on each (which already removes the Qdrant points, the
row, and — if unreferenced — the blob). Same as the blob sweep, this is a
function to invoke from a cron, not wired into anything by this change.

## Org files

New router, `org_files.py`, mounted outside `/conversations`. Every route
carries `dependencies=[Depends(require_role(UserRole.ADMIN))]` at the router
level — one line to change if a non-admin role should manage org files later,
the same pattern `admin.py` already uses for user management.

### Folders

- `POST /folders` `{name, parent_id}` → `FolderResponse`. Duplicate sibling
  name raises `DuplicateFolderError` (already exists) → 409.
- `PATCH /folders/{id}` `{name?, parent_id?}` — rename, move, or both.
  `FolderRepository` gains `update()`. Moving checks the new parent is not the
  folder itself or one of its own descendants (walk the new parent's
  ancestor chain via `parent_id`, reject if the target folder's id appears);
  a self/descendant move raises a new `FolderCycleError` → 409. A rename
  collision goes through the same `DuplicateFolderError` as create.
- `GET /folders?parent_id=` → `list[FolderResponse]`, the children of that
  folder (root folders when omitted) — `FolderRepository.children` already
  does this.
- `DELETE /folders/{id}` — only an empty folder (no child folders, no
  documents). The FK is `ON DELETE RESTRICT`, so a non-empty folder's delete
  fails at the database; `FolderRepository.delete()` catches the
  `IntegrityError` and raises a new `FolderNotEmptyError` → 409, rather than
  leaking a raw database error.

### Files

- `POST /folders/{id}/files` — multipart `file`. Synchronous ingest via the
  existing `ingest_document(folder_id=...)`, `namespace=ORG_FILES`. A
  duplicate blob in the same folder raises the existing
  `DuplicateDocumentError` → 409.
- `GET /folders/{id}/files` → `list[DocumentResponse]`.
  `DocumentRepository` gains `list_by_folder(folder_id)`, the folder
  counterpart of the existing `list_by_conversation`.
- `DELETE /org-files/{id}` — calls the existing `delete_document()`.
- `GET /org-files/{id}/download` — streams the original bytes from the blob
  store (`BlobStore.open(sha256)`), with `Content-Disposition:
  attachment; filename="..."` from the stored filename and the stored `mime`
  as the response's content type. The only place in the codebase that serves
  a document's bytes back — deliberately not extended to chat attachments,
  which stay display-only per the existing history-attachments design.

### Why two upload endpoints instead of one

`POST /attachments` and `POST /folders/{id}/files` both end in the same
`ingest_document()` call — no duplication there. They stay separate endpoints
because everything around that call differs:

- **Authorization.** Any member uploads to their own conversation; only an
  admin uploads to a folder. A single endpoint would have to branch
  authorization on which id was supplied, which is the same "one parameter,
  two behaviours" shape the codebase already avoids elsewhere (see
  `create_conversation`'s own docstring on why it is not an optional argument
  to `ask()`).
- **Duplicate handling.** A folder forbids the same blob twice
  (`ux_documents_folder_blob`); a conversation does not — the same PDF
  attached to a later question in the same thread is normal.
- **Lifecycle after upload.** An attachment can be deleted while pending
  (`message_id IS NULL`); an org file has no such pending phase.

## Testing

`tests/api/test_attachments_api.py`:

- Upload with no `conversation_id` returns a document with `conversation_id`
  unset; upload with one behaves as the old nested endpoint did.
- Upload with a `conversation_id` that is not the caller's conversation → 404.
- `DELETE /attachments/{id}` on someone else's draft → 404; on one already
  referenced by a message → 404.
- `POST /conversations` with `attachment_ids` claims them (conversation_id
  set, Qdrant payload retagged — the retag call is stubbed at the service
  boundary, same pattern the existing tests use for `add_attachment`).
- `POST /conversations` with an `attachment_id` that belongs to another user
  → 404, and the conversation row still exists (not rolled back).
- Sending a message with a still-unbound `attachment_id` claims it as a side
  effect of `ask()`.

`tests/test_conversations.py`: a conversation created with no title stays
titled `""` after its first turn — `ask()` no longer calls `title_from()`.
`title_from()` itself keeps its existing tests unchanged, since the function
is not removed.

New `tests/test_documents_service.py` or extending the existing documents
tests:

- `sweep_unbound_attachments` deletes a draft older than the grace period and
  leaves a young one and a placed one alone.

New `tests/api/test_org_files_api.py`:

- Folder create/rename/move/list/delete, including the duplicate-name 409,
  the non-empty-folder 409, and the cycle-move 409.
- A non-admin user gets 403 on every org files route.
- File upload/list/delete/download round-trip, including the
  duplicate-blob-in-folder 409.

## Documentation

`docs/superpowers/specs/2026-08-09-backend-api-fe-notes.md`: update the
Attachments section for the new upload/delete shape (single endpoint,
optional `conversation_id`, claiming); note that `POST /conversations` no
longer acquires a title on the first turn, so a client wanting an
auto-derived name must compute and send one as `title` itself; and add an
Org Files section describing the new endpoints for the FE team building the
admin file manager.
