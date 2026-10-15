"""Chunking behaviour: boundaries, repeated context, merging, identity."""

from __future__ import annotations

import pytest
from tests.conftest import FragmentBuilder

from law_agent.ingestion import HeuristicTokenCounter
from law_agent.ingestion.laws import ChunkingConfig, LawChunker
from law_agent.ingestion.laws.chunker import FootnoteMode, hard_wrap, split_sentences

LOREM = "Zaměstnavatel je povinen zajistit rovné zacházení se všemi zaměstnanci. "


def chunker(**overrides: object) -> LawChunker:
    return LawChunker(config=ChunkingConfig(**overrides))  # type: ignore[arg-type]


def test_section_that_fits_becomes_exactly_one_chunk(builder: FragmentBuilder) -> None:
    builder.add("Paragraf", 2, segment="par_1", designation="§ 1", content="§ 1")
    builder.add("Nadpis_pod", 3, heading="Předmět úpravy", content="Předmět úpravy")
    builder.add(
        "Odstavec_Dc", 3, segment="odst_1", designation="(1)", content="(1) První odstavec."
    )
    builder.add(
        "Odstavec_Dc", 3, segment="odst_2", designation="(2)", content="(2) Druhý odstavec."
    )

    chunks = chunker(merge_small_sections=False).chunk(builder.document())

    assert len(chunks) == 1
    chunk = chunks[0]
    assert "(1) První odstavec." in chunk.body
    assert "(2) Druhý odstavec." in chunk.body
    assert "Předmět úpravy" in chunk.header, "the heading belongs to the header"
    assert chunk.body.count("Předmět úpravy") == 0, "and must not be duplicated in the body"
    assert chunk.citation == "§ 1 zákon č. 1/2020 Sb."


def test_oversized_section_splits_by_paragraph(builder: FragmentBuilder) -> None:
    builder.add("Paragraf", 2, segment="par_1", designation="§ 1", content="§ 1")
    for index in range(1, 5):
        builder.add(
            "Odstavec_Dc",
            3,
            segment=f"odst_{index}",
            designation=f"({index})",
            content=f"({index}) " + LOREM * 6,
        )

    chunks = chunker(max_tokens=200, merge_small_sections=False).chunk(builder.document())

    assert len(chunks) > 1
    assert all(chunk.token_count <= 200 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(1, len(chunks) + 1))
    assert all(chunk.chunk_total == len(chunks) for chunk in chunks)
    assert all(chunk.section == "§ 1" for chunk in chunks)
    assert "odst." in chunks[0].citation


def test_split_below_paragraph_repeats_the_lead_in(builder: FragmentBuilder) -> None:
    """A letter is meaningless without the sentence that introduces it."""
    intro = "(1) Pro účely úpravy pracovní doby a doby odpočinku je"
    builder.add("Paragraf", 2, segment="par_78", designation="§ 78", content="§ 78")
    builder.add("Odstavec_Dc", 3, segment="odst_1", designation="(1)", content=intro)
    for letter in "abcd":
        builder.add(
            "Pismeno_Lb",
            4,
            segment=f"pism_{letter}",
            designation=f"{letter})",
            content=f"{letter}) " + LOREM * 4,
        )

    chunks = chunker(max_tokens=200, merge_small_sections=False).chunk(builder.document())

    assert len(chunks) > 1
    assert all(intro in chunk.body for chunk in chunks), "lead-in must be repeated"
    assert all("odst. 1 písm." in chunk.citation for chunk in chunks)


def test_small_adjacent_sections_are_merged_and_labelled(builder: FragmentBuilder) -> None:
    builder.add("Hlava", 2, segment="hlava_1", designation="HLAVA I", content="HLAVA I")
    for index in (1, 2, 3):
        builder.add(
            "Paragraf", 3, segment=f"par_{index}", designation=f"§ {index}", content=f"§ {index}"
        )
        builder.add(
            "Odstavec_Dc",
            4,
            segment="odst_1",
            designation="(1)",
            content=f"(1) Krátký text {index}.",
        )

    chunks = chunker(min_tokens=200, max_tokens=768).chunk(builder.document())

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.citation == "§ 1 až 3 zákon č. 1/2020 Sb."
    assert "§ 2" in chunk.body, "merged sections must stay individually identifiable"
    assert "Krátký text 3." in chunk.body


