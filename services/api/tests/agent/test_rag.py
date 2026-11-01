"""Corpus chunking and retrieval sanity, including the real docs/methods corpus."""

from __future__ import annotations

from pathlib import Path

from strata.agent.rag import (
    BM25Retriever,
    Chunk,
    DenseRetriever,
    KnowledgeBase,
    chunk_markdown,
    default_methods_dir,
    load_methods_corpus,
    metadata_chunks,
    reciprocal_rank_fusion,
    slugify,
    tokenize,
)


def test_chunk_markdown_splits_on_headings(tmp_path: Path) -> None:
    doc = tmp_path / "topic.md"
    doc.write_text(
        "# Document Title\n\nIntro text.\n\n## First Section\n\nAlpha body.\n\n"
        "### Nested\n\nBeta body.\n\n## First Section\n\nDuplicate heading body.\n",
        encoding="utf-8",
    )
    chunks = chunk_markdown(doc)
    ids = [c.id for c in chunks]
    assert ids == [
        "methods/topic#overview",
        "methods/topic#first-section",
        "methods/topic#nested",
        "methods/topic#first-section-2",
    ]
    assert all(c.title.startswith("Document Title - ") for c in chunks)
    assert chunks[1].text == "Alpha body."
    assert chunks[0].source == "docs/methods/topic.md"


def test_slugify_and_tokenize() -> None:
    assert slugify("Choice of Right Populations!") == "choice-of-right-populations"
    assert slugify("###") == "section"
    toks = tokenize("The qpAdm p-value is NOT a ranking score")
    assert "qpadm" in toks and "p-value" in toks
    assert "the" not in toks and "is" not in toks


def test_metadata_chunks_render_records() -> None:
    chunks = metadata_chunks(
        [
            {"kind": "population", "id": "Onge.SG", "name": "Onge", "region": "South Asia"},
            {"kind": "publication", "id": "pub1", "title": "A paper", "year": 2019},
            {"kind": "population", "id": "", "name": "dropped"},
        ]
    )
    assert [c.id for c in chunks] == ["population/Onge.SG", "publication/pub1"]
    assert "region: South Asia" in chunks[0].text
    assert chunks[1].title == "Publication: A paper"


def test_bm25_retrieves_the_relevant_chunk() -> None:
    chunks = [
        Chunk(
            "a#1",
            "Right populations",
            "Right populations must be differentially related to the sources.",
            "x",
        ),
        Chunk("a#2", "Shrinkage", "Projected samples are pulled toward the origin.", "x"),
        Chunk("a#3", "Consumer arrays", "SNP overlap with the 1240k panel limits power.", "x"),
    ]
    r = BM25Retriever(chunks)
    hits = r.search("which right populations should I choose", 2)
    assert hits and hits[0][0].id == "a#1"
    assert r.search("projection shrinkage origin", 1)[0][0].id == "a#2"
    assert r.search("zzzz nonexistent token", 3) == []


def test_bm25_handles_empty_corpus() -> None:
    assert BM25Retriever([]).search("anything", 3) == []


def test_reciprocal_rank_fusion_rewards_agreement() -> None:
    a = Chunk("a", "A", "", "x")
    b = Chunk("b", "B", "", "x")
    c = Chunk("c", "C", "", "x")
    sparse = [(a, 5.0), (b, 4.0)]
    dense = [(b, 0.9), (c, 0.8)]
    fused = reciprocal_rank_fusion([sparse, dense], k=3)
    # b appears in both rankings, so it fuses to the top.
    assert [ch.id for ch, _ in fused][0] == "b"
    assert {ch.id for ch, _ in fused} == {"a", "b", "c"}


def test_dense_retriever_with_stub_embeddings() -> None:
    chunks = [
        Chunk("a", "apples", "fruit orchard", "x"),
        Chunk("b", "engines", "machine torque", "x"),
    ]

    def embed(texts: list[str]) -> list[list[float]]:
        # 2-d: [fruitiness, machineness]
        out = []
        for t in texts:
            low = t.lower()
            out.append(
                [
                    float("fruit" in low or "apple" in low),
                    float("machine" in low or "engine" in low or "torque" in low),
                ]
            )
        return out

    dense = DenseRetriever(chunks, embed)
    assert dense.search("torque in an engine", 1)[0][0].id == "b"

    kb = KnowledgeBase(chunks, embed=embed)
    hits = kb.search("fruit", 2)
    assert hits[0][0].id == "a"


def test_knowledge_base_survives_a_failing_dense_retriever() -> None:
    chunks = [Chunk("a", "qpAdm p-values", "not rejected is not proven", "x")]

    def embed(texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding service down")

    kb = KnowledgeBase(chunks, embed=embed)
    hits = kb.search("qpAdm p-value", 2)
    assert hits and hits[0][0].id == "a"


def test_knowledge_base_source_filter() -> None:
    chunks = [
        Chunk("methods/qpadm#p", "p-values", "qpAdm p-value interpretation", "docs"),
        Chunk("population/Onge.SG", "Onge", "region South Asia qpAdm reference", "library"),
    ]
    kb = KnowledgeBase(chunks)
    assert [c.id for c, _ in kb.search("qpAdm", 5, source="methods")] == ["methods/qpadm#p"]
    assert [c.id for c, _ in kb.search("qpAdm", 5, source="reference")] == ["population/Onge.SG"]
    assert kb.has("methods/qpadm#p") and not kb.has("methods/nope#x")


# ---- the real corpus -------------------------------------------------------------------------


def test_real_methods_corpus_loads_and_covers_required_topics() -> None:
    chunks = load_methods_corpus()
    assert chunks, f"no corpus found at {default_methods_dir()}"
    files = {c.id.split("#")[0] for c in chunks}
    for expected in (
        "methods/pca",
        "methods/g25-coordinates",
        "methods/f-statistics",
        "methods/qpadm",
        "methods/admixtools2",
        "methods/south-asia",
        "methods/consumer-data",
        "methods/uncertainty",
    ):
        assert expected in files, f"missing corpus document {expected}"
    assert all(c.text.strip() for c in chunks)
    assert all(c.id.count("#") == 1 for c in chunks)
    assert len(chunks) == len({c.id for c in chunks}), "chunk ids must be unique"


def test_real_corpus_retrieval_is_relevant() -> None:
    kb = KnowledgeBase(load_methods_corpus())
    cases = [
        ("how do I interpret a qpAdm p-value", "methods/qpadm"),
        ("which right outgroup populations should I pick", "methods/qpadm"),
        ("why are projected ancient samples pulled toward the origin", "methods/pca"),
        ("SNP overlap of a 23andMe file with the 1240k panel", "methods/consumer-data"),
        ("ANI ASI cline Indus periphery steppe ancestry", "methods/south-asia"),
        ("f2 blocks precomputed by ADMIXTOOLS 2", "methods/admixtools2"),
        ("are G25 coordinate fit weights real ancestry proportions", "methods/g25-coordinates"),
        ("f4 statistic block jackknife standard error", "methods/f-statistics"),
    ]
    for query, expected_doc in cases:
        hits = kb.search(query, 3)
        assert hits, query
        assert any(c.id.startswith(expected_doc) for c, _ in hits), (
            f"{query!r} -> {[c.id for c, _ in hits]}, expected {expected_doc}"
        )


def test_real_corpus_states_the_exploratory_formal_distinction() -> None:
    text = "\n".join(c.text.lower() for c in load_methods_corpus())
    assert "not rejected" in text
    assert "exploratory" in text
    assert "shrinkage" in text
    assert "block jackknife" in text
