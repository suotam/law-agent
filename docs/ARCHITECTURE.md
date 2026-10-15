# Architecture

Agentic RAG for a law firm (on-premise, no multi-tenancy). Answers over
Czech laws, internal org files, and in-chat uploaded files, citing sources.
Python 3.13, uv, FastAPI, LangChain, Qdrant, Postgres.

This is a high-level overview of principles, structure and status — not
exhaustive design documentation. For implementation nuance, read the code
(module docstrings, the functions named below).

## Stack & principles

- LLM + embeddings: open-weight via OpenRouter, swappable in `.env`
  (`core/llm.py`, `core/embeddings.py`). Default `qwen/qwen3-235b-a22b-2507` /
  `openai/gpt-oss-120b`; embedding `baai/bge-m3` (1024D). Routing pinned to
  zero-data-retention providers (`openrouter_provider`, `config.py`).
- Orchestration: LangChain tool-calling, **not** LangGraph. `chain/answer.py`
  does two rounds in one turn: forced `search`, then streaming with tools
  forbidden.
- Hybrid retrieval: dense (BGE-M3) + sparse (BM25/IDF) via RRF.
- One Qdrant collection `chunks`; namespace is a payload field, not a separate
  collection (`indexing/qdrant_store.py`).
- Postgres as metadata store (conversations, documents, folders, users; Alembic
  migrations); original files content-addressed in `storage/blobs.py`.
- Docker. Dev `docker-compose.yml` (Qdrant, postgres, docling, pgweb); prod
  `docker-compose.prod.yml` (only `api` publishes a port; migrations/ingestion
  run in-container).
