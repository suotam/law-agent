"""Tests for the search tool's schema and for numbering its results."""

from __future__ import annotations

import pytest

from law_agent.chain.citations import Numbering
from law_agent.chain.tools import SEARCH_TOOL, SEARCH_TOOL_NAME, to_items
from law_agent.retrieval import RetrievedChunk


def _law_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        score=0.9,
        chunk_id="c1",
        citation="§ 1829 obč. zák.",
        text="Spotřebitel má právo odstoupit od smlouvy…",
        payload={
            "namespace": "laws",
            "chunk_id": "c1",
            "citation": "§ 1829 obč. zák.",
            "law_id": "/eli/cz/sb/2012/89/2026-01-01",
            "anchor_fragment_id": "/eli/cz/sb/2012/89/2026-01-01/norma/par_1829",
        },
    )


def _file_chunk(namespace: str = "org_files") -> RetrievedChunk:
    return RetrievedChunk(
        score=0.8,
        chunk_id="d1#4",
        citation="smlouva.pdf, s. 4 – Odstoupení",
        text="Smluvní strany se dohodly…",
        payload={
            "namespace": namespace,
            "chunk_id": "d1#4",
            "citation": "smlouva.pdf, s. 4 – Odstoupení",
            "doc_id": "d1",
            "filename": "smlouva.pdf",
            "pages": [4],
        },
    )


def test_the_model_may_only_choose_the_query() -> None:
    """Scope is the user's choice and, with roles, an authorisation boundary --
    it is never handed to the model."""
    parameters = SEARCH_TOOL["function"]["parameters"]

    assert SEARCH_TOOL["function"]["name"] == SEARCH_TOOL_NAME
    assert set(parameters["properties"]) == {"query"}
    assert parameters["required"] == ["query"]


def test_the_tool_describes_itself_to_the_model() -> None:
    assert SEARCH_TOOL["function"]["description"].strip()


def test_a_law_chunk_becomes_a_law_item() -> None:
    item = to_items([_law_chunk()], numbering=Numbering.of({}))[0]

    assert item.ref == 1
    assert item.kind == "law"
    assert item.label == "§ 1829 obč. zák."
    assert item.content == {
        "chunk_id": "c1",
        "law_id": "/eli/cz/sb/2012/89/2026-01-01",
        "anchor": "/eli/cz/sb/2012/89/2026-01-01/norma/par_1829",
        "text": "Spotřebitel má právo odstoupit od smlouvy…",
    }


@pytest.mark.parametrize("namespace", ["org_files", "user_files"])
def test_a_file_chunk_becomes_a_document_item(namespace: str) -> None:
    """An in-chat attachment resolves through the same click-through as an org
    file: both are rows in ``documents``."""
    item = to_items([_file_chunk(namespace)], numbering=Numbering.of({}))[0]

    assert item.kind == "document"
    assert item.content == {
        "chunk_id": "d1#4",
        "doc_id": "d1",
        "filename": "smlouva.pdf",
        "pages": [4],
        "text": "Smluvní strany se dohodly…",
    }


def test_a_rediscovered_chunk_comes_back_under_its_first_ref() -> None:
    """Two turns, one chunk: the model must not meet the same paragraph under
    two numbers."""
    numbering = Numbering.of({})
    first = to_items([_law_chunk()], numbering=numbering)

    second = to_items([_file_chunk(), _law_chunk()], numbering=numbering)

    assert first[0].ref == 1
    assert [item.ref for item in second] == [2, 1]


def test_new_chunks_continue_the_conversation_s_numbering() -> None:
    numbering = Numbering(by_chunk={"c1": 1}, next_ref=11)

    items = to_items([_file_chunk()], numbering=numbering)

    assert items[0].ref == 11


def test_an_unknown_namespace_is_an_error_not_a_silent_fallback() -> None:
    chunk = RetrievedChunk(
        score=0.5, chunk_id="x", citation="?", text="?", payload={"namespace": "web"}
    )

    with pytest.raises(ValueError, match="web"):
        to_items([chunk], numbering=Numbering.of({}))
