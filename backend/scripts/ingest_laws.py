"""Chunk law JSON files and index them into the ``laws`` namespace.

    uv run scripts/ingest_laws.py                         # every data/laws/*.json
    uv run scripts/ingest_laws.py data/laws/zakonik_prace.json
    uv run scripts/ingest_laws.py --dry-run               # chunk and validate only

Requires a running Qdrant (see docker-compose.yml): `docker compose up -d`.

The counterpart of ``ingest_files.py`` for laws: chunking itself lives in
``law_agent.ingestion.laws`` and indexing in ``law_agent.indexing``, so what is
left here is argparse, iterating over files and printing.

Re-running is safe and cheap: ``index_chunks`` re-embeds only chunks whose text
changed, and ``prune_orphans`` then removes points a shorter new version of the
law no longer produces.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient

from law_agent.config import settings
from law_agent.core import get_embeddings
from law_agent.indexing import (
    Bm25SparseEmbedder,
    ensure_collection,
    get_qdrant_client,
    index_chunks,
    prune_orphans,
)
from law_agent.ingestion.laws import NAMESPACE, ChunkingConfig, LawChunker, LawDocument, validate

REPO_ROOT = Path(__file__).resolve().parent.parent
LAWS_DIR = REPO_ROOT / "data" / "laws"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=f"law fragment JSON files (default: {LAWS_DIR}/*.json)",
    )
    parser.add_argument("--namespace", default=NAMESPACE)
    parser.add_argument("--collection", default=settings.qdrant_collection)
    parser.add_argument("--max-tokens", type=int, default=768, help="chunker budget")
    parser.add_argument("--min-tokens", type=int, default=120)
    parser.add_argument("--include-repealed", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="chunk and validate only: no Qdrant, no embedding API",
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="keep points of the law that this run did not produce",
    )
    return parser


def resolve_paths(paths: list[Path]) -> list[Path]:
    return paths or sorted(LAWS_DIR.glob("*.json"))


def open_backend(collection: str) -> tuple[QdrantClient, Embeddings, Bm25SparseEmbedder]:
    """Everything a real run needs; a dry run touches none of it."""
    client = get_qdrant_client()
    ensure_collection(client, collection)
    return client, get_embeddings(), Bm25SparseEmbedder()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    paths = resolve_paths(args.paths)
    if not paths:
        print(f"no law files found in {LAWS_DIR}", file=sys.stderr)
        return 2

    config = ChunkingConfig(max_tokens=args.max_tokens, min_tokens=args.min_tokens)
    chunker = LawChunker(config=config)

    backend = None if args.dry_run else open_backend(args.collection)

    failed = False
    for path in paths:
        if not path.is_file():
            print(f"skipping {path}: not a file", file=sys.stderr)
            continue

        document = LawDocument.from_json(path, include_repealed=args.include_repealed)
        chunks = chunker.chunk(document)
        report = validate(document, chunks, config)

        print(f"\n=== {path.name} — {document.metadata.render_header()}")
        print(f"  {len(chunks)} chunks | {report.describe()}")
        if not report.ok:
            # Loud but not fatal: a coverage gap is worth seeing, yet indexing
            # the rest still beats leaving the law out of retrieval entirely.
            failed = True

        if backend is None:
            continue

        client, embeddings, sparse_embedder = backend
        stats = index_chunks(
            client,
            chunks,
            collection_name=args.collection,
            embeddings=embeddings,
            sparse_embedder=sparse_embedder,
            namespace=args.namespace,
        )
        print(f"  embedded {stats.embedded}, skipped {stats.skipped} (of {stats.total})")

        if not args.no_prune:
            deleted = prune_orphans(
                client,
                args.collection,
                scope={"namespace": args.namespace, "law_id": document.metadata.law_id},
                keep=[chunk.point_id for chunk in chunks],
            )
            if deleted:
                print(f"  pruned {deleted} stale points")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
