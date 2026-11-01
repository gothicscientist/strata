"""Tests for the 1000 Genomes South Asian extraction.

The failure mode this guards against is not a crash: it is plausible genotypes
that are wrong. An allele pair matched the wrong way round inverts every call
at that site, a position matched across builds compares unrelated loci, and a
site the panel does not carry would quietly widen the SNP set. Each of those
gets a test; the ones that must be refused assert that nothing is kept.
"""

from __future__ import annotations

import gzip
import io

import numpy as np
import pytest
from pipeline.onekg import (
    MISSING,
    POPULATION_BY_CODE,
    SAS_POPULATIONS,
    ChromExtract,
    OneKgError,
    assemble,
    extract_chromosome,
    ind_records,
    orientation,
    orientation_detail,
    panel_dosage,
    parse_sample_panel,
    vcf_url,
)

from strata.io.types import SnpPanel

PANEL_TEXT = """sample\tpop\tsuper_pop\tgender
HG01A\tGIH\tSAS\tmale
HG01B\tPJL\tSAS\tfemale
HG02A\tCEU\tEUR\tmale
HG02B\tBEB\tSAS\tfemale
"""


def panel_of(rows: list[tuple[str, str, int, str, str]]) -> SnpPanel:
    return SnpPanel(
        name="test",
        build="GRCh37",
        rsid=np.array([r[0] for r in rows], dtype=object),
        chrom=np.array([r[1] for r in rows], dtype=object),
        pos=np.array([r[2] for r in rows], dtype=np.int64),
        ref=np.array([r[3] for r in rows], dtype=object),
        alt=np.array([r[4] for r in rows], dtype=object),
    )


def vcf(body: str, samples: list[str]) -> list[bytes]:
    header = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + "\t".join(samples)
    text = "##fileformat=VCFv4.1\n" + header + "\n" + body
    return [line.encode() + b"\n" for line in text.splitlines()]


# ------------------------------------------------------------------ samples


def test_only_the_requested_populations_are_kept() -> None:
    assert parse_sample_panel(PANEL_TEXT) == {"HG01A": "GIH", "HG01B": "PJL", "HG02B": "BEB"}


def test_an_empty_selection_is_an_error_not_an_empty_run() -> None:
    """An empty result would look like a successful run that found nothing."""
    with pytest.raises(OneKgError, match="no samples"):
        parse_sample_panel("sample\tpop\nHG1\tCEU\n")


def test_every_declared_population_is_addressable_by_code() -> None:
    assert set(POPULATION_BY_CODE) == {p.code for p in SAS_POPULATIONS}
    # The group IDs must stay distinguishable from an AADR group of the same
    # name: the two have different coverage and must never be pooled.
    assert all(p.group_id.endswith("_1000G") for p in SAS_POPULATIONS)


def test_the_release_url_names_the_phase_three_callset() -> None:
    url = vcf_url("22")
    assert url.startswith("https://ftp.1000genomes.ebi.ac.uk/")
    assert "chr22" in url and "20130502" in url


# ------------------------------------------------------------------ alleles


@pytest.mark.parametrize(
    ("ref", "alt", "a1", "a2", "expected"),
    [
        ("A", "G", "G", "A", 1),  # ALT is the counted allele
        ("A", "G", "A", "G", -1),  # counted allele is REF, so 2 - dosage
        ("T", "C", "G", "A", 1),  # strand flip, unambiguous pair
        ("T", "C", "A", "G", -1),  # strand flip the other way round
        ("A", "G", "C", "T", 1),  # complementary pair: a flip, not a different site
        ("A", "G", "C", "A", None),  # shares an allele but is not the same pair
        ("A", "AT", "A", "T", None),  # indel
        ("A", "G", "A", "A", None),  # degenerate panel row
    ],
)
def test_orientation(ref, alt, a1, a2, expected) -> None:
    assert orientation(ref, alt, a1, a2) == expected


def test_a_strand_flip_is_reported_as_one() -> None:
    """An unexpected share of flipped sites means panel and callset disagree."""
    assert orientation_detail("T", "C", "G", "A") == (1, True)
    assert orientation_detail("A", "G", "G", "A") == (1, False)
    assert orientation_detail("A", "G", "C", "A") == (None, False)


