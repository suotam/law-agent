"""Chunk law JSON files, report statistics and optionally write JSONL.

uv run scripts/chunk_laws.py data/laws/*.json --stats
uv run scripts/chunk_laws.py data/laws/zakon.json --out data/chunks --max-tokens 512
uv run scripts/chunk_laws.py data/laws/zakon.json --sample 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from law_agent.ingestion.laws import ChunkingConfig, LawChunker, LawDocument, validate
from law_agent.ingestion.laws.chunker import FootnoteMode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="+", type=Path, help="law fragment JSON files")
    parser.add_argument("--out", type=Path, help="directory for <stem>.chunks.jsonl output")
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--min-tokens", type=int, default=120)
    parser.add_argument("--no-merge", action="store_true", help="disable merging of small sections")
    parser.add_argument("--include-repealed", action="store_true")
    parser.add_argument(
        "--footnotes",
        choices=[mode.value for mode in FootnoteMode],
        default=FootnoteMode.METADATA.value,
    )
    parser.add_argument("--sample", type=int, default=0, help="print N sample chunks")
    parser.add_argument("--stats", action="store_true", help="print the token histogram")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = ChunkingConfig(
        max_tokens=args.max_tokens,
        min_tokens=args.min_tokens,
        merge_small_sections=not args.no_merge,
        footnote_mode=FootnoteMode(args.footnotes),
    )

    failed = False
    for path in args.paths:
        document = LawDocument.from_json(path, include_repealed=args.include_repealed)
        chunks, stats = LawChunker(config=config).chunk_with_stats(document)
        report = validate(document, chunks, config)

        print(f"\n=== {path.name} — {document.metadata.render_header()}")
        print(
            f"  fragments={document.report.fragment_count} nodes={document.report.node_count} "
            f"repealed_dropped={document.report.dropped_repealed} footnotes={len(document.footnotes)}"
        )
        print("  " + " ".join(f"{key}={value}" for key, value in stats.summary().items()))
        print(f"  {report.describe()}")
        if not report.ok:
            failed = True

        if args.stats:
            print_histogram(sorted(chunk.token_count for chunk in chunks))
        for chunk in chunks[: args.sample]:
            print(f"\n  --- {chunk.citation} [{chunk.token_count} tok] {chunk.chunk_id}")
            print("  " + chunk.text.replace("\n", "\n  "))

        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            target = args.out / f"{path.stem}.chunks.jsonl"
            with target.open("w", encoding="utf-8") as handle:
                for chunk in chunks:
                    handle.write(
                        json.dumps(chunk.to_payload(namespace=config.namespace), ensure_ascii=False)
                        + "\n"
                    )
            print(f"  wrote {len(chunks)} chunks -> {target}")

    return 1 if failed else 0


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


if __name__ == "__main__":
    sys.exit(main())
