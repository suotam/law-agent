"""Fetch a single law from the ceskezakony.cz API and index it into the ``laws`` namespace.

    uv run scripts/ingest_law_url.py https://ceskezakony.cz/api/v1/laws/106/1999/fragments
    uv run scripts/ingest_law_url.py https://ceskezakony.cz/api/v1/laws/106/1999/fragments --dry-run
    uv run scripts/ingest_law_url.py https://ceskezakony.cz/api/v1/laws/89/2012/fragments --dump

Requires ``CESKEZAKONY_API_TOKEN`` in the environment (see ``.env.example``) and
a running Qdrant (see docker-compose.yml): `docker compose up -d`.

The counterpart of ``ingest_laws.py`` for a law that is not yet in ``data/laws/``:
fetching lives here, chunking in ``law_agent.ingestion.laws`` and indexing in
``law_agent.indexing``, matching the split ``ingest_laws.py`` already uses.

Re-running is safe and cheap: ``index_chunks`` re-embeds only chunks whose text
changed, and ``prune_orphans`` then removes points a shorter new version of the
law no longer produces.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv

from law_agent.config import settings
from law_agent.core import get_embeddings
from law_agent.indexing import (
    Bm25SparseEmbedder,
    ensure_collection,
    get_qdrant_client,
    index_chunks,
    prune_orphans,
)
from law_agent.ingestion.laws import (
    NAMESPACE,
    ChunkingConfig,
    LawChunk,
    LawChunker,
    LawDocument,
    validate,
)

# Api ceskezakony.cz is limited to 5000 requests per day AND 5 requests per second.
PER_PAGE = 100
MAX_RETRIES = 5
REQUEST_DELAY_SECONDS = 1.0

REPO_ROOT = Path(__file__).resolve().parent.parent
_RULE = "=" * 100


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "url", help="ceskezakony.cz fragments API URL, e.g. .../laws/106/1999/fragments"
    )
    parser.add_argument("--collection", default=settings.qdrant_collection)
    parser.add_argument("--max-tokens", type=int, default=768, help="chunker budget")
    parser.add_argument("--min-tokens", type=int, default=120)
    parser.add_argument("--include-repealed", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch, chunk and validate only: no Qdrant, no embedding API",
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="keep points of the law that this run did not produce",
    )
    parser.add_argument(
        "--dump", action="store_true", help="write a readable chunk listing to data/law_chunks/"
    )
    parser.add_argument(
        "--save-json",
        action="store_true",
        help="save the fetched fragments to data/laws/, so a re-run can use ingest_laws.py instead",
    )
    return parser


def fetch_page(url: str, token: str, cursor: str | None) -> dict:
    params: dict[str, int | str] = {"per_page": PER_PAGE}
    if cursor is not None:
        params["cursor"] = cursor

    request = urllib.request.Request(
        f"{url}?{urlencode(params)}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "curl/8.7.1",
        },
    )

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(request) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == MAX_RETRIES - 1:
                raise
            wait_seconds = float(error.headers.get("Retry-After") or 2**attempt)
            time.sleep(wait_seconds)

    raise RuntimeError("unreachable")


def fetch_fragments(url: str, token: str) -> list[dict]:
    fragments: list[dict] = []
    cursor = None
    while True:
        page = fetch_page(url, token, cursor)
        fragments.extend(page["data"])
        cursor = page["meta"]["next_cursor"]
        if not cursor:
            break
        time.sleep(REQUEST_DELAY_SECONDS)
    return fragments


def slug_from_url(url: str) -> str:
    """``.../laws/106/1999/fragments`` -> ``106_1999``, for filenames."""
    parts = [part for part in url.rstrip("/").split("/") if part]
    number, year = parts[-3], parts[-2]
    return f"{number}_{year}"


def save_json(fragments: list[dict], slug: str) -> Path:
    target = REPO_ROOT / "data" / "laws" / f"{slug}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(fragments, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def dump_chunks(chunks: list[LawChunk], out_dir: Path, stem: str) -> Path:
    """Write chunks in a readable form, for eyeballing chunk boundaries before indexing."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{stem}.chunks.txt"
    blocks = [
        "\n".join(
            [
                _RULE,
                f"[{index}/{len(chunks)}] {chunk.citation}",
                f"tokens={chunk.token_count} chars={chunk.char_count}",
                _RULE,
                chunk.text,
            ]
        )
        for index, chunk in enumerate(chunks, start=1)
    ]
    target.write_text("\n\n".join(blocks), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    token = os.environ.get("CESKEZAKONY_API_TOKEN")
    if not token:
        print("CESKEZAKONY_API_TOKEN is not set (see .env.example)", file=sys.stderr)
        return 2

    slug = slug_from_url(args.url)
    print(f"fetching {args.url} ...")
    fragments = fetch_fragments(args.url, token)
    print(f"  {len(fragments)} fragments")

    if args.save_json:
        path = save_json(fragments, slug)
        print(f"  saved to {path}")

    config = ChunkingConfig(max_tokens=args.max_tokens, min_tokens=args.min_tokens)
    document = LawDocument.from_fragments(fragments, include_repealed=args.include_repealed)
    chunks = LawChunker(config=config).chunk(document)
    report = validate(document, chunks, config)

    print(f"\n=== {document.metadata.render_header()}")
    print(f"  {len(chunks)} chunks | {report.describe()}")

    if args.dump:
        print(f"  dumped to {dump_chunks(chunks, REPO_ROOT / 'data' / 'law_chunks', slug)}")

    if args.dry_run:
        return 1 if not report.ok else 0

    client = get_qdrant_client()
    ensure_collection(client, args.collection)
    stats = index_chunks(
        client,
        chunks,
        collection_name=args.collection,
        embeddings=get_embeddings(),
        sparse_embedder=Bm25SparseEmbedder(),
        namespace=NAMESPACE,
    )
    print(f"  embedded {stats.embedded}, skipped {stats.skipped} (of {stats.total})")

    if not args.no_prune:
        deleted = prune_orphans(
            client,
            args.collection,
            scope={"namespace": NAMESPACE, "law_id": document.metadata.law_id},
            keep=[chunk.point_id for chunk in chunks],
        )
        if deleted:
            print(f"  pruned {deleted} stale points")

    return 1 if not report.ok else 0


if __name__ == "__main__":
    sys.exit(main())
