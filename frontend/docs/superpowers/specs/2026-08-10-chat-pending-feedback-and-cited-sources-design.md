# Chat: waiting feedback and cited-only sources

_Two changes to the existing chat screen described in `2026-08-10-frontend-auth-chat-design.md`.
Nothing about the API contract changes._

## Goal

Two gaps in the current turn:

1. **Nothing tells the user the turn is alive.** Between pressing send and the first token, the
   screen is silent. The wait is long enough to read as a broken app — especially when an
   attachment is still being processed before the question can even go out.
2. **Every retrieved source is listed, cited or not.** The backend returns whatever the retrieval
   step found; only a subset ends up referenced in the answer. Listing all of them buries the ones
   that matter and invites the user to trust a source the answer never used.

## Waiting feedback

A single indicator line, rendered below the last message, whose label depends on what is being
waited for.

| Condition                                                               | Label                    |
| ----------------------------------------------------------------------- | ------------------------ |
| `queuedQuestion !== null`                                               | "Zpracovávám dokumenty…" |
| `status === "submitted"`                                                | "Přemýšlím…"             |
| `status === "streaming"` and the last assistant message has no text yet | "Přemýšlím…"             |
| otherwise                                                               | not rendered             |

The indicator disappears on the first text token. A `data-sources` part arriving on its own does
**not** end it — sources land before the model starts writing, and the user is still waiting.

`queuedQuestion` today renders a hint line ("Odešle se po nahrání souborů.") under its own bubble.
That hint is replaced by this indicator: one place answers "what is happening", instead of two
half-answers in two positions.

### Component

`src/features/chat/PendingTurn.tsx` — a presentational component taking the resolved label. A
spinner (`LoaderCircle` with `animate-spin`, matching `AttachmentChips`) plus muted text, wrapped in
`aria-live="polite"` so a screen reader announces the phase change.

Phase resolution lives in `MessageList`, which already receives `queuedQuestion` and will now also
receive `status`. It is a pure function of props — no new state anywhere.

## Cited-only sources

### Which sources are shown

A source is shown when the answer text contains a `[n]` marker matching its `ref`. This is the same
rule `CitationText` already applies when deciding whether a marker becomes a button, so the list and
the in-text markers can never disagree.

If no marker matches, the section is not rendered at all. An answer that cites nothing shows no
sources.

### When they are shown

Filtering requires the whole answer: a source cited in the final paragraph would flicker in late if
the list were filtered per token. So while the turn is streaming, `SourceList` renders a single line
— "Zdroje načteny (4)" — in the place the list will occupy, and swaps to the filtered list when the
turn finishes. The section does not move.

The count comes from the `data-sources` part, so the line only appears once sources have actually
arrived; before that the section renders nothing.

### Knowing a message is finished

`AssistantMessage` gains an `isStreaming` prop. `MessageList` sets it for the last message when
`status` is `submitted` or `streaming`; every other message is finished by definition. History
rehydrated from `GET /conversations/{id}/messages` is therefore filtered like any finished turn,
with no separate path.

### Shared citation parsing

`MARKER_PATTERN` lives inside `CitationText` today. It moves to `src/features/chat/citations.ts`
alongside a new `collectCitedRefs(text: string): Set<number>`, used by `AssistantMessage` to filter
and by `CitationText` to substitute. One definition of "cited".

## i18n

New keys under `chat` in `src/assets/locales/cs.json`:

- `processingDocuments`: "Zpracovávám dokumenty…"
- `thinking`: "Přemýšlím…"
- `sourcesLoaded`: "Zdroje načteny ({{count}})"

`chat.queuedHint` is removed with the hint line it labelled.

## Testing

- `citations.test.ts` — `collectCitedRefs` on: no markers, repeated markers, markers with no
  matching source, multi-digit refs.
- `AssistantMessage.test.tsx` — streaming with sources shows the "Zdroje načteny" line and no list;
  finished shows only cited sources; finished with sources but no markers shows no section.
- `MessageList` (or `ChatScreen`) — the indicator renders "Zpracovávám dokumenty…" while a question
  is queued, "Přemýšlím…" after submit, and disappears once assistant text exists.

## Out of scope

A stop/abort control for a running turn, elapsed-time or progress detail in the indicator, and any
hover preview of a source's opaque `content` payload.
