"""Mapping of raw fragment ``type`` values onto structural roles.

The ceskezakony.cz fragment API uses a large, open-ended vocabulary of ``type``
values, and the set differs between laws (a short law has no ``Hlava``/``Dil``,
an annexed one adds ``Block_Priloha``, ``Tabulka``, ...). Chunking must not
depend on that vocabulary, so every fragment is first reduced to one of a few
:class:`Role` values. Unknown types are classified by shape (see
:func:`classify`), which is what makes the pipeline work on laws we have never
seen.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from law_agent.ingestion.laws.models import Fragment


class Role(StrEnum):
    """Structural role of a fragment, independent of the source ``type``."""

    ROOT = "root"
    """The document itself (``Virtual_Document``)."""

    CONTAINER = "container"
    """Grouping node carrying no body text of its own (parts, chapters,
    ``Virtual_*`` sections, transparent ``Block_*`` wrappers)."""

    SECTION = "section"
    """Smallest independently citable unit and the primary chunk anchor
    (``Paragraf``, and annex headers which play the same role in annexes)."""

    TEXT = "text"
    """Body text: paragraphs, letters, points, sentence continuations, tables."""

    HEADING = "heading"
    """A title for a container or for a group of following siblings."""

    FOOTNOTE = "footnote"
    """Footnote text (``PPC``), stored out-of-band and referenced by marker."""

    DOC_META = "doc_meta"
    """Front-matter carrying document metadata (number, kind, date, title)."""

    SKIP = "skip"
    """Never contributes to a chunk (signatures)."""


_EXPLICIT: dict[str, Role] = {
    "Virtual_Document": Role.ROOT,
    # Containers ------------------------------------------------------------
    "Virtual_Prefix": Role.CONTAINER,
    "Virtual_Norma": Role.CONTAINER,
    "Virtual_Zaver": Role.CONTAINER,
    "Virtual_Postfix": Role.CONTAINER,
    "Virtual_Prilohy": Role.CONTAINER,
    "Virtual_PPC": Role.CONTAINER,
    "Cast": Role.CONTAINER,
    "Hlava": Role.CONTAINER,
    "Dil": Role.CONTAINER,
    "Oddil": Role.CONTAINER,
    "Block_Priloha": Role.CONTAINER,
    "Block_Prechodne_Ustanoveni_Nov": Role.CONTAINER,
    "Block_Prechodne_Ustanoveni": Role.CONTAINER,
    "Block_Ucinnostni_Ustanoveni": Role.CONTAINER,
    "Block_Zrusovaci_Ustanoveni": Role.CONTAINER,
    # Anchors ---------------------------------------------------------------
    "Paragraf": Role.SECTION,
    "Clanek": Role.SECTION,
    "Hlavicka_priloha": Role.SECTION,
    # Body text -------------------------------------------------------------
    "Odstavec_Dc": Role.TEXT,
    "Pismeno_Lb": Role.TEXT,
    "Bod_Dd": Role.TEXT,
    "Pokracovani_Text": Role.TEXT,
    "Tabulka": Role.TEXT,
    "Prefix": Role.TEXT,
    # Headings --------------------------------------------------------------
    "Nadpis": Role.HEADING,
    "Nadpis_nad": Role.HEADING,
    "Nadpis_pod": Role.HEADING,
    # Other -----------------------------------------------------------------
    "PPC": Role.FOOTNOTE,
    "Prefix_Number": Role.DOC_META,
    "Prefix_Type": Role.DOC_META,
    "Prefix_Date": Role.DOC_META,
    "Prefix_Title": Role.DOC_META,
    "Postfix": Role.SKIP,
}


def classify(fragment: Fragment, *, has_children: bool) -> Role:
    """Return the structural role of ``fragment``.

    Known types are mapped directly. Unknown ones fall back to shape-based
    rules so that a law introducing new ``type`` values still chunks sensibly
    instead of losing text:

    * ``Nadpis*`` prefix -> :attr:`Role.HEADING`
    * ``Virtual_*`` / ``Block_*`` prefix -> :attr:`Role.CONTAINER`
    * no content, but children -> :attr:`Role.CONTAINER`
    * content equal to the node's own designation or heading -> it is a label,
      not body text -> :attr:`Role.CONTAINER`
    * anything else that carries text -> :attr:`Role.TEXT`

    Args:
        fragment: The raw fragment to classify.
        has_children: Whether the fragment has nested fragments beneath it.
    """
    role = _EXPLICIT.get(fragment.type)
    if role is not None:
        return role

    type_name = fragment.type
    if type_name.startswith("Nadpis"):
        return Role.HEADING
    if type_name.startswith(("Virtual_", "Block_")):
        return Role.CONTAINER

    content = (fragment.content or "").strip()
    if not content:
        return Role.CONTAINER if has_children else Role.SKIP
    if content in {(fragment.designation or "").strip(), (fragment.heading or "").strip()}:
        return Role.CONTAINER
    return Role.TEXT


def is_known_type(type_name: str) -> bool:
    """Whether ``type_name`` has an explicit mapping (used for drift reports)."""
    return type_name in _EXPLICIT
