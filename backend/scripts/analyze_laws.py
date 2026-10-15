"""Analyze laws.json: unique `type` values and a histogram of `content` character counts."""

import json
from collections import Counter
from pathlib import Path

LAWS_PATH = Path(__file__).resolve().parent.parent / "data" / "laws" / "laws.json"


def main() -> None:
    with LAWS_PATH.open(encoding="utf-8") as f:
        entries = json.load(f)

    type_counts = Counter(entry.get("type") for entry in entries)

    print(f"Unique 'type' values ({len(type_counts)}):")
    for type_name, count in sorted(type_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {type_name!r}: {count}")

    lengths = [len(entry["content"]) for entry in entries if entry.get("content")]
    print_histogram(lengths)


def print_histogram(lengths: list[int], bins: int = 20) -> None:
    if not lengths:
        print("\nNo content to histogram.")
        return

    lo, hi = min(lengths), max(lengths)
    width = max(1, (hi - lo) // bins or 1)
    edges = [lo + i * width for i in range(bins + 1)]
    edges[-1] = hi

    counts = [0] * bins
    for length in lengths:
        idx = min((length - lo) // width, bins - 1)
        counts[idx] += 1

    max_count = max(counts)
    bar_width = 50

    print(f"\nContent length histogram ({len(lengths)} entries with content, min={lo}, max={hi}):")
    for i, count in enumerate(counts):
        bar = "#" * (round(count / max_count * bar_width) if max_count else 0)
        label = f"{edges[i]:>7}-{edges[i + 1]:<7}"
        print(f"  {label} | {bar} {count}")


if __name__ == "__main__":
    main()
