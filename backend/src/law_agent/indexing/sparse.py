"""Local BM25 sparse vectors via FastEmbed — no network, no ML inference.

Purely statistical (IDF-weighted term frequency), so it needs no API key and
runs on CPU. The model file itself is downloaded from Hugging Face once and
cached under ``~/.cache/fastembed``.

Known limitation: FastEmbed's BM25 tokenizer defaults to English (Czech isn't
in its ``supported_languages``), so it stems with an English Snowball
stemmer and strips ``§`` as punctuation — e.g. a query for ``§ 52 písm. c)``
degrades to the bare token ``52``. This is consistent between indexing and
querying (both sides use the same tokenizer), so it doesn't break matching,
but it does mean Czech inflected forms and legal symbols get less precise
sparse matching than a language-aware tokenizer would give. Revisit if
retrieval quality on symbol-heavy queries (``§``, "písm.") proves
insufficient in practice.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from fastembed import SparseTextEmbedding

_MODEL_NAME = "Qdrant/bm25"


@dataclass(frozen=True, slots=True)
class SparseVector:
    """Token index -> weight, in the shape Qdrant's sparse vectors expect."""

    indices: list[int]
    values: list[float]


class Bm25SparseEmbedder:
    """Wraps FastEmbed's BM25 model with the same batch/single shape as
    :class:`law_agent.core.embeddings.OpenRouterEmbeddings`."""

    def __init__(self) -> None:
        self._model = SparseTextEmbedding(model_name=_MODEL_NAME)

    def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        return [
            SparseVector(indices=embedding.indices.tolist(), values=embedding.values.tolist())
            for embedding in self._model.embed(texts)
        ]

    def embed_query(self, text: str) -> SparseVector:
        return self.embed_documents([text])[0]


@lru_cache(maxsize=1)
def get_sparse_embedder() -> Bm25SparseEmbedder:
    """Cached because constructing the embedder loads the BM25 model from disk."""
    return Bm25SparseEmbedder()
