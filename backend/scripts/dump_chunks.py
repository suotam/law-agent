"""Dump chunks to a human-readable file for eyeballing the chunking.

Unlike ``chunk_laws.py --out`` (which writes JSONL for ingestion), this writes
one readable block per chunk: header, body, metadata and footnotes.

    uv run scripts/dump_chunks.py data/laws/zakonik_prace.json
    uv run scripts/dump_chunks.py data/laws/*.json --out data/dump --format md
    uv run scripts/dump_chunks.py data/laws/zakon.json --section "§ 41" --body-only
    uv run scripts/dump_chunks.py data/laws/zakon.json --min-tokens 700   # only the big ones
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from law_agent.ingestion.laws import ChunkingConfig, LawChunk, LawChunker, LawDocument, validate
from law_agent.ingestion.laws.chunker import FootnoteMode

_RULE = "=" * 100


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="+", type=Path, help="law fragment JSON files")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/chunks"),
        help="output directory (default: data/chunks)",
    )
    parser.add_argument("--format", choices=["txt", "md"], default="txt")

    parser.add_argument("--max-tokens", type=int, default=768, help="chunker budget")
    parser.add_argument("--min-tokens", type=int, default=120, help="chunker merge threshold")
    parser.add_argument("--no-merge", action="store_true", help="disable merging of small sections")
    parser.add_argument("--include-repealed", action="store_true")
    parser.add_argument(
        "--footnotes",
        choices=[mode.value for mode in FootnoteMode],
        default=FootnoteMode.METADATA.value,
    )

    filters = parser.add_argument_group("filters (what lands in the dump)")
    filters.add_argument("--section", help="substring match against the chunk citation")
    filters.add_argument("--part", help="only this document part (norma, prilohy, zaver, ...)")
    filters.add_argument("--only-above", type=int, help="only chunks with >= N tokens")
    filters.add_argument("--only-below", type=int, help="only chunks with <= N tokens")
    filters.add_argument("--only-split", action="store_true", help="only sections split in pieces")
    filters.add_argument("--limit", type=int, default=0, help="stop after N chunks (0 = all)")

    parser.add_argument(
        "--body-only", action="store_true", help="omit the metadata block, print text only"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = ChunkingConfig(
        max_tokens=args.max_tokens,
        min_tokens=args.min_tokens,
        merge_small_sections=not args.no_merge,
        footnote_mode=FootnoteMode(args.footnotes),
    )

    args.out.mkdir(parents=True, exist_ok=True)
    for path in args.paths:
        document = LawDocument.from_json(path, include_repealed=args.include_repealed)
        chunks, stats = LawChunker(config=config).chunk_with_stats(document)
        report = validate(document, chunks, config)

        selected = [chunk for chunk in chunks if keep(chunk, args)]
        if args.limit:
            selected = selected[: args.limit]

        target = args.out / f"{path.stem}.chunks.{args.format}"
        with target.open("w", encoding="utf-8") as handle:
            handle.write(
                render_summary(
                    document=document,
                    stats_line=" ".join(f"{k}={v}" for k, v in stats.summary().items()),
                    validation=report.describe(),
                    total=len(chunks),
                    shown=len(selected),
                    config=config,
                    markdown=args.format == "md",
                )
            )
            for index, chunk in enumerate(selected, start=1):
                handle.write(
                    render_chunk(
                        chunk,
                        index=index,
                        markdown=args.format == "md",
                        body_only=args.body_only,
                    )
                )

        print(f"{path.name}: {len(selected)}/{len(chunks)} chunks -> {target}")
    return 0


def keep(chunk: LawChunk, args: argparse.Namespace) -> bool:
    if args.section and args.section.lower() not in chunk.citation.lower():
        return False
    if args.part and chunk.part != args.part:
        return False
    if args.only_above is not None and chunk.token_count < args.only_above:
        return False
    if args.only_below is not None and chunk.token_count > args.only_below:
        return False
    return not (args.only_split and chunk.chunk_total <= 1)


def render_summary(
    *,
    document: LawDocument,
    stats_line: str,
    validation: str,
    total: int,
    shown: int,
    config: ChunkingConfig,
    markdown: bool,
) -> str:
    lines = [
        f"# {document.metadata.render_header()}" if markdown else document.metadata.render_header(),
        "",
        f"law_id:     {document.metadata.law_id}",
        (
            f"fragments:  {document.report.fragment_count} "
            f"nodes={document.report.node_count} "
            f"repealed_dropped={document.report.dropped_repealed} "
            f"footnotes={len(document.footnotes)}"
        ),
        (
            f"config:     max_tokens={config.max_tokens} min_tokens={config.min_tokens} "
            f"merge={config.merge_small_sections} footnotes={config.footnote_mode.value}"
        ),
        f"stats:      {stats_line}",
        f"validation: {validation}",
        f"dumped:     {shown} of {total} chunks",
        "",
    ]
    return "\n".join(lines) + "\n"


def render_chunk(chunk: LawChunk, *, index: int, markdown: bool, body_only: bool) -> str:
    title = f"[{index}] {chunk.citation}  ({chunk.token_count} tok, {chunk.char_count} ch)"
    if chunk.chunk_total > 1:
        title += f"  část {chunk.chunk_index}/{chunk.chunk_total}"

    lines: list[str] = [""]
    if markdown:
        lines += [f"## {title}", ""]
    else:
        lines += [_RULE, title, _RULE]

    if not body_only:
        breadcrumb = " > ".join(entry.render() for entry in chunk.breadcrumb) or "—"
        meta = [
            f"chunk_id:  {chunk.chunk_id}",
            f"point_id:  {chunk.point_id}",
            f"anchor:    {chunk.anchor_fragment_id}",
            f"part:      {chunk.part}   section: {chunk.section or '—'}",
            f"path:      {breadcrumb}",
            (
                f"positions: {chunk.position_start}-{chunk.position_end}  "
                f"fragments={len(chunk.source_fragment_ids)}"
            ),
            (
                f"flags:     effective={chunk.is_effective} repealed={chunk.is_repealed} "
                f"amended={chunk.is_amended}"
            ),
        ]
        if chunk.group_heading:
            meta.append(f"group:     {chunk.group_heading}")
        lines += [*indent(meta, markdown), ""]

    lines += ["--- text (embedded) ---" if not markdown else "```"]
    lines.append(chunk.text)
    if markdown:
        lines.append("```")

    if chunk.footnotes and not body_only:
        lines += ["", "--- footnotes ---"]
        lines += [f"  {marker} {text}" for marker, text in sorted(chunk.footnotes.items())]

    lines.append("")
    return "\n".join(lines) + "\n"


def indent(lines: list[str], markdown: bool) -> list[str]:
    prefix = "    " if markdown else ""
    return [prefix + line for line in lines]


if __name__ == "__main__":
    sys.exit(main())
