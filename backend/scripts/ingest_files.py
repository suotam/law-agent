"""Parse, chunk and index general documents into the ``org_files`` namespace.

    uv run scripts/ingest_files.py data/files/*.pdf --dry-run --stats
    uv run scripts/ingest_files.py data/files/smlouva.pdf --folder Vzory --dump
    uv run scripts/ingest_files.py data/files/*.pdf --folder Vzory

A developer tool: it takes a folder path and creates whatever part of it is
missing, which the web UI deliberately will not do. All the ingestion logic
lives in ``law_agent.documents.service.ingest_document``; what is left here is
argparse, reading a file and printing.

Parsed documents are cached under ``data/parsed``, because OCR of a scan is by
far the most expensive step: re-tuning ``--max-tokens`` then costs nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

from docling_core.types.doc.document import DoclingDocument

from law_agent.config import settings
from law_agent.db import FolderRepository, session_scope
from law_agent.documents import DuplicateDocumentError, Folder
from law_agent.documents.service import ingest_document
from law_agent.ingestion.files import DoclingClient, FileChunk, FileChunker

_RULE = "=" * 100


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="+", type=Path, help="documents to ingest")
    parser.add_argument(
        "--folder",
        help="folder path such as 'Vzory/Smlouvy'; missing folders are created",
    )
    parser.add_argument(
        "--name", help="stored filename; defaults to the file's own name (one path only)"
    )
    parser.add_argument("--max-tokens", type=int, default=768, help="chunker budget")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and chunk only: no database, no Qdrant, no embedding API",
    )
    parser.add_argument("--stats", action="store_true", help="print the token histogram")
    parser.add_argument(
        "--dump", action="store_true", help="write a readable chunk listing to data/file_chunks/"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/parsed"),
        help="where parsed documents are cached (default: data/parsed)",
    )
    parser.add_argument("--no-cache", action="store_true", help="always re-parse")
    return parser


def load_document(path: Path, *, cache_dir: Path, use_cache: bool) -> DoclingDocument:
    """Parse ``path`` through docling-serve, reusing a cached parse when present."""
    cached = cache_dir / f"{path.stem}.docling.json"
    if use_cache and cached.is_file():
        print(f"  cache hit: {cached}")
        return DoclingDocument.model_validate_json(cached.read_text(encoding="utf-8"))

    print(f"  parsing via docling-serve at {settings.docling_url} ...")
    document = DoclingClient().parse(path)
    if use_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(document.model_dump_json(), encoding="utf-8")
    return document


def print_histogram(counts: list[int], bins: int = 15, width: int = 46) -> None:
    if not counts:
        return
    low, high = counts[0], counts[-1]
    span = max(1, (high - low) // bins or 1)
    buckets = [0] * bins
    for value in counts:
        buckets[min((value - low) // span, bins - 1)] += 1
    peak = max(buckets)
    print("  token distribution:")
    for index, count in enumerate(buckets):
        label = f"{low + index * span:>5}-{low + (index + 1) * span:<5}"
        bar = "#" * round(count / peak * width) if peak else ""
        print(f"    {label} | {bar} {count}")


def dump_chunks(chunks: list[FileChunk], out_dir: Path, stem: str) -> Path:
    """Write chunks in a readable form, for eyeballing OCR and chunk boundaries."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{stem}.chunks.txt"
    blocks = [
        "\n".join(
            [
                _RULE,
                f"[{chunk.chunk_index + 1}/{chunk.chunk_total}] {chunk.citation}",
                f"tokens={chunk.token_count} chars={chunk.char_count} pages={chunk.pages}",
                _RULE,
                chunk.text,
            ]
        )
        for chunk in chunks
    ]
    target.write_text("\n\n".join(blocks), encoding="utf-8")
    return target


def resolve_folder(folder_path: str) -> Folder:
    """Create whatever part of ``folder_path`` does not exist yet, return the leaf."""
    parts = [part for part in folder_path.split("/") if part]
    with session_scope() as session:
        folder = FolderRepository(session).ensure_path(parts)
        session.commit()
    return folder


def report(chunks: list[FileChunk], *, args: argparse.Namespace, stem: str) -> None:
    """The inspection flags: they look at chunks and touch no storage."""
    if args.stats:
        print_histogram(sorted(chunk.token_count for chunk in chunks))
    if args.dump:
        print(f"  dumped to {dump_chunks(chunks, Path('data/file_chunks'), stem)}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Required for a real run only: a dry run stops at parse and chunk and never
    # reaches the database, so there is nobody to ask for a folder.
    if not args.dry_run and not args.folder:
        print("--folder is required unless --dry-run is given", file=sys.stderr)
        return 2
    if args.name and len(args.paths) > 1:
        print("--name makes sense for a single path only", file=sys.stderr)
        return 2

    folder = None if args.dry_run else resolve_folder(args.folder)

    for path in args.paths:
        if not path.is_file():
            print(f"skipping {path}: not a file", file=sys.stderr)
            continue

        filename = args.name or path.name
        print(f"\n=== {path}")
        document = load_document(path, cache_dir=args.cache_dir, use_cache=not args.no_cache)

        if folder is None:
            # A throwaway id: nothing is stored, only the chunk shape is inspected.
            chunks = FileChunker(max_tokens=args.max_tokens).chunk(
                document, doc_id=str(uuid4()), filename=filename
            )
            print(f"  {len(chunks)} chunks")
            report(chunks, args=args, stem=path.stem)
            continue

        try:
            doc_id = ingest_document(
                path.read_bytes(),
                filename=filename,
                folder_id=folder.id,
                uploaded_by="cli",
                parsed=document,
                max_tokens=args.max_tokens,
            )
        except DuplicateDocumentError:
            # Expected on a second run over the same directory: unchanged files
            # hash the same and the unique index turns them away.
            print(f"  skipped: {filename} is already in {args.folder}")
            continue

        print(f"  indexed as doc_id={doc_id}")
        if args.stats or args.dump:
            chunks = FileChunker(max_tokens=args.max_tokens).chunk(
                document, doc_id=str(doc_id), filename=filename, folder_id=str(folder.id)
            )
            report(chunks, args=args, stem=path.stem)

    return 0


if __name__ == "__main__":
    sys.exit(main())
