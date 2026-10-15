"""The ``search`` tool: what the model may ask for, and what it gets back.

The model never executes this tool. The spec here is a schema the model calls
against; the orchestration performs the retrieval itself, because ``scope`` and
``limit`` come from the conversation, not from the model. Were the model to
pick the scope, a user could switch the statutes off and still be answered from
them -- and with roles, the scope is an authorisation boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from law_agent.chain.citations import Numbering
from law_agent.conversations.models import SourceItem
from law_agent.documents.models import Namespace
from law_agent.retrieval import FILES_NAMESPACE, LAWS_NAMESPACE, RetrievedChunk

SEARCH_TOOL_NAME = "search"

_DESCRIPTION = (
    "Vyhledá podklady v indexovaných zdrojích (zákony, dokumenty kanceláře, "
    "přílohy této konverzace) a vrátí očíslované úryvky, ze kterých se odpovídá."
)

_DOCUMENT_NAMESPACES = frozenset({FILES_NAMESPACE, str(Namespace.USER_FILES)})


class SearchArgs(BaseModel):
    """The one argument the model controls."""

    query: str = Field(
        description=(
            "Vyhledávací dotaz. Zachovej odborné termíny z otázky uživatele "
            "doslovně; vyhledávání je z poloviny lexikální."
        )
    )


SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": SEARCH_TOOL_NAME,
        "description": _DESCRIPTION,
        "parameters": SearchArgs.model_json_schema(),
    },
}


def to_items(chunks: Sequence[RetrievedChunk], *, numbering: Numbering) -> list[SourceItem]:
    """Number retrieved chunks and flatten them into stored source items.

    Numbering happens here, before the model is shown anything, because the
    prompt lists the material under exactly these numbers. The numbers come
    from ``numbering``, which knows what the conversation has already handed
    out: a chunk found again keeps its ref.

    Raises:
        ValueError: A chunk comes from a namespace with no mapping. A new
            source has to supply its mapping deliberately -- a silent fallback
            would produce citations that resolve nowhere.
    """
    return [_to_item(chunk, ref=numbering.ref_for(chunk.chunk_id)) for chunk in chunks]


def _to_item(chunk: RetrievedChunk, *, ref: int) -> SourceItem:
    namespace = chunk.payload.get("namespace")
    if namespace == LAWS_NAMESPACE:
        return SourceItem(
            ref=ref,
            kind="law",
            label=chunk.citation,
            content={
                "chunk_id": chunk.chunk_id,
                "law_id": _text(chunk, "law_id"),
                "anchor": _text(chunk, "anchor_fragment_id"),
                "text": chunk.text,
            },
        )
    if namespace in _DOCUMENT_NAMESPACES:
        return SourceItem(
            ref=ref,
            kind="document",
            label=chunk.citation,
            content={
                "chunk_id": chunk.chunk_id,
                "doc_id": _text(chunk, "doc_id"),
                "filename": _text(chunk, "filename"),
                "pages": _pages(chunk),
                "text": chunk.text,
            },
        )
    msg = f"No source mapping for namespace {namespace!r}"
    raise ValueError(msg)


def _text(chunk: RetrievedChunk, key: str) -> str:
    value = chunk.payload.get(key)
    return str(value) if value is not None else ""


def _pages(chunk: RetrievedChunk) -> list[int]:
    value = chunk.payload.get("pages")
    return [int(page) for page in value] if isinstance(value, list) else []
