"""Chunking a parsed document: size decides, structure only advises.

Chunking runs here rather than in docling-serve on purpose: the token budget has
to match the embedding model, and that model is configured in this application,
not in the container. Keeping the policy here also makes it unit-testable and
lets a re-chunk reuse a cached parse instead of re-running OCR.

The work is split across three units -- the item stream, serialization and the
packer -- and this class only wires them together and gives the result identity.
"""

from __future__ import annotations

from docling_core.types.doc.document import DoclingDocument

from law_agent.ingestion.files.items import iter_items
from law_agent.ingestion.files.models import FileChunk
from law_agent.ingestion.files.packer import DEFAULT_SOFT_RATIO, PackedChunk, Packer
from law_agent.ingestion.tokenizer import TokenCounter, default_token_counter

DEFAULT_MAX_TOKENS = 768


class FileChunker:
    """Turns a :class:`DoclingDocument` into :class:`FileChunk` objects."""

    def __init__(
        self,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        token_counter: TokenCounter | None = None,
        soft_ratio: float = DEFAULT_SOFT_RATIO,
    ) -> None:
        self._counter = token_counter or default_token_counter()
        self._packer = Packer(budget=max_tokens, soft_ratio=soft_ratio, count_tokens=self._counter)

    def chunk(
        self,
        document: DoclingDocument,
        *,
        doc_id: str,
        filename: str,
        folder_id: str | None = None,
        conversation_id: str | None = None,
    ) -> list[FileChunk]:
        """Chunk ``document``, attributing every chunk to ``doc_id``.

        Args:
            document: A parsed document.
            doc_id: Identity of the source -- the uuid of its ``documents`` row.
                Drives ``chunk_id``, and therefore re-ingestion in place.
            filename: Name shown in citations. Passed in rather than derived,
                because a uuid carries no name.
            folder_id: Folder the document sits in, for the authorisation filter.
            conversation_id: Conversation an in-chat attachment belongs to, for
                the retrieval filter.

        Returns:
            Chunks in document order.
        """
        packed = self._packer.pack(iter_items(document))

        return [
            self._to_file_chunk(
                chunk,
                doc_id=doc_id,
                filename=filename,
                folder_id=folder_id,
                conversation_id=conversation_id,
                index=index,
                total=len(packed),
            )
            for index, chunk in enumerate(packed)
        ]

    def _to_file_chunk(
        self,
        chunk: PackedChunk,
        *,
        doc_id: str,
        filename: str,
        folder_id: str | None,
        conversation_id: str | None,
        index: int,
        total: int,
    ) -> FileChunk:
        return FileChunk.create(
            doc_id=doc_id,
            filename=filename,
            folder_id=folder_id,
            conversation_id=conversation_id,
            text=chunk.text,
            headings=[chunk.heading] if chunk.heading else [],
            pages=list(chunk.pages),
            chunk_index=index,
            chunk_total=total,
            token_count=self._counter(chunk.text),
        )
