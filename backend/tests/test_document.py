"""Parsing: tree reconstruction, heading attribution, metadata, footnotes."""

from __future__ import annotations

from tests.conftest import FragmentBuilder

from law_agent.ingestion.laws import Role


def test_tree_is_built_from_depth_not_from_fragment_id(builder: FragmentBuilder) -> None:
    """``Block_*`` wrappers are not path prefixes of what they wrap.

    ``.../par_1/frag_9`` (the block) wraps ``.../par_1/odst_1``, so parsing by
    path prefix would mis-parent the paragraph. ``depth`` models it correctly.
    """
    builder.add("Cast", 2, segment="cast_1", designation="ČÁST PRVNÍ", content="ČÁST PRVNÍ")
    builder.add("Paragraf", 3, segment="par_1", designation="§ 1", content="§ 1")
    block = builder.add("Block_Ucinnostni_Ustanoveni", 4, content="")
    builder.add(
        "Odstavec_Dc",
        5,
        designation="(1)",
        content="(1) Text.",
        # Nested under the block by depth, but a sibling of it by path.
        path="dokument/norma/cast_1/par_1/odst_1",
    )

    document = builder.document()
    paragraph = document.get(f"{builder.eli}/dokument/norma/cast_1/par_1/odst_1")

    assert paragraph is not None
    assert paragraph.parent is not None
    assert paragraph.parent.fragment_id == block.fragment_id
    assert paragraph.parent.role is Role.CONTAINER


def test_leading_leaf_heading_titles_its_parent(builder: FragmentBuilder) -> None:
    builder.add("Paragraf", 2, segment="par_1", designation="§ 1", content="§ 1")
    builder.add("Nadpis_pod", 3, heading="Předmět úpravy", content="Předmět úpravy")
    builder.add("Odstavec_Dc", 3, segment="odst_1", designation="(1)", content="(1) Text.")

    document = builder.document()
    section = document.get(f"{builder.eli}/dokument/norma/par_1")

    assert section is not None
    assert document.heading_text(section) == "Předmět úpravy"


def test_heading_with_children_is_structure_not_a_title(builder: FragmentBuilder) -> None:
    """Annexes nest body text under ``Nadpis``; treating it as a title would
    drop the whole subtree."""
    builder.add("Hlavicka_priloha", 2, segment="priloha_0", content="Příloha k zákonu")
    builder.add("Nadpis", 3, heading="Charakteristiky", content="Charakteristiky")
    builder.add("Odstavec_Dc", 4, content="Popis první třídy.")

    document = builder.document()
    annex = document.get(f"{builder.eli}/dokument/norma/priloha_0")

    assert annex is not None
    assert document.own_headings(annex) == []


def test_group_heading_applies_to_following_siblings(builder: FragmentBuilder) -> None:
    builder.add("Hlava", 2, segment="hlava_1", designation="HLAVA I", content="HLAVA I")
    builder.add("Paragraf", 3, segment="par_1", designation="§ 1", content="§ 1")
    builder.add("Odstavec_Dc", 4, segment="odst_1", designation="(1)", content="(1) První.")
    builder.add("Nadpis_nad", 3, heading="Skupinový nadpis", content="Skupinový nadpis")
    builder.add("Paragraf", 3, segment="par_2", designation="§ 2", content="§ 2")
    builder.add("Odstavec_Dc", 4, segment="odst_1", designation="(1)", content="(1) Druhý.")

    document = builder.document()
    first = document.get(f"{builder.eli}/dokument/norma/hlava_1/par_1")
    second = document.get(f"{builder.eli}/dokument/norma/hlava_1/par_2")

    assert first is not None and second is not None
    assert document.group_heading(first) is None
    assert document.group_heading(second) == "Skupinový nadpis"


