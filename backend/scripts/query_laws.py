"""Index data/laws/*.json into Qdrant and run a hybrid query against it.

Requires a running Qdrant (see docker-compose.yml): `docker compose up -d`.

uv run scripts/query_laws.py "kdy musí zaměstnavatel převést zaměstnance na jinou práci"
uv run scripts/query_laws.py "§ 52 písm. c)" --limit 10
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from qdrant_client import QdrantClient

from law_agent.config import settings
from law_agent.core import OpenRouterEmbeddings, get_embeddings
from law_agent.indexing import (
    Bm25SparseEmbedder,
    ensure_collection,
    get_qdrant_client,
    index_chunks,
)
from law_agent.ingestion.laws import LawChunker, LawDocument
from law_agent.retrieval import RetrievedChunk, query_chunks

REPO_ROOT = Path(__file__).resolve().parent.parent
LAWS_DIR = REPO_ROOT / "data" / "laws"
RESULTS_DIR = REPO_ROOT / "data" / "query_results"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("query", help="search text")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--namespace", default="laws")
    parser.add_argument("--collection", default=settings.qdrant_collection)
    return parser


def index_all_laws(
    client: QdrantClient,
    *,
    collection_name: str,
    embeddings: OpenRouterEmbeddings,
    sparse_embedder: Bm25SparseEmbedder,
    namespace: str,
) -> None:
    for path in sorted(LAWS_DIR.glob("*.json")):
        document = LawDocument.from_json(path)
        chunks = LawChunker().chunk(document)
        stats = index_chunks(
            client,
            chunks,
            collection_name=collection_name,
            embeddings=embeddings,
            sparse_embedder=sparse_embedder,
            namespace=namespace,
        )
        print(f"{path.name}: embedded {stats.embedded}, skipped {stats.skipped} (of {stats.total})")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    client = get_qdrant_client()
    ensure_collection(client, args.collection)
    embeddings = get_embeddings()
    sparse_embedder = Bm25SparseEmbedder()

    index_all_laws(
        client,
        collection_name=args.collection,
        embeddings=embeddings,
        sparse_embedder=sparse_embedder,
        namespace=args.namespace,
    )

    results = query_chunks(
        client,
        args.query,
        collection_name=args.collection,
        embeddings=embeddings,
        sparse_embedder=sparse_embedder,
        namespace=args.namespace,
        limit=args.limit,
    )

    for rank, result in enumerate(results, start=1):
        print(f"\n#{rank} [{result.score:.4f}] {result.citation}")
        print("  " + result.text.replace("\n", "\n  "))

    _write_results(args.query, args.namespace, results)
    return 0


def _write_results(query: str, namespace: str, results: list[RetrievedChunk]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    payload = {
        "query": query,
        "namespace": namespace,
        "results": [
            {
                "score": result.score,
                "chunk_id": result.chunk_id,
                "citation": result.citation,
                "law_citation": result.payload.get("law_citation"),
                "text": result.text,
            }
            for result in results
        ],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {len(results)} results -> {out_path}")


if __name__ == "__main__":
    sys.exit(main())
