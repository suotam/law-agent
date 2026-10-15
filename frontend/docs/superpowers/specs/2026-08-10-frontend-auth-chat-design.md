# Frontend: authentication and chat

_Design for the first two slices of the Law Agent frontend: the auth flow and the chat screen with
source selection. Companion to `2026-08-09-backend-api-fe-notes.md`, which is the authority on the
API contract._

## Goal

A React SPA where a member signs in, opens a chat thread, picks which corpora the agent may search,
attaches documents, and reads a streamed answer with working citations.

Out of scope for this spec: the admin section (`/admin/users`), dark mode, per-file selection inside
`org_files`, and any language other than Czech. Each is accounted for in the architecture so it can
be added without rework.

## Backend constraints that shape the design

Four properties of the API drive most decisions here.

**The retrieval scope is frozen onto a thread at creation.** `POST /conversations` accepts
`{scope, limit}` and never accepts them again. Source selection is therefore a one-time act before
the first question, not a control the user operates during a conversation.

**A conversation is created lazily.** Whichever comes first — the first attachment or the first
message — triggers `POST /conversations`. Ids are never generated client-side.

**Streaming does not go through axios.** `useChat` streams over `fetch`, so the existing axios
interceptor in `src/lib/api-client.tsx` covers neither the auth header nor the 401 handling for the
chat endpoint.

**`detail` is a string on every status except `422`,** where it is FastAPI's array of field errors.

### Endpoints missing from the API notes

Two endpoints the design relies on postdate `2026-08-09-backend-api-fe-notes.md` and are not
described there. Both exist:

- `GET /auth/me` → `UserResponse` (`id`, `email`, `role`, `created_at`). Used to validate the token.
  Note the `/auth` prefix, shared with `POST /auth/login`.
- `GET /conversations/{id}` → `ConversationDetail` = `ConversationResponse` plus `scope: list[str]`
  and `limit: int`. Used to show which sources a thread was created with. This supersedes the note's
  claim that "there is no `GET /conversations/{id}`".

Two further points where this spec overrides the notes, both verified against the backend source:

- The notes say `POST /conversations` takes `{}`. It does, but an absent `scope` means _both_
  corpora, not none — see "Lazy thread creation".
- The notes present `AttachmentResponse.status` as reaching the frontend as `pending` / `indexed` /
  `failed`. In practice only `indexed` ever arrives; a failure is a `500` — see "Attachments".

`scope` values are the enum `laws` and `org_files`. `limit` is a server-side RAG tuning parameter:
the frontend never sends it and never shows it.

## Architecture

### Layout

```
src/
  app/routes/          login.tsx, chat.tsx, chat.$id.tsx
  features/
    auth/              api, useAuth, useLogin, LoginForm, token store
    conversations/     api, useConversations, ConversationList
    chat/              transport, useChatSession, message rendering, citations
    attachments/       api, useAttachmentUploads, AttachmentChips
  components/ui/       shadcn primitives
  lib/                 api-client, react-query, errors
```

Each feature owns its API calls, types, and components. Components never touch `apiClient`
directly; they go through their feature's hook. This keeps the chat screen testable against a mocked
hook and lets any feature's data layer change without touching UI.

### Routes

| Path        | Guard                                          |
| ----------- | ---------------------------------------------- |
| `/login`    | public; redirects an authenticated user to `/` |
| `/`         | protected — empty "new chat" screen            |
| `/chat/:id` | protected — an existing thread                 |

`ProtectedRoute` already exists and gains one behaviour: it remembers the attempted path so an
expired token returns the user where they were.

### Authentication

The token lives in a Zustand store mirrored to `localStorage`. It is not server state, so keeping it
in React Query would mean `queryClient.clear()` on logout could drop it mid-flight.

`useAuth` validates the token against `GET /auth/me` rather than decoding the JWT:

- The query is disabled when no token is present.
- `isAuthenticated` means the query succeeded; `isLoadingAuth` means it is in flight — the branch
  `ProtectedRoute` already has.
- `staleTime: Infinity`, no refetch on focus. The user does not change during a session.
- A `401` from `/auth/me` means a dead token: clear storage, redirect to login.
- `user.role` (`admin` | `member`) is exposed now even though no screen consumes it yet.