def test_repealed_subtrees_are_dropped_by_default(builder: FragmentBuilder) -> None:
    builder.add("Paragraf", 2, segment="par_1", designation="§ 1", content="§ 1", is_repealed=True)
    builder.add("Odstavec_Dc", 3, segment="odst_1", designation="(1)", content="(1) Zrušeno.")
    builder.add("Paragraf", 2, segment="par_2", designation="§ 2", content="§ 2")
    builder.add("Odstavec_Dc", 3, segment="odst_1", designation="(1)", content="(1) Platné.")

    document = builder.document()

    assert document.get(f"{builder.eli}/dokument/norma/par_1") is None
    assert document.get(f"{builder.eli}/dokument/norma/par_1/odst_1") is None, "subtree must go too"
    assert document.get(f"{builder.eli}/dokument/norma/par_2") is not None
    assert document.report.dropped_repealed == 1

    kept = builder.document(include_repealed=True)
    assert kept.get(f"{builder.eli}/dokument/norma/par_1") is not None


def test_metadata_from_eli_and_prefix(builder: FragmentBuilder) -> None:
    metadata = builder.document().metadata

    assert metadata.number == "1"
    assert metadata.year == 2020
    assert metadata.version_date == "2024-01-01"
    assert metadata.title == "o testování"
    assert metadata.citation_label == "zákon č. 1/2020 Sb."


def test_unit_labels_disambiguate_by_path(builder: FragmentBuilder) -> None:
    """``(1)``, ``a)`` and ``1.`` are ambiguous alone; the path says which is which."""
    builder.add("Paragraf", 2, segment="par_41", designation="§ 41", content="§ 41")
    builder.add("Odstavec_Dc", 3, segment="odst_1", designation="(1)", content="(1) Text.")
    builder.add("Pismeno_Lb", 4, segment="pism_a", designation="a)", content="a) Text.")
    builder.add("Bod_Dd", 5, segment="bod_1", designation="1.", content="1. Text.")

    document = builder.document()
    base = f"{builder.eli}/dokument/norma/par_41"
    labels = [
        document.unit_label(document.get(path))  # type: ignore[arg-type]
        for path in (base, f"{base}/odst_1", f"{base}/odst_1/pism_a", f"{base}/odst_1/pism_a/bod_1")
    ]

    assert labels == ["§ 41", "odst. 1", "písm. a)", "bod 1."]


def test_footnote_markers_resolve_and_ignore_list_markers(builder: FragmentBuilder) -> None:
    builder.add("Virtual_PPC", 1, segment="poznamkypodcarou")
    builder.add("PPC", 2, segment="ppc_1", designation="1)", content="1) Směrnice Rady 98/59/ES.")

    document = builder.document()

    assert document.footnotes == {"1)": "Směrnice Rady 98/59/ES."}
    assert document.footnote_refs("předpisy Evropské unie1),") == {"1)": "Směrnice Rady 98/59/ES."}
    assert document.footnote_refs("(1) Odstavec a) písmeno") == {}, "designations are not footnotes"
    assert document.footnote_refs("odkaz na 9)") == {}, "unknown markers are dropped"


def test_cross_reference_tail_is_not_mistaken_for_a_footnote(builder: FragmentBuilder) -> None:
    """``(§ 283 až 285)`` ends in ``85)``, which is a real footnote elsewhere.

    Matching it would attach an unrelated note to every chunk that cites a
    three-digit section -- and the resolution filter cannot catch it, because
    the marker genuinely exists in the table.
    """
    builder.add("Virtual_PPC", 1, segment="poznamkypodcarou")
    builder.add("PPC", 2, segment="ppc_85", designation="85)", content="85) Školský zákon.")
    builder.add("PPC", 2, segment="ppc_71", designation="71)", content="71) Obchodní zákoník.")

    document = builder.document()

    assert document.footnote_refs("podle tohoto zákona (§ 283 až 285),") == {}
    assert document.footnote_refs("v rozsahu § 271 až 285 se nepoužije") == {}
    assert document.footnote_refs("podle zvláštního předpisu71)") == {"71)": "Obchodní zákoník."}


def test_unknown_types_are_reported_but_still_carry_text(builder: FragmentBuilder) -> None:
    builder.add("Paragraf", 2, segment="par_1", designation="§ 1", content="§ 1")
    builder.add("Budouci_Novy_Typ", 3, content="Text neznámého typu.")

    document = builder.document()
    node = next(n for n in document.root.walk() if n.type == "Budouci_Novy_Typ")

    assert document.report.unknown_types == {"Budouci_Novy_Typ": 1}
    assert node.role is Role.TEXT, "unknown text-bearing types must not be dropped"