def test_titled_section_starts_its_own_chunk(builder: FragmentBuilder) -> None:
    """A section with its own heading is a self-contained topic.

    Merging it into a neighbour would bury its title, and the merged header --
    built from the first anchor -- would spread one section's title over the
    others.
    """
    builder.add("Hlava", 2, segment="hlava_1", designation="HLAVA I", content="HLAVA I")
    for index in (1, 2, 3):
        builder.add(
            "Paragraf", 3, segment=f"par_{index}", designation=f"§ {index}", content=f"§ {index}"
        )
        if index == 2:
            builder.add(
                "Nadpis_pod", 4, segment="nadpis", heading="Vlastní téma", content="Vlastní téma"
            )
        builder.add(
            "Odstavec_Dc",
            4,
            segment="odst_1",
            designation="(1)",
            content=f"(1) Krátký text {index}.",
        )

    chunks = chunker(min_tokens=200, max_tokens=768).chunk(builder.document())

    citations = [chunk.citation for chunk in chunks]
    assert citations == [
        "§ 1 zákon č. 1/2020 Sb.",
        "§ 2 zákon č. 1/2020 Sb.",
        "§ 3 zákon č. 1/2020 Sb.",
    ]
    assert "Vlastní téma" in chunks[1].header
    assert all("Vlastní téma" not in chunk.header for chunk in (chunks[0], chunks[2]))


def test_sections_under_different_parents_are_not_merged(builder: FragmentBuilder) -> None:
    for chapter in (1, 2):
        builder.add(
            "Hlava",
            2,
            segment=f"hlava_{chapter}",
            designation=f"HLAVA {chapter}",
            content=f"HLAVA {chapter}",
        )
        builder.add(
            "Paragraf",
            3,
            segment=f"par_{chapter}",
            designation=f"§ {chapter}",
            content=f"§ {chapter}",
        )
        builder.add("Odstavec_Dc", 4, segment="odst_1", designation="(1)", content="(1) Krátce.")

    chunks = chunker(min_tokens=500).chunk(builder.document())

    assert len(chunks) == 2, "merging across containers would produce a misleading citation"


def test_single_huge_leaf_falls_back_to_sentence_splitting(builder: FragmentBuilder) -> None:
    builder.add("Paragraf", 2, segment="par_1", designation="§ 1", content="§ 1")
    builder.add("Odstavec_Dc", 3, segment="odst_1", designation="(1)", content="(1) " + LOREM * 40)

    chunks = chunker(max_tokens=200, merge_small_sections=False).chunk(builder.document())

    assert len(chunks) > 1
    assert all(chunk.token_count <= 200 for chunk in chunks)


def test_every_chunk_carries_its_context_header(builder: FragmentBuilder) -> None:
    builder.add("Cast", 2, segment="cast_1", designation="ČÁST PRVNÍ", content="ČÁST PRVNÍ")
    builder.add("Nadpis_pod", 3, heading="OBECNÁ USTANOVENÍ", content="OBECNÁ USTANOVENÍ")
    builder.add("Paragraf", 3, segment="par_1", designation="§ 1", content="§ 1")
    builder.add("Odstavec_Dc", 4, segment="odst_1", designation="(1)", content="(1) Text.")

    chunk = chunker().chunk(builder.document())[0]

    assert chunk.text.startswith(chunk.header)
    assert "zákon č. 1/2020 Sb." in chunk.header
    assert "ČÁST PRVNÍ – OBECNÁ USTANOVENÍ" in chunk.header
    assert [entry.render() for entry in chunk.breadcrumb] == ["ČÁST PRVNÍ – OBECNÁ USTANOVENÍ"]


def test_leaf_headings_do_not_become_chunks_of_their_own(builder: FragmentBuilder) -> None:
    """Their text already reaches the index via headers and breadcrumbs."""
    builder.add("Cast", 2, segment="cast_1", designation="ČÁST PRVNÍ", content="ČÁST PRVNÍ")
    builder.add("Nadpis_pod", 3, heading="VŠEOBECNÁ USTANOVENÍ", content="VŠEOBECNÁ USTANOVENÍ")
    builder.add("Paragraf", 3, segment="par_1", designation="§ 1", content="§ 1")
    builder.add("Odstavec_Dc", 4, segment="odst_1", designation="(1)", content="(1) Text.")
    builder.add("Nadpis_nad", 3, heading="Skupinový nadpis", content="Skupinový nadpis")
    builder.add("Paragraf", 3, segment="par_2", designation="§ 2", content="§ 2")
    builder.add("Odstavec_Dc", 4, segment="odst_1", designation="(1)", content="(1) Další.")

    chunks = chunker(merge_small_sections=False).chunk(builder.document())

    assert [chunk.section for chunk in chunks] == ["§ 1", "§ 2"]
    assert "VŠEOBECNÁ USTANOVENÍ" in chunks[0].header
    assert chunks[1].group_heading == "Skupinový nadpis"
    assert "Skupinový nadpis" in chunks[1].header


