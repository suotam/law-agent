"""Pluggable token counting.

Chunk sizes are budgeted in tokens, not characters, because the embedding model
has a token limit. Counting is behind a :class:`TokenCounter` protocol so the
chunker stays dependency-free and testable: the default is a calibrated
heuristic, and :class:`HuggingFaceTokenCounter` swaps in the real tokenizer of
the deployed embedding model when exactness matters.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# Czech legal prose under the XLM-RoBERTa vocabulary (BAAI/bge-m3 and friends)
# runs at roughly 3.2-3.6 characters per token. A deliberately low value makes
# the heuristic over-estimate token counts, so chunks stay under the real limit.
DEFAULT_CHARS_PER_TOKEN = 3.0


@runtime_checkable
class TokenCounter(Protocol):
    """Anything that can report the token length of a string."""

    def __call__(self, text: str) -> int: ...


class HeuristicTokenCounter:
    """Character-ratio estimator with a small per-line overhead.

    Fast, deterministic and dependency-free -- good enough for planning chunk
    boundaries, and intentionally conservative so that estimates round upwards.
    """

    __slots__ = ("chars_per_token",)

    def __init__(self, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN) -> None:
        if chars_per_token <= 0:
            msg = "chars_per_token must be positive"
            raise ValueError(msg)
        self.chars_per_token = chars_per_token

    def __call__(self, text: str) -> int:
        if not text:
            return 0
        # Each newline becomes at least one token, so count them separately.
        newlines = text.count("\n")
        return int(len(text) / self.chars_per_token) + newlines + 1


class HuggingFaceTokenCounter:
    """Exact counts from a Hugging Face tokenizer, with an in-memory cache.

    Requires ``transformers`` (not a project dependency -- install it only if
    you want exact budgeting):

        >>> counter = HuggingFaceTokenCounter("BAAI/bge-m3")  # doctest: +SKIP
    """

    __slots__ = ("_cache", "_tokenizer")

    def __init__(self, model_name: str) -> None:
        try:
            from transformers import AutoTokenizer  # pyright: ignore[reportMissingImports]
        except ImportError as error:  # pragma: no cover - optional dependency
            msg = "HuggingFaceTokenCounter requires the 'transformers' package"
            raise RuntimeError(msg) from error

        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._cache: dict[str, int] = {}

    def __call__(self, text: str) -> int:
        cached = self._cache.get(text)
        if cached is None:
            cached = len(self._tokenizer.encode(text, add_special_tokens=True))
            self._cache[text] = cached
        return cached


class CachingTokenCounter:
    """Memoizing wrapper -- the planner measures the same subtree repeatedly."""

    __slots__ = ("_cache", "_inner")

    def __init__(self, inner: TokenCounter) -> None:
        self._inner = inner
        self._cache: dict[str, int] = {}

    def __call__(self, text: str) -> int:
        cached = self._cache.get(text)
        if cached is None:
            cached = self._inner(text)
            self._cache[text] = cached
        return cached


def default_token_counter() -> TokenCounter:
    """The counter used when a caller does not supply one."""
    return CachingTokenCounter(HeuristicTokenCounter())
