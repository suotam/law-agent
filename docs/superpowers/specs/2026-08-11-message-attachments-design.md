# Attachments in the archive

## The problem

`documents.message_id` already records which turn used which file: `ask()` binds every
`attachment_id` to the user message it was sent with. Nothing reads it back. `GET /history`
serialises a user message as a single `text` part, so a client that reloads a thread cannot show
which files a past question carried.

The upload response is the FE's only record of an attachment, and it is discarded once the
message is sent.

## Scope

A user message in `GET /history` carries the files it was sent with. Display only: filename,
size and an icon derived from the media type.

Out of scope, deliberately:

- **Listing a conversation's pending attachments.** Files uploaded but not yet sent are the state
  of a draft, not of the archive; a reload still loses the chips, as the FE notes already record.
- **Downloading the original.** No endpoint serves an attachment's bytes, and this design does not
  add one.
- **Attachments as citation targets.** Unrelated to showing what was sent.

## The wire shape

A user message gains one part, before its `text` part:

```json
{
  "id": "…",
  "role": "user",
  "parts": [
    {
      "type": "data-attachments",
      "data": {
        "items": [
          {
            "id": "…",
            "filename": "smlouva.pdf",
            "mime": "application/pdf",
            "byte_size": 184320
          }
        ]
      }
    },
    { "type": "text", "text": "Co říká čl. 5?" }
  ]
}
```

A message with no attachments has no such part — never an empty `items`.

`data-attachments` rather than the protocol's `file` part: that part requires a `url`, and there
is nothing to serve behind one. The name follows `data-sources`, the custom part the same
serialisation already uses for citations.

`status` is not a field. `ingest_document` re-raises after marking a row `failed`, so a failed
upload answers the POST with an error and its id never reaches the client. An id that can appear
in `attachment_ids` is always an indexed one.

### The live turn

The stream does not emit this part, and cannot: a `data-*` frame is appended to the assistant
message being streamed, while these files belong to the question. The user message is built
optimistically on the client before the request leaves.

So the FE composes the part itself for the live turn. To make the two paths produce the same
shape, `AttachmentResponse` gains **`mime`** — the upload response then carries exactly the four
fields of an item, and a chip does not change appearance after a reload.

## Implementation

- `law_agent.api.streaming`: `attachments_part(documents)`, beside `sources_part`. Both custom
  data parts are shaped in one module.
- `law_agent.conversations.service`: `sent_attachments(conversation_id) -> dict[UUID, list[Document]]`
  — `list_by_conversation` grouped by `message_id`, dropping the rows where it is `NULL`. The
  existing `attachments()` returns the pending ones and is left alone: the two answer different
  questions, and merging them would make the FE read meaning out of a null.
- `_history_messages` takes that mapping as an argument and prepends the part to a `Role.USER`
  message that has entries.
- `AttachmentResponse` gains `mime: str`.

One extra query per `GET /history`. No schema change and no migration — the column exists.

## Testing

In `tests/api/test_history_api.py`:

- A message sent with attachments comes back with the part, its items in upload order.
- A message sent without them has no `data-attachments` part at all.
- A pending attachment — uploaded, never sent — appears against no message. This is what keeps the
  feature separate from listing a draft's files.

In `tests/api/test_attachments_api.py`: the upload response carries `mime`.

## Documentation

`docs/superpowers/specs/2026-08-09-backend-api-fe-notes.md`, the Attachments section: the new part
and its shape, the `mime` field on the upload response, and the fact that the part exists only in
history hydration — during a live turn the FE builds it from the upload responses it is holding.
