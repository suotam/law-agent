"""Splitting prose into pieces that fit a token budget.

Shared by both chunkers: laws split a node's text when it overflows, files split
an oversized item the same way. It lives here rather than in either subpackage
so that neither source has to import the other.
"""

from __future__ import annotations

import re

from law_agent.ingestion.tokenizer import TokenCounter

_ABBREVIATIONS = frozenset(
    [
        "odst",
        "písm",
        "č",
        "sb",
        "tj",
        "např",
        "resp",
        "zák",
        "apod",
        "atd",
        "mj",
        "tzv",
        "popř",
        "vyhl",
        "nař",
        "obč",
        "srov",
        "násl",
        "kč",
        "ks",
        "st",
        "ust",
        "zákl",
        "pozn",
        "čl",
        "odd",
        "viz",
        "cit",
        "dle",
        "event",
        "max",
        "min",
        "mld",
    ]
)

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;:])\s+(?=[\"'(\[]?[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ0-9§])")


def split_sentences(text: str) -> list[str]:
    """Split Czech legal prose into sentences.

    Guards against the abbreviations that saturate legal text (``odst.``,
    ``písm.``, ``č.``, ``Sb.``), which a naive full-stop split would break on.
    """
    if not text:
        return []

    pieces: list[str] = []
    start = 0
    for match in _SENTENCE_BOUNDARY.finditer(text):
        head = text[start : match.start()]
        if _ends_with_abbreviation(head):
            continue
        pieces.append(head)
        start = match.end()
    pieces.append(text[start:])
    return [p.strip() for p in pieces if p.strip()]


def _ends_with_abbreviation(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped.endswith("."):
        return False
    last = stripped[:-1].rsplit(maxsplit=1)
    token = last[-1] if last else ""
    return token.lower() in _ABBREVIATIONS or len(token) <= 1


def hard_wrap(text: str, budget: int, count_tokens: TokenCounter) -> list[str]:
    """Break ``text`` on word boundaries into pieces of at most ``budget`` tokens."""
    words = text.split()
    if not words:
        return []

    pieces: list[str] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        if count_tokens(" ".join(current)) > budget and len(current) > 1:
            pieces.append(" ".join(current[:-1]))
            current = [word]
    if current:
        pieces.append(" ".join(current))
    return pieces