def test_lead_in_too_large_to_repeat_is_still_indexed(builder: FragmentBuilder) -> None:
    """Trimming an unrepeatable lead-in must not silently drop its text."""
    intro = "(1) " + LOREM * 12
    builder.add("Paragraf", 2, segment="par_1", designation="§ 1", content="§ 1")
    builder.add("Odstavec_Dc", 3, segment="odst_1", designation="(1)", content=intro)
    for letter in "abc":
        builder.add(
            "Pismeno_Lb",
            4,
            segment=f"pism_{letter}",
            designation=f"{letter})",
            content=f"{letter}) " + LOREM * 3,
        )

    chunks = chunker(max_tokens=180, merge_small_sections=False).chunk(builder.document())
    combined = "\n".join(chunk.body for chunk in chunks)

    assert all(chunk.token_count <= 180 for chunk in chunks)
    assert LOREM.strip() in combined
    assert any("(1)" in chunk.body for chunk in chunks), "the lead-in text survives somewhere"


def test_chunk_ids_are_deterministic_and_content_hash_tracks_edits(
    builder: FragmentBuilder,
) -> None:
    builder.add("Paragraf", 2, segment="par_1", designation="§ 1", content="§ 1")
    builder.add("Odstavec_Dc", 3, segment="odst_1", designation="(1)", content="(1) Původní text.")

    first = chunker().chunk(builder.document())
    second = chunker().chunk(builder.document())

    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert [c.point_id for c in first] == [c.point_id for c in second]

    builder.fragments[-1] = builder.fragments[-1].model_copy(
        update={"content": "(1) Novelizovaný text."}
    )
    amended = chunker().chunk(builder.document())

    assert amended[0].chunk_id == first[0].chunk_id, (
        "identity survives amendments (upsert in place)"
    )
    assert amended[0].content_hash != first[0].content_hash, "but the change is detectable"


@pytest.mark.parametrize(
    ("mode", "in_body", "in_metadata"),
    [
        (FootnoteMode.METADATA, False, True),
        (FootnoteMode.INLINE, True, False),
        (FootnoteMode.IGNORE, False, False),
    ],
)
def test_footnote_modes(
    builder: FragmentBuilder, mode: FootnoteMode, in_body: bool, in_metadata: bool
) -> None:
    builder.add("Paragraf", 2, segment="par_1", designation="§ 1", content="§ 1")
    builder.add(
        "Odstavec_Dc", 3, segment="odst_1", designation="(1)", content="(1) Podle předpisů1)."
    )
    builder.add("Virtual_PPC", 1, segment="poznamkypodcarou")
    builder.add("PPC", 2, segment="ppc_1", designation="1)", content="1) Směrnice Rady 98/59/ES.")

    chunk = chunker(footnote_mode=mode).chunk(builder.document())[0]

    assert ("Směrnice Rady" in chunk.body) is in_body
    assert bool(chunk.footnotes) is in_metadata


def test_payload_is_flat_and_filterable(builder: FragmentBuilder) -> None:
    builder.add("Paragraf", 2, segment="par_1", designation="§ 1", content="§ 1")
    builder.add("Odstavec_Dc", 3, segment="odst_1", designation="(1)", content="(1) Text.")

    payload = chunker().chunk(builder.document())[0].to_payload()

    assert payload["namespace"] == "laws"
    assert payload["law_year"] == 2020
    assert payload["citation"] == "§ 1 zákon č. 1/2020 Sb."
    assert payload["breadcrumb"] == []
    assert all(not isinstance(value, dict) for key, value in payload.items() if key != "footnotes")


def test_split_sentences_respects_legal_abbreviations() -> None:
    text = "Podle § 12 odst. 1 písm. a) zákona č. 262/2006 Sb. platí pravidlo. Další věta zde."

    assert split_sentences(text) == [
        "Podle § 12 odst. 1 písm. a) zákona č. 262/2006 Sb. platí pravidlo.",
        "Další věta zde.",
    ]


def test_hard_wrap_never_exceeds_budget() -> None:
    counter = HeuristicTokenCounter()
    pieces = hard_wrap(" ".join(["slovo"] * 300), 40, counter)

    assert len(pieces) > 1
    assert all(counter(piece) <= 40 for piece in pieces[:-1])
    assert " ".join(pieces).split() == ["slovo"] * 300, "no words lost"
