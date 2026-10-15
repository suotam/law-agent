"""LLM and embedding client factories."""

from law_agent.core.embeddings import OpenRouterEmbeddings, get_embeddings
from law_agent.core.llm import get_llm

__all__ = [
    "OpenRouterEmbeddings",
    "get_embeddings",
    "get_llm",
]