The app therefore waits on a roundtrip before its first paint. `Loading` is delayed ~200 ms so it
does not flash on a fast connection.

Because token access is needed by both axios and `fetch`, the token getter and the `onUnauthorized`
handler live in `features/auth` as plain functions over the store. The axios interceptor and the AI
SDK transport each read from there — one source of truth, two consumers.

The login form validates the email client-side. Without it a malformed address returns `422` with
FastAPI's array shape rather than the `401` the user expects. A wrong password and an unknown
account return identical responses by design, so there is exactly one message:
"Nesprávný e-mail nebo heslo." There is no registration or password reset, so the screen links to
neither.

Forms use `react-hook-form` + `zod` + `@hookform/resolvers`; shadcn's `form` component is built on
them, which supplies error wiring and accessibility. Validation messages are i18n keys, not literals
inside the schema.

### Localisation

The UI is Czech-only, but every user-visible string goes through `react-i18next` — including
`aria-label`s, placeholders, `title` attributes, and error-code mappings. No literal in JSX.
`cs.json` is split into per-feature namespaces: `auth.*`, `chat.*`, `sources.*`, `errors.*`.

## Chat data flow

Adds `ai` and `@ai-sdk/react` to the project.

### Transport

`useChat` posts an array of messages to a fixed URL; the API wants a per-thread URL and a different
body. A `DefaultChatTransport` with `prepareSendMessagesRequest` maps between them:

```
api:  /conversations/{id}/messages
body: { question: <text of the last user message>, attachment_ids: [...] }
```

`DefaultChatTransport` is required rather than `TextStreamChatTransport` — the backend speaks the
data stream protocol, which the `x-vercel-ai-ui-message-stream: v1` header advertises.

### Lazy thread creation

The transport needs an id when it builds the URL, but the thread does not exist until the user acts.
Creating it inside the transport invites a race where an upload and a send each create one.

Instead `useChatSession` owns a single `ensureConversation()`. The first caller — upload or send —
starts the request and stores the pending promise in a ref, so a second caller awaits the first.
The resolved id lands in a ref the transport reads synchronously.

`ensureConversation()` is the only place that sends `scope`, and it **always sends it explicitly,
including as an empty array.** This matters: the server's own default when `scope` is absent is
_both_ corpora (`laws, org_files`), the opposite of this design's "nothing selected by default", and
the router distinguishes a missing `scope` from `[]`. Posting `{}` would silently give the user a
thread searching everything. So the body is `{scope: [...]}` built from the chips as they stand at
that moment, with `limit` omitted so the server default applies. Because
this fires on the first attachment as well as the first message, a user who attaches a file before
touching the chips freezes an empty scope onto the thread.

That creates a trap: the chips would still look editable while the thread's scope is already
settled, and toggling one afterwards would silently do nothing. So **the chips lock the moment
`ensureConversation()` resolves**, not when the first message is sent — on the new-chat screen
exactly as they do inside a thread, with the same "Nový chat s jinými zdroji" popover. Attaching a
file is therefore a commitment to the current source selection, and the composer says so before the
first upload: the chips carry a hint that sources lock once a file is attached.

After the first message in a new thread the app calls `navigate("/chat/" + id, { replace: true })`
and invalidates the conversation list: the title is generated server-side from the first message and
is still `""` in the `POST` response.

### Attachments

One request per file, even when several are dropped at once; the multipart field is `file`. Each
request blocks until the file is parsed and indexed — a scanned PDF can take tens of seconds — so
the chip's state is driven by that request's own lifecycle, with no polling. Cancelling aborts that
request via `AbortController`.

**A failed ingest arrives as `500`, not as `status: "failed"`.** The service re-raises after marking
the document failed, so the response either succeeds with `status: "indexed"` or never comes at all.
The chip's error state therefore hangs off the rejected request, and the frontend does not branch on
`status`. The message is necessarily generic — the `500` body carries no server detail, so it cannot
say "unsupported format" or "OCR failed". Wording: "Soubor se nepodařilo zpracovat." with a retry
that re-uploads the same file.