def test_a_strand_ambiguous_site_is_dropped_rather_than_guessed() -> None:
    """A/T and C/G cannot be resolved; guessing inverts every call at the site."""
    assert orientation("A", "T", "T", "A") == 1  # direct match is still fine
    assert orientation("A", "T", "G", "C") is None  # would need an unprovable flip
    assert orientation("C", "G", "A", "T") is None


# ------------------------------------------------------------------ extraction


def test_only_panel_positions_are_kept() -> None:
    panel = panel_of([("rs1", "22", 100, "A", "G"), ("rs2", "22", 300, "C", "T")])
    lines = vcf(
        "22\t100\trs1\tG\tA\t.\tPASS\t.\tGT\t0|0\t1|1\n"
        "22\t200\trsX\tC\tT\t.\tPASS\t.\tGT\t0|1\t0|1\n"
        "22\t300\trs2\tC\tT\t.\tPASS\t.\tGT\t0|1\t1|1\n",
        ["HG01A", "HG01B"],
    )

    out = extract_chromosome(
        lines, panel=panel, chrom="22", samples={"HG01A": "GIH", "HG01B": "PJL"}
    )

    assert out.snp_idx.tolist() == [0, 1]
    assert out.stats["sites_seen"] == 3
    assert out.stats["at_panel_position"] == 2


def test_genotypes_count_the_panels_allele_in_either_orientation() -> None:
    # rs1: VCF REF=G ALT=A, panel ref(counted)=A -> ALT dosage counts it.
    # rs2: VCF REF=C ALT=T, panel ref(counted)=C -> 2 - ALT dosage.
    panel = panel_of([("rs1", "22", 100, "A", "G"), ("rs2", "22", 300, "C", "T")])
    lines = vcf(
        "22\t100\trs1\tG\tA\t.\tPASS\t.\tGT\t0|0\t1|1\n"
        "22\t300\trs2\tC\tT\t.\tPASS\t.\tGT\t0|1\t1|1\n",
        ["HG01A", "HG01B"],
    )

    out = extract_chromosome(
        lines, panel=panel, chrom="22", samples={"HG01A": "GIH", "HG01B": "PJL"}
    )

    assert out.geno.tolist() == [[0, 1], [2, 0]]


def test_a_missing_call_stays_missing() -> None:
    panel = panel_of([("rs1", "22", 100, "A", "G")])
    lines = vcf("22\t100\trs1\tG\tA\t.\tPASS\t.\tGT\t.|.\t0|.\n", ["HG01A", "HG01B"])

    out = extract_chromosome(
        lines, panel=panel, chrom="22", samples={"HG01A": "GIH", "HG01B": "PJL"}
    )

    assert out.geno.tolist() == [[MISSING], [MISSING]]


def test_multiallelic_and_mismatched_sites_are_counted_and_dropped() -> None:
    panel = panel_of([("rs1", "22", 100, "A", "G"), ("rs2", "22", 200, "A", "G")])
    lines = vcf(
        "22\t100\trs1\tG\tA,T\t.\tPASS\t.\tGT\t0|1\n"
        "22\t200\trs2\tC\tG\t.\tPASS\t.\tGT\t0|1\n",
        ["HG01A"],
    )

    out = extract_chromosome(lines, panel=panel, chrom="22", samples={"HG01A": "GIH"})

    assert out.snp_idx.size == 0
    assert out.stats["not_biallelic"] == 1
    assert out.stats["allele_mismatch"] == 1


def test_only_the_requested_samples_are_read() -> None:
    panel = panel_of([("rs1", "22", 100, "A", "G")])
    lines = vcf(
        "22\t100\trs1\tG\tA\t.\tPASS\t.\tGT\t0|0\t1|1\t1|1\n",
        ["HG01A", "HG02A", "HG01B"],
    )

    out = extract_chromosome(
        lines, panel=panel, chrom="22", samples={"HG01A": "GIH", "HG01B": "PJL"}
    )

    assert out.geno.shape == (2, 1)
    assert out.geno[:, 0].tolist() == [0, 2]  # HG02A (CEU) skipped


def test_a_panel_on_another_build_is_refused() -> None:
    """Phase 3 is GRCh37; matching positions across builds compares other loci."""
    panel = panel_of([("rs1", "22", 100, "A", "G")])
    panel = panel.model_copy(update={"build": "GRCh38"})

    with pytest.raises(OneKgError, match="GRCh37"):
        extract_chromosome([], panel=panel, chrom="22", samples={"HG01A": "GIH"})


