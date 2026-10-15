"""Query the documents indexed by ``ingest_files.py``.

    uv run scripts/query_files.py "odměna za hodinu"
    uv run scripts/query_files.py "topologie sítě" --limit 3
    uv run scripts/query_files.py "odstoupení" --doc-id smlouva.pdf

Unlike ``query_laws.py`` this only queries: what is in the index got there
through ``ingest_files.py``, so a query never has a side effect on the index.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from law_agent.config import settings
from law_agent.core.embeddings import get_embeddings
from law_agent.indexing import Bm25SparseEmbedder, ensure_collection, get_qdrant_client
from law_agent.ingestion.files import NAMESPACE
from law_agent.retrieval import RetrievedChunk, query_chunks

RESULTS_DIR = Path("data/query_results")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("query", help="search text")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--namespace", default=NAMESPACE)
    parser.add_argument("--collection", default=settings.qdrant_collection)
    parser.add_argument("--doc-id", help="restrict the search to a single document")
    parser.add_argument("--full", action="store_true", help="print whole chunks, not excerpts")
    parser.add_argument("--save", action="store_true", help="write results to data/query_results/")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    client = get_qdrant_client()
    ensure_collection(client, args.collection)

    results = query_chunks(
        client,
        args.query,
        collection_name=args.collection,
        embeddings=get_embeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace=args.namespace,
        limit=args.limit,
        extra_filter={"doc_id": args.doc_id} if args.doc_id else None,
    )

    if not results:
        print(f"no hits in namespace '{args.namespace}' — is anything ingested?")
        return 1

    for rank, result in enumerate(results, start=1):
        print(f"\n#{rank} [{result.score:.4f}] {result.citation}")
        text = result.text if args.full else result.text[:400]
        print("  " + text.replace("\n", "\n  "))

    if args.save:
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
                "doc_id": result.payload.get("doc_id"),
                "pages": result.payload.get("pages"),
                "text": result.text,
            }
            for result in results
        ],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {len(results)} results -> {out_path}")


if __name__ == "__main__":
    sys.exit(main())