- Auth (`api/auth/`): stateless bearer JWT, no refresh and no revocation; the
  token carries only `user_id`. Roles (admin-defined capabilities + optional
  `is_superuser` bypass, `access/`) and ACL grants (groups + per-folder/
  per-document grants, union of ancestors, no deny) gate org files; retrieval
  is filtered by that ACL. Accounts are admin-provisioned only.
  Details: [Authorization & accounts](#authorization--accounts).

## Authorization & accounts

- **Token vs. database.** The token proves identity, the database proves the
  identity still holds: every request re-reads the account
  (`api/auth/dependencies.py:get_current_user`), one indexed PK lookup, so a
  deactivated account's existing token dies on its very next request. The
  same freshness rule drives the capability checks.
- **Accounts.** Provisioned by an admin with `MANAGE_USERS`
  (`/users`). Deletion is soft (`users.is_active`): login and every
  request reject a deactivated account, the row (and its reserved email
  address, so re-creating it 409s) stays, and an admin can reactivate
  (`DELETE` / `POST /users/{id}/activate`). Group membership is group data:
  reading which groups one user belongs to (`GET /users/{id}/groups`,
  `groups.py`'s second router under the shared `/users` prefix) requires
  `MANAGE_GROUPS`, not `MANAGE_USERS` — the same endpoints as the
  group-centric membership editor, only the read axis differs.
- **Passwords.** No reset flow: the account holder changes their own password
  (`POST /me/password`, requires the current password), an admin resets
  someone else's (`PUT /users/{id}/password`), and the first superuser
  comes from `scripts/create_user.py`.
- **The superuser boundary** (`api/routers/users.py:_assert_manageable`):
  nobody manages their own account (role change, deactivation, password
  reset), and a non-superuser with `MANAGE_USERS` cannot touch superuser
  accounts or hand out the superuser role — mirrored in the UI (selects and
  menus simply do not offer it), but authoritative only on the server (403).
- **Roles** (`/roles/*`) are superuser-only, and the superuser role itself is
  immutable — not renamable, editable or deletable even by a superuser
  (`api/routers/roles.py:_assert_editable`): the API cannot mint another
  superuser role (`is_superuser` is set only by the seed migration and the
  bootstrap script), so the seeded one is the deployment's only way back in.
- **ACL-filtered retrieval.** `role_id → role_capabilities` is re-read from
  the database on every capability check, so an admin's edit takes effect on
  the caller's very next request. ACL grants are read/write on folders
  (write implies upload/delete inside, and covers the whole subtree) but
  read-only on documents — `access/service.py:upsert_acl_entry` raises
  `InvalidAclGrantError` for a `write` grant on a document.
  Granting access is split by principal type: `MANAGE_GROUPS` to write a
  grant naming a group, `MANAGE_USERS` to write one naming a user
  (`api/routers/acl.py`) — reading a resource's grants is filtered the same
  way: a caller sees only grants of a principal type they can manage
  (superuser sees both), so a caller without `MANAGE_GROUPS` cannot learn
  which groups have access, server-side, not just in the UI. A superuser or
  a role holding `MANAGE_ORG_FILES_STRUCTURE`
  (`access/service.py:has_full_org_files_access`) has full org-files access:
  every resolver below is bypassed and every resource behaves as if
  write-granted. Setting or deleting a folder grant
  (`upsert_acl_entry`/`delete_acl_entry`) cascades: the principal's own
  direct grants on the folder's whole subtree (subfolders and documents) are
  pruned first, so a folder grant replaces per-file exceptions rather than
  layering on top of them.

  Two resolvers exist, and the distinction is load-bearing:
  `access/service.py:accessible_org_folder_ids` is the *retrieval* ceiling
  that `retrieval/search.py:_corpus_hits` restricts every `org_files` chunk
  to, while `visible_folder_ids` is the wider *navigation* ceiling used for
  browsing — it also surfaces ancestor folders of directly granted documents
  so the file browser and chat scope picker can show a path to a document
  without exposing that folder's other contents (**visible does not mean
  retrievable**, `access/member_view.py:folder_contents`). A member may
  narrow the retrieval ceiling further, per conversation, to a chosen
  subset of folders/documents (`conversations/service.py:create_conversation`,
  `search()`); narrowing is one decision about the whole selection — once
  either side is sent, the untouched side counts as narrowed to nothing,
  so unrelated direct grants never stay searchable next to a checked
  folder/document; full-access callers (superuser or
  `MANAGE_ORG_FILES_STRUCTURE`) bypass both resolvers entirely rather than
  being narrowed to their (typically empty) personal grants.
  `access/member_view.py` shapes the navigation ceiling into folders/
  documents for the member-facing views (`GET /me/org-files/*`), each node
  carrying the caller's own `effective_permission`/`is_structure_manager`
  that the file browser gates upload/delete/structure actions on.

## Layout

Monorepo: `backend/` (Python service; module map below) and `frontend/`
(React/Vite web UI — chat, source picker, org file upload — feature-first
structure under `src/features/*`, nginx static hosting in production via
`docker-compose.prod.yml`).

## Namespaces

| namespace               | content                                                                          | status  |
| ----------------------- | -------------------------------------------------------------------------------- | ------- |
| `laws`                  | Czech laws, chunked by structure (`docs/CHUNKING.md`)                            | done    |
| `org_files`             | internal firm docs, PDF/DOCX, Docling + Tesseract OCR (`docs/FILE_INGESTION.md`) | done    |
| `user_files`            | in-chat uploads, scoped to a conversation via `conversation_id`                  | done    |
| persistent `user_files` | 4th namespace: uploads outside conversations                                     | roadmap |

## Module map (`backend/src/law_agent/`)

- `ingestion/laws` — statute chunking; anchor = §, header embedded with text.
- `ingestion/files` — docling-serve + `HybridChunker`.
- `indexing/` — Qdrant store, BM25 sparse embedder, indexer, orphan cleanup.
- `retrieval/search.py` — `search()` tool; searches selected namespaces + the
  conversation's attachments.
- `chain/` — prompt, search tool, two-round `answer`, `[n]` citations.
- `conversations/`, `documents/`, `users/`, `access/`, `db/` — domain models +
  repos; `access/service.py` resolves the access ceiling (roles, ACL sets),
  `access/member_view.py` does the filtered folder/document traversal behind
  the member-facing `/me/org-files/*` views (roots, folder contents).
- `api/` — FastAPI: auth, users, roles, groups, acl, conversations,
  attachments, org files (capability-gated), member org files views
  (`me_org_files`, capability-free).
- `utils/` — cross-cutting helpers (rate limiting).

## Flow

```
question → request_search (tool_choice=required) → search() → stream_answer → [n] answer → archive
```

`search()` (`retrieval/search.py:44`) returns the conversation's attachments as
a first separate block, then corpus per `scope` (laws/org_files).

## Citations

Answer carries `[n]` marks; `n` is a ref bound to a chunk, unique per
conversation (`chain/citations.py`). Marks aren't stored — they're derived as
the intersection of marks found in the text and refs offered in the archive.
MVP cites the source document (+ §/page).

## Roadmap status

Done: RAG on one statute, backend API, in-chat attachments, conversation
archive, org files + folders, conversation-wide citations, ACL-filtered
`org_files` retrieval, per-conversation org files scope narrowing (chat
scope picker), read/write org files ACL semantics, path-to-root navigation.

Pending: persistent user files. The production web UI (chat + source-picker
sidebar + org file upload) lives in `frontend/`.

## Open decisions

- Agent loop over the two-round chain.
- Auth is MVP-minimal by design (see Stack & principles) and needs revisiting
  before this is more than an internal tool: token revocation/refresh.
- Whether user files go persistent (4th namespace).
