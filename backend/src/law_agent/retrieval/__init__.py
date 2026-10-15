"""Hybrid (dense + sparse) retrieval over the `chunks` Qdrant collection."""

from law_agent.ingestion.files import NAMESPACE as FILES_NAMESPACE
from law_agent.ingestion.laws import NAMESPACE as LAWS_NAMESPACE
from law_agent.retrieval.retriever import RetrievedChunk, query_chunks
from law_agent.retrieval.search import (
    DEFAULT_SCOPE,
    ScopeSource,
    search,
)

__all__ = [
    "DEFAULT_SCOPE",
    "FILES_NAMESPACE",
    "LAWS_NAMESPACE",
    "RetrievedChunk",
    "ScopeSource",
    "query_chunks",
    "search",
]