The send button stays enabled during uploads. Pressing it queues the message, which is sent
automatically once the last upload resolves; this needs a wrapper around `sendMessage` because
`useChat` has no knowledge of that state.

Attachment ids live only in component state — no endpoint lists a thread's pending attachments. A
reload before sending loses the chips and orphans the files server-side. Accepted. The remove
affordance appears only on chips that have not been sent, because an attachment used by a sent
message cannot be deleted.

### Opening an existing thread

`GET /conversations/{id}/history` returns `[{id, role, parts}]` — already the shape `useChat`
hydrates from. Switching threads passes a new `id` prop to `useChat` so state stays separated and
messages do not leak between conversations.

### Citations

`data-sources` is a custom data part: in `useChat` it arrives as a part of type `data-sources`, not
one of the SDK's built-in `source-*` parts. The answer text carries `[n]` markers whose `n` matches
`ref` in that part. The renderer splits the text on `[n]` and substitutes a link.

The stream and the history endpoint emit that part identically, so the citation renderer is written
once and serves both.

A source item is `{ref, kind, label, content}`. **`label` is the human-readable string and the only
field rendered** — e.g. "§ 1829 obč. zák.". `content` is an opaque dict shaped by whichever tool
produced the hit; it is never rendered, and rendering it would print `[object Object]`. `kind` is
`law` or `document` and decides where the link points.

Answer text is rendered as markdown via `react-markdown`, since legal answers use lists, bold
paragraph names, and paragraph breaks. Citation-marker substitution runs inside the markdown
renderer's text nodes so the two do not fight over the same string.

## Screen layout

```
┌──────────────┬────────────────────────────────────────┐
│ Law Agent    │  Rozbor smlouvy o dílo          [Zákony]│
│ [+ Nový chat]│────────────────────────────────────────│
│              │                                        │
│ · Výpověď…   │      ⟨ messages, max-w 48rem ⟩         │
│ · Reklamace… │                                        │
│ · Nájemní…   │                                        │
│              │────────────────────────────────────────│
│ ─────────    │  [📎] Zeptejte se…            [Odeslat] │
│ jan@fir.cz ⌄ │                                        │
└──────────────┴────────────────────────────────────────┘
```

**Left sidebar** — "Nový chat", a flat list of threads (no date grouping), the account with logout at
the bottom. Collapsible; a drawer on mobile. Thread names are single-line and truncate with an
ellipsis, full name in the tooltip. Threads the backend returns without a title render as
"Bez názvu". The list is capped at 50 with no pagination, so a quiet note closes it: "Zobrazeno
posledních 50 konverzací" — otherwise older threads look like a bug. Deleting is a hover icon with
confirmation; it is a soft delete on the server but the frontend cannot undo it.

**New chat screen (`/`)** — a centred composer with a heading above it and two independent toggle
chips below it: "Zákony" and "Firemní soubory". Both are off by default and both can be on at once
(`scope` is a list). This is where sources get space and attention, because this is where they are
decided.

**Open thread (`/chat/:id`)** — the same sources appear as inert labels in the header. Clicking them
opens a small popover: "Zdroje jsou pro tuto konverzaci zafixované." with a "Nový chat s jinými
zdroji" action that prefills the new-chat screen with the current selection. The scope is read from
`ConversationDetail`.

### Where per-file selection will go

When the backend gains an endpoint for browsing folders and files, the "Firemní soubory" chip gains
a secondary affordance that opens a **modal** with the tree.

A modal rather than a right sidebar: because scope is frozen at creation, the selection is a
one-time act before the first question, so a permanent sidebar would consume width for a control
that is inert most of the time. The left sidebar is too narrow for a tree and would mix two
unrelated concerns. A modal gives the tree full width exactly when it is needed.

The rules already agreed for that stage: nothing is selected by default, and whole folders may be
selected but not "all files" at once.

### The "scope or attachment" rule

A thread is created even with an empty scope; nothing blocks there. The check sits at message send:
with no source enabled and no attachment on the turn, the message does not go.

The button is not disabled — a disabled button with no explanation is a dead end. A line appears
above the composer instead: "Vyberte zdroje nebo přiložte dokument — jinak nemá agent v čem hledat."
with the chips highlighted, showing both cause and remedy.