def test_a_position_carrying_two_panel_rows_is_not_matched() -> None:
    """Which row the site belongs to is unknowable, so neither is offered."""
    panel = panel_of([("rs1", "22", 100, "A", "G"), ("rs1b", "22", 100, "C", "T")])
    lines = vcf("22\t100\trs1\tG\tA\t.\tPASS\t.\tGT\t0|1\n", ["HG01A"])

    out = extract_chromosome(lines, panel=panel, chrom="22", samples={"HG01A": "GIH"})

    assert out.snp_idx.size == 0
    assert out.stats["at_panel_position"] == 0


def test_a_data_line_before_the_header_is_an_error() -> None:
    with pytest.raises(OneKgError, match="#CHROM"):
        extract_chromosome(
            [b"22\t100\trs1\tG\tA\t.\tPASS\t.\tGT\t0|1\n"],
            panel=panel_of([("rs1", "22", 100, "A", "G")]),
            chrom="22",
            samples={"HG01A": "GIH"},
        )


def test_a_real_gzip_stream_reads(tmp_path) -> None:
    """The fetch path hands gzip bytes straight through; keep that readable."""
    panel = panel_of([("rs1", "22", 100, "A", "G")])
    raw = b"".join(vcf("22\t100\trs1\tG\tA\t.\tPASS\t.\tGT\t1|1\n", ["HG01A"]))
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(raw)
    with gzip.GzipFile(fileobj=io.BytesIO(buf.getvalue())) as gz:
        out = extract_chromosome(gz, panel=panel, chrom="22", samples={"HG01A": "GIH"})

    assert out.geno.tolist() == [[2]]


# ------------------------------------------------------------------ assembly


def test_assemble_orders_by_panel_row() -> None:
    a = ChromExtract("22", np.array([5, 7]), np.array([[0, 1], [2, 0]], dtype=np.int8))
    b = ChromExtract("1", np.array([1, 2]), np.array([[1, 1], [0, 2]], dtype=np.int8))

    geno, snp_idx = assemble(
        [a, b],
        panel=panel_of([("rs", "1", i, "A", "G") for i in range(8)]),
        sample_ids=["HG01A", "HG01B"],
        samples={"HG01A": "GIH", "HG01B": "PJL"},
    )

    assert snp_idx.tolist() == [1, 2, 5, 7]
    assert geno.tolist() == [[1, 1, 0, 1], [0, 2, 2, 0]]


def test_the_same_panel_row_from_two_chromosomes_is_an_error() -> None:
    dup = [
        ChromExtract("22", np.array([3]), np.array([[1]], dtype=np.int8)),
        ChromExtract("21", np.array([3]), np.array([[2]], dtype=np.int8)),
    ]

    with pytest.raises(OneKgError, match="more than one chromosome"):
        assemble(
            dup,
            panel=panel_of([("rs", "1", i, "A", "G") for i in range(4)]),
            sample_ids=["HG01A"],
            samples={"HG01A": "GIH"},
        )


def test_extracts_disagreeing_on_sample_count_is_an_error() -> None:
    bad = [
        ChromExtract("22", np.array([0]), np.array([[1]], dtype=np.int8)),
        ChromExtract("21", np.array([1]), np.array([[1], [2]], dtype=np.int8)),
    ]

    with pytest.raises(OneKgError, match="sample count"):
        assemble(
            bad,
            panel=panel_of([("rs", "1", i, "A", "G") for i in range(2)]),
            sample_ids=["HG01A"],
            samples={"HG01A": "GIH"},
        )


def test_sites_not_supplied_are_missing_not_zero() -> None:
    """A zero is a genotype; an unsupplied site must not become one."""
    geno = np.array([[1, 2]], dtype=np.int8)

    full = panel_dosage(geno, np.array([0, 3]), 5)

    assert full.tolist() == [[1, MISSING, MISSING, 2, MISSING]]


def test_ind_records_carry_the_strata_group_id() -> None:
    (rec,) = ind_records(["HG01A"], {"HG01A": "GIH"})

    assert rec.population == "Gujarati_1000G"
    assert rec.id == "HG01A"
