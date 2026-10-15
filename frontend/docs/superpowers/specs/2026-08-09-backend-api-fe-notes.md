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
- The token carries the role (`admin` / `member`), but the FE has no endpoint to ask "who am I".
  Decode the JWT's `role` claim client-side to decide which nav to render, and treat the `403`
  from the server as the real authority.

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
- The conversation's title is set automatically from the first message's text — nothing to send
  for title from the FE. **It is `""` in the create response and stays `""` in whatever you
  cached**: the title is written server-side during the first turn, so refetch
  `GET /conversations` after that turn if the sidebar should show it.
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

- One upload request per file: `POST /conversations/{id}/attachments` (multipart) — even when
  several files are dropped at once, fire one request per file, not a single batched request.
  The multipart field is named **`file`**; the response is `201` with
  `{id, filename, byte_size, status}`, where `status` is `pending` / `indexed` / `failed`.
- Each request blocks until the file is fully parsed and indexed server-side; the response only
  arrives once the attachment is actually usable. Drive the "uploading…" → "ready" UI state off
  that request's own lifecycle, not a separate polling/status check.
- Cancel a file mid-upload by aborting its specific request (`AbortController`). Remove an
  already-uploaded file with `DELETE /conversations/{id}/attachments/{attachment_id}`.
- UX we settled on: keep the send button enabled even while uploads are still in flight. Queue
  the actual `sendMessage` call until every pending upload for that turn has resolved, then fire
  it automatically — don't disable the button and make the user wait to click it.
- **There is no endpoint that lists a conversation's pending attachments.** The ids returned by
  the upload calls are the only record the FE gets, so hold them in component state until the
  message is sent. A page reload before sending loses the chips; the files stay on the server as
  orphans. Accepted for now.
- An attachment already used by a sent message cannot be deleted — `DELETE` answers `404`, the
  same as for an unknown id, because removing it would break that turn's citations. Only show
  the remove affordance on chips that have not been sent yet.
- Upload is synchronous and unbounded: a large scanned PDF is tens of seconds of OCR. Make sure
  the FE's fetch/proxy timeouts allow for it (Vercel's default function timeout in particular).

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
- A failure partway through generation shows up as an error part inside the stream, not as an
  HTTP error status (by that point headers are already sent and the status can't change). The
  `errorText` is a fixed Czech sentence safe to display verbatim; it never carries server detail.
- The failure modes that _do_ arrive as a status, because they are resolved before the first
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
- `messageId` is generated per response and is _not_ the archived message's id. Don't key
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
  part appended when that turn cited anything — **byte-identical to what the live stream sends**,
  so the citation renderer is written once and works for both paths.
- `id` here _is_ the stored message's id and is stable across reloads.
- There is no `GET /conversations/{id}`. Opening a thread means calling `/history`; the title
  and timestamps come from the sidebar list.

## Status codes and error bodies

| Code  | When                                                | Body                                     |
| ----- | --------------------------------------------------- | ---------------------------------------- |
| `401` | missing, malformed or expired token                 | `{"detail":"not authenticated"}`         |
| `401` | bad login credentials                               | `{"detail":"invalid email or password"}` |
| `403` | a member hitting an admin route                     | `{"detail":"insufficient role"}`         |
| `404` | unknown _or_ someone else's conversation/attachment | `{"detail":"…"}`                         |
| `409` | admin creating a duplicate email                    | `{"detail":"…"}`                         |
| `422` | schema validation                                   | FastAPI's array form, see below          |
| `500` | anything unexpected                                 | `{"detail":"internal server error"}`     |

`detail` is a **string on every code except `422`**, where it is FastAPI's array of field errors:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "question"],
      "msg": "String should have at least 1 character",
      "input": "",
      "ctx": { "min_length": 1 }
    }
  ]
}
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