In-flight uploads satisfy the rule, so a message typed during an upload is accepted and sent when
the upload resolves.

## Visual design

Direction: a dark navy chrome around a light working surface — sidebar and header in
`oklch(0.28 0.05 250)`, softer radii (10 px), a subtle shadow on the composer.

### Token layers

Three layers, so re-theming is one edit rather than a hunt through components.

**Layer 1 — primitives.** Raw values with no meaning, in their own block in `globals.css`, never
referenced from JSX:

```css
--navy-900, --navy-800, --navy-100
--slate-50 … --slate-900
--amber-500   /* signal, warnings */
--red-600
--radius-base: 0.625rem;
```

**Layer 2 — semantic.** Assigns primitives a role. This layer _is_ the shadcn contract, so
`--background`, `--foreground`, `--primary`, `--border`, `--destructive` keep exactly the names
shadcn components expect — they are just filled from layer 1 instead of literals. `--warning` is
added, since shadcn has no such token.

**Layer 3 — component.** For places with their own visual identity, continuing the precedent shadcn
already sets with `--sidebar-*`:

```css
--sidebar, --chat-user-bubble, --chat-assistant-bg,
--citation-fg, --citation-marker-bg, --source-chip-active-bg
```

**The rule that holds it together: JSX references layers 2 and 3 only, never layer 1.** Typography,
spacing, and radii follow the same structure, exposed as utilities through Tailwind 4's
`@theme inline`.

Dark mode is not built now, but the `.dark` block exists in the token file from the start so adding
it later is a palette rewrite rather than a component pass.

The visual work itself is carried out under the `frontend-design` skill during implementation.

## Error handling

One translator in `lib/errors.ts`, because `detail` is a string on every status except `422`, where
it is an array of field errors. Without it something renders `[object Object]`. It returns an i18n
key, not a finished sentence.

- **`401`** — one global reaction: log out and redirect. Never shown as a message.
- **`422` on a form** — mapped to a specific field through `loc` and handed to react-hook-form.
- **`404` from `GET /conversations/{id}` or `/history`** — the thread is gone (deleted, or someone
  else's; the backend deliberately does not distinguish). Redirect to `/` with a quiet notice, not
  an error panel.
- **`404` from `POST /conversations/{id}/messages`** — _not_ a missing thread. The send endpoint also
  answers `404` for an `attachment_id` that is not a pending attachment of this conversation, so
  treating it as "thread gone" would throw the user out of a live conversation over a stale chip.
  Handled as a failed turn in place: the message stays in the composer, the offending chips are
  dropped, and the user can send again.
- **`error` part in the stream** — rendered in place below whatever text arrived, with a "Zkusit
  znovu" action. `errorText` is displayed verbatim; it is a prepared Czech sentence carrying no
  server detail.
- **`500` / network** — a generic message. No attempt to extract detail; the server deliberately
  includes none.

## Testing

Vitest + Testing Library, with MSW mocking the API. Three places hold real logic:

1. **`ensureConversation`** — a concurrent upload and send must create exactly one conversation, and
   the request body must always carry `scope`, including `[]` when no chip is on.
2. **The send queue** — a message typed during an upload is sent only after that upload resolves,
   and carries its `attachment_id`.
3. **The error translator** — `422` array vs. string `detail` vs. an empty body.

Plus a rendering test for citations: the same `data-sources` part must produce identical output
whether it came from the stream or from history. Components without logic are not tested.

## Implementation phases

1. Design tokens and the app shell.
2. Auth: token store, `/me`, `useAuth`, login screen, route guards.
3. Chat: transport, `useChatSession`, streaming, markdown, citations.
4. Sidebar: conversation list, opening threads, deleting.
5. Sources: chips, the frozen-scope header, the "scope or attachment" rule.
6. Attachments: uploads, chips, the send queue.

## Accepted gaps

- A reload before sending loses attachment chips and orphans the uploaded files server-side.
- The conversation list is capped at 50; older threads are unreachable.
- The list may include empty, untitled threads. Known backend gap, not worked around here.
- A stream aborted mid-generation leaves the question stored with no answer, and history will show
  exactly that.
