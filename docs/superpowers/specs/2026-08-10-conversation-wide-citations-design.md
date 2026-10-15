# Conversation-wide citations and retained tool context

**Date:** 2026-08-10
**Status:** design

## Problem

Two limits of the current turn, and they share one cause.

Refs restart at `1` with every question (`service.ask` calls
`to_items(chunks, start_ref=1)`). A `[1]` in the third answer therefore names a
different source than a `[1]` in the first. Because numbers collide, the replay
has to drop the `tool_use` and `tool_result` blocks of every past turn
(`blocks._replay_turn(full=is_current)`) -- the model answering question three
cannot see what questions one and two retrieved, and cannot cite it.

Dropping those blocks also moves the prompt prefix between turns: material that
was in the request for turn N is gone from the request for turn N+1, so the
cache is invalidated near the start of the conversation rather than at its end.

## Goal

A `ref` identifies a source for the life of the conversation. The model sees
what earlier turns retrieved and used, and may cite it again. Only the material
it actually cited is carried forward, so the context window grows with the
answer, not with the search.

## Design

### Numbering

`ref` becomes an identifier unique within a conversation. Before each search,
the refs already handed out are read from the archive; a chunk the conversation
has seen keeps its number, a new chunk takes the next one.

`blocks.offered_items` already accepts any `Sequence[Message]` and returns
`ref -> SourceItem`. Called over the whole history instead of over one turn it
is the conversation's ref table -- no signature change, no migration.

`chain/citations.py` grows the assigning half of what it already resolves:

```python
class Numbering:
    """Refs already handed out in this conversation, and where to continue."""

    @classmethod
    def of(cls, offered: Mapping[int, SourceItem]) -> Numbering: ...

    def ref_for(self, chunk_id: str) -> int: ...
```

`chunk_id` is present in `content` for both item kinds (`law`, `document`), so
`chunk_id -> ref` is derivable from stored data.

`tools.to_items` takes a `Numbering` instead of `start_ref: int` and keeps its
own job -- mapping a `RetrievedChunk` payload onto a `SourceItem`. Numbers come
from `Numbering`, shapes from `tools`.

**`next_ref` is `max(ref in the archive) + 1`**, over everything *offered*, not
over what was cited; an empty conversation starts at `1`. Reusing the numbers of
uncited items would give a number a second meaning: the FE accumulates its
`ref -> source` map from every offered item the API sends it, so a reissued
`[4]` would resolve to the first turn's source. Dedup consumes no number, so no
gaps arise, but `max + 1` survives them if they ever do.

`Numbering` is mutable for the length of a turn rather than a value computed
once. A future agent loop calling `search` twice in one turn needs the second
call to continue from the first, before anything is stored.

### Storage

Unchanged. A `tool_result` block keeps every item the search offered, with its
ref. The archive stays complete: the source panel can show what was found, an
audit can see what the model was given and ignored, and the replay filter --
being a pure function over stored data -- can be changed later without a
migration. Pruning on write would save nothing in the context window, because
the context is the replay, not the database.

### Replay

Every turn now replays with the same shape: `AIMessage` carrying the
`tool_call`, then the `ToolMessage`, then the `AIMessage` with the answer. Past
turns differ from the current one only in the *content* of the `ToolMessage`:
its items are filtered to those whose mark appears in that turn's answer text,
via `used_refs`.

A turn's result is filtered by *its own* answer, not by later ones. A later
answer citing an older ref needs no exception: the item survives in the turn
that cited it first, and if no turn cited it, the model cannot have read it
there -- it reaches the model through the current turn's search instead, in
full, under its original number.

This removes machinery. The `full` flag on `_replay_turn` goes, and
`_assistant_text_only` with it: it existed only to drop a search round whose
tool blocks had been discarded, and a search round is no longer discarded.

Consequences:

- **Pairing.** A `ToolMessage` needs a preceding `AIMessage` with a matching
  `tool_call_id`, so the search round of a past turn must be replayed.
- **Empty result.** A turn whose answer cited nothing leaves an empty
  `ToolMessage`, which still cannot be omitted. It needs text distinct from the
  current `_NO_CONTEXT` ("no material was found"), because here material *was*
  found and went unused -- e.g. `(Z tohoto hledání nebyl citován žádný
  podklad.)`.
- **Prefix stability.** A past turn's filter depends only on that turn's answer
  text, which never changes again. Once a turn closes, its replay is frozen, so
  the cache breaks only at the tail where new content is appended anyway.

### Rendering the current turn

A chunk whose ref appears in some earlier answer is live in the context; the
search result renders it as a reference line only:

```
[3] § 1829 obč. zák. (uvedeno výše)
```

A chunk the conversation offered but nobody cited has been filtered out of the
replay; it renders in full under its original ref. The rule: **the number is
permanent, the text is printed exactly when it is not already in context.**

"Already in context" has to be decided the same way live and on replay, or the
prefix moves after all. It is therefore not a property of the moment but of the
position: an item prints in full in the *first* turn that cited it and as a
reference line in every later result that carries it. Rendering a past turn
takes the refs cited by turns *before* it, accumulated as the replay walks
forward -- which is exactly the set the current turn is rendered against.

### Prompt

Rule 2 gains that marks hold for the whole conversation and that material from
an earlier turn may be cited again. A new rule bounds the risk this opens: a
mark may only be used for material whose text is visible in the context. Without
it the model could hang a claim on a label it can no longer read.

### API

The contract does not change. The live stream still sends `data-sources` with
the items offered in that turn, before the first token -- at which point what
will be cited is not yet known, so filtering there is impossible anyway.

The FE accumulates `ref -> source` across the conversation and resolves marks
against that map rather than against one message's list. Dedup makes the write
idempotent: a rediscovered chunk arrives under the number it already has.

The per-answer source panel keeps showing the material *found* in that turn, not
only what was cited -- consistent with the archive staying complete.

`used_refs` receives the conversation-wide offered set as `offered` instead of
one turn's.

The Streamlit UI is not the target frontend, but `_render_sources` resolves
marks against a single turn and would silently drop cross-turn citations. It
gets the conversation-wide map -- a two-line change, for consistency only.

### Existing data

Stored conversations number refs per turn, so under the new rules their marks
would lie. They are deleted once, by hand, during implementation -- no script is
added to the repository. `documents.message_id` and `documents.conversation_id`
are `ondelete="RESTRICT"`, so the order is: conversation attachments (through
`delete_document`, which also clears the blob and the Qdrant points), then
`messages`, then `conversations`. Laws and firm documents are untouched.

## Testing

- `test_citations` -- `Numbering`: a new chunk takes the next ref, a known chunk
  keeps its own, `next_ref` continues past uncited items, an empty conversation
  starts at 1, numbering advances within a turn.
- `test_blocks` -- a past turn replays call, result and answer; its result holds
  only cited items; a turn that cited nothing keeps a paired but empty tool
  message; the current turn keeps everything.
- `test_conversations` -- a chunk found again in a later turn comes back under
  its first ref; an answer may cite a ref from an earlier turn.
- `test_prompt` -- a live chunk renders as a reference line, a filtered-out one
  in full; the empty-result text differs from `_NO_CONTEXT`.

## Out of scope

The agent loop itself. `Numbering` is built to survive several searches in one
turn, but `answer.py` keeps its two fixed rounds.
