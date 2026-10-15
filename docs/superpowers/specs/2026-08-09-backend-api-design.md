# Backend API design

_Spec, 2026-08-09. Result of a brainstorming session on the API layer that will sit in front
of `law_agent` and be consumed by a future React/Vercel-AI-SDK web UI (separate sub-project,
not covered here beyond the integration notes in the companion FE file)._

## Goal

Expose the existing `law_agent` library (conversations, RAG chain, retrieval) over HTTP, with
enough auth to distinguish users and roles, without duplicating any business logic into the API
layer. `law_agent` stays a framework-free library; the API is a thin adapter over it, the same
role `ui/streamlit_app.py` already plays.

## Scope

In scope: FastAPI app structure, authentication and authorization, conversation/chat/attachment
endpoints, streaming protocol, error handling, testing approach.

Explicitly deferred (not designed here):

- Token refresh/revoke, self-registration, password reset — minimal-first was the stated
  priority ("security isn't the priority, the priority is that adding security later is easy"),
  not maximal security now.
- Filtering empty/orphaned conversations out of `GET /conversations` — acknowledged as a gap,
  intentionally not solved yet.
- Blob cleanup was checked, not deferred: `storage/blobs.py` writes via a temp file + atomic
  rename, so an aborted upload cannot produce a corrupted blob, only (at worst) an unreferenced
  one if indexing fails after the write — and `storage/gc.py`'s `sweep_blobs()` already exists
  as the safety net for exactly that case. Confirmed: `sweep_unreferenced_blobs()` asks
  `DocumentRepository.count_by_blob`, which filters on `blob_sha256` alone, so a conversation
  attachment references its blob exactly like an org document does and the sweep already
  covers both; no new mechanism needed here.
- Org-file RBAC / dynamic roles beyond `admin`/`member` — still an open project-level decision
  (see the project spec memory); today's roles are a placeholder for that eventual model.
- The FE implementation itself — see the companion notes file for what it needs to know.

## Architecture

New `src/law_agent/api/` package:

- `auth/` — user model access, password hashing, JWT issuance/verification, the
  `get_current_user` and `require_role(...)` dependencies
- `routers/` — `admin.py` (user management), `conversations.py` (chat/history/CRUD/attachments)
- Pydantic request/response schemas for the HTTP boundary

The API package only calls into `conversations/service.py`, `db/`, `documents/`, etc. — it never
grows business logic of its own, and nothing in `law_agent`'s existing modules imports from
`api/`. FastAPI was chosen over alternatives because the project already sits on
Pydantic + SQLAlchemy + Alembic, which FastAPI uses natively for request/response validation and
dependency injection.

`api/` is nested inside `src/law_agent/` rather than top-level (unlike `ui/`) because this is a
single-deployment application, not a redistributable library — the practical win of avoiding
import-path/packaging ceremony around `uvicorn` outweighs the purity of a framework-free core
package. It still shares `db/` (no duplicated models) and stays behaviorally separate.

## Authentication & authorization

- `users` table: `id`, `email`, `password_hash`, `role` (string: `"admin"` | `"member"`). A
  string column, not a `roles` table — a real RBAC/permissions model doesn't exist yet
  (org-file filtering is still undesigned), so a normalized roles table today would just hold
  two static rows. Migrating a string column to an FK-backed table later is a small, mechanical
  migration; it isn't a decision that costs future flexibility.
- `POST /auth/login` — `{email, password}` → `{access_token}`. Self-issued JWT (own login +
  password check, no external identity provider), 1-week expiry, role carried as a claim.
  Deliberately stateless: no refresh token, no revoke list. A compromised token is valid until
  it expires — accepted given the stated priority.
- `get_current_user` dependency — decodes and validates the JWT, returns `(user_id, role)`.
  Every non-auth endpoint depends on this.
- `require_role("admin")` dependency — layered on top of `get_current_user` for admin-only
  routes.

This shape is deliberately the minimal one that still speaks the protocol a future OIDC/Keycloak
integration will speak: bearer JWT, role claim, one dependency that validates and extracts
identity. Migrating later means replacing what mints and verifies the token (and the `users`
table with Keycloak-managed identities) — the authorization checks throughout the rest of the
API (`require_role`, per-endpoint role checks) don't change shape.

## Admin endpoints (role = `admin` only)

- `POST /admin/users` — `{email, password, role}` → creates a user
- `GET /admin/users` — lists users

No self-registration and no password-reset flow: this is an internal tool for one firm, accounts
are provisioned by an admin.

## Conversation & chat endpoints

- `POST /conversations` — creates an empty conversation (no title yet), returns `{id}`.
  Triggered lazily by the FE, not on page load: whichever happens first in a new chat — the
  first attachment upload or the first message send — calls this to get an id, then reuses it
  for everything else in that chat. The id is always server-generated, never client-supplied.
- `GET /conversations` — lists the current user's conversations (`owner` = JWT user id). May
  include conversations with no messages yet (see Scope — deferred).
- `GET /conversations/{id}/history` — full message history, for replaying a conversation.
- `DELETE /conversations/{id}` — deletes a conversation.
- `POST /conversations/{id}/attachments` — **one file per request** (multipart), not a batch
  endpoint. Synchronous: parses, chunks, and indexes the file before returning; the response
  (and the attachment id in it) only arrives once the file is actually usable in a message. This
  is what makes upload ordering safe by construction — a client cannot reference an attachment
  id in `/messages` before the upload call that produces it has returned, so there is no race
  between "attachment saved" and "attachment searchable." Multiple files uploaded together are
  multiple concurrent requests, not one batch call, so each has its own cancelable/removable
  lifecycle.
- `DELETE /conversations/{id}/attachments/{attachment_id}` — removes an already-processed
  attachment before it's referenced by a message. An in-flight (still processing) upload is
  instead canceled by the client aborting that HTTP request.
- `POST /conversations/{id}/messages` — the chat turn: `{question, attachment_ids}`. Streams the
  answer back using the Vercel AI SDK data stream protocol. Sets
  `title = title_from(question)` if this is the conversation's first message.

## Streaming protocol

The data stream protocol (not the plain text stream) was chosen so citations
(`SourceItem`/`used_refs`, already produced by the existing chain) arrive as structured parts the
FE can render directly, instead of text the FE has to re-parse `[ref]` markers out of.

Once a stream has started, HTTP status can no longer change (headers are already sent). A
failure mid-stream (e.g. `ask()` raising partway through) is surfaced as an error part within the
stream, using the data stream protocol's own error-part convention, not as an HTTP error status.

## Error handling

- `HTTPException` for expected, pre-stream failures: 401 unauthenticated, 403 wrong role, 404
  unknown conversation/attachment, 422 validation (via Pydantic request schemas).
- A single exception handler maps anything unexpected to a generic 500, logs the traceback
  server-side, and never leaks internals to the client.
- Streaming responses use the error-part convention described above once headers are sent.

## Testing

The existing test suite (`tests/test_conversations.py`, `tests/test_answer.py`, etc.) already
exercises the service layer directly and keeps doing so — RAG/service behavior is not retested
through HTTP. The API layer gets its own thin tests using FastAPI's `TestClient`, focused on what
only the HTTP layer can get wrong: auth (role gating, expired/invalid tokens) and
request/response shape.

## FE integration

See `docs/superpowers/specs/2026-08-09-backend-api-fe-notes.md` for the condensed points a
frontend implementation needs to know.
