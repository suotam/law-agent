"""The ``[n]`` marks in an answer: handing them out, and reading them back.

A mark is a ``ref``, not a position in a list -- the identifier stored on the
``tool_result`` item the model was shown. A ref is unique for the life of a
conversation, so a mark from an earlier turn resolves to the source it named
then, and an invented one resolves to nothing.

The list of cited refs is not stored. It is ``marks in the text ∩ refs offered
in the conversation``, and both sides are already in the loaded archive.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from law_agent.conversations.models import SourceItem

_MARK_PATTERN = re.compile(r"\[(\d+)\]")

_CHUNK_ID = "chunk_id"


def used_refs(text: str, offered: Collection[int]) -> list[int]:
    """Refs cited in ``text``, first use first, hallucinated ones dropped."""
    refs: list[int] = []
    for match in _MARK_PATTERN.finditer(text):
        ref = int(match.group(1))
        if ref in offered and ref not in refs:
            refs.append(ref)
    return refs


@dataclass
class Numbering:
    """The refs a conversation has handed out, and where to continue.

    Mutable for the length of a turn on purpose: an agent loop searching twice
    before anything is stored needs the second call to continue from the first.
    """

    by_chunk: dict[str, int] = field(default_factory=dict)
    next_ref: int = 1

    @classmethod
    def of(cls, offered: Mapping[int, SourceItem]) -> Numbering:
        """Rebuild the numbering from everything the conversation offered.

        ``next_ref`` counts past uncited material too: the archive keeps it and
        the FE has it in its map, so its numbers are spent either way.
        """
        by_chunk = {
            str(item.content[_CHUNK_ID]): item.ref
            for item in offered.values()
            if item.content.get(_CHUNK_ID)
        }
        return cls(by_chunk=by_chunk, next_ref=max(offered, default=0) + 1)

    def ref_for(self, chunk_id: str) -> int:
        """The chunk's ref -- the one it already has, or the next free one."""
        ref = self.by_chunk.get(chunk_id)
        if ref is None:
            ref = self.next_ref
            self.by_chunk[chunk_id] = ref
            self.next_ref += 1
        return ref
