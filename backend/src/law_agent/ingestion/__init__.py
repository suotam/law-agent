"""Ingestion pipelines and what they share.

Two sources live side by side and know nothing about each other:

- ``law_agent.ingestion.laws`` -- Czech laws from structured fragments
- ``law_agent.ingestion.files`` -- arbitrary documents parsed by Docling

This package exports only what both need: token counting and chunk identity.
Everything source-specific is imported from its own subpackage, so the boundary
between the two is visible at the import site.
"""

from law_agent.ingestion.identity import make_point_id
from law_agent.ingestion.tokenizer import (
    HeuristicTokenCounter,
    HuggingFaceTokenCounter,
    TokenCounter,
    default_token_counter,
)

__all__ = [
    "HeuristicTokenCounter",
    "HuggingFaceTokenCounter",
    "TokenCounter",
    "default_token_counter",
    "make_point_id",
]
