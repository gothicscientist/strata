from __future__ import annotations

import numpy as np
import pytest

from strata.io import (
    MISSING,
    GenotypeDataset,
    IndRecord,
    merge_sample_into_reference,
    read_eigenstrat_dataset,
    read_eigenstrat_snp,
    read_geno,
    read_panel_parquet,
    read_plink_bim,
    write_eigenstrat_dataset,
    write_geno,
    write_panel_parquet,
)
from strata.io.eigenstrat import eigensoft_hash
from strata.io.types import SnpPanel


def _dataset(n_ind: int, n_snp: int, seed: int = 0) -> GenotypeDataset:
    rng = np.random.default_rng(seed)
    geno = rng.integers(0, 3, (n_ind, n_snp)).astype(np.int8)
    geno[rng.random(geno.shape) < 0.1] = MISSING
    chrom = np.array([str(1 + i * 23 // n_snp) for i in range(n_snp)], dtype=object)
    chrom[chrom == "23"] = "X"
    panel = SnpPanel(
        name="t",
        rsid=np.array([f"rs{i}" for i in range(n_snp)], dtype=object),
        chrom=chrom,
        pos=np.arange(1, n_snp + 1, dtype=np.int64) * 1000,
        ref=np.array(["A"] * n_snp, dtype=object),
        alt=np.array(["G"] * n_snp, dtype=object),
        genpos=np.arange(n_snp) * 1e-3,
    )
    inds = [IndRecord(id=f"I{i}", sex="MFU"[i % 3], population=f"P{i % 4}") for i in range(n_ind)]
    return GenotypeDataset(inds=inds, panel=panel, geno=geno)


@pytest.mark.parametrize("fmt", ["eigenstrat", "packedancestrymap"])
@pytest.mark.parametrize("n_ind", [7, 201])  # 201: not a multiple of 4 and record > 48 bytes
def test_roundtrip(tmp_path, fmt, n_ind):
    ds = _dataset(n_ind, 333)
    prefix = tmp_path / "d"
    write_eigenstrat_dataset(prefix, ds, fmt=fmt)
    back = read_eigenstrat_dataset(prefix)
    np.testing.assert_array_equal(back.geno, ds.geno)
    assert [r.id for r in back.inds] == [r.id for r in ds.inds]
    assert [r.sex for r in back.inds] == [r.sex for r in ds.inds]
    np.testing.assert_array_equal(back.panel.chrom, ds.panel.chrom)
    np.testing.assert_array_equal(back.panel.pos, ds.panel.pos)
    np.testing.assert_allclose(back.panel.genpos, ds.panel.genpos)
    sub = read_eigenstrat_dataset(prefix, populations=["P1", "P3"], snp_ids=["rs5", "rs2", "rs300"])
    keep = [i for i, r in enumerate(ds.inds) if r.population in ("P1", "P3")]
    np.testing.assert_array_equal(sub.geno, ds.geno[np.ix_(keep, [5, 2, 300])])
    assert list(sub.panel.rsid) == ["rs5", "rs2", "rs300"]


def test_packed_header(tmp_path):
    ds = _dataset(5, 10)
    write_geno(tmp_path / "g", ds.geno, ind_ids=["a"], snp_ids=["b"])
    raw = (tmp_path / "g").read_bytes()
    assert raw.startswith(b"GENO       5      10 ")
    assert len(raw) == 48 * 11
    # hashit("a") = 97 -> hasharr = 97; written in hex
    assert eigensoft_hash(["a"]) == 97 and b" 61 62" in raw[:48]


def test_eigensoft_hash_wraps_32bit():
    h = eigensoft_hash([f"sample_{i:06d}" for i in range(5000)])
    assert 0 <= h < 2**32


def test_text_geno_crlf(tmp_path):
    p = tmp_path / "x.geno"
    p.write_bytes(b"0129\r\n2210\r\n")
    g = read_geno(p, 4, 2)
    np.testing.assert_array_equal(g, [[0, 2], [1, 2], [2, 1], [MISSING, 0]])


def test_header_mismatch(tmp_path):
    ds = _dataset(5, 10)
    write_geno(tmp_path / "g", ds.geno)
    with pytest.raises(ValueError):
        read_geno(tmp_path / "g", 6, 10)


def test_snp_bim_parquet(tmp_path):
    (tmp_path / "a.snp").write_text("rs1 1 0.01 1000 A G\nrs2 23 0.02 2000 C T\n")
    p = read_eigenstrat_snp(tmp_path / "a.snp")
    assert list(p.chrom) == ["1", "X"] and list(p.ref) == ["A", "C"]
    (tmp_path / "a.bim").write_text("1\trs1\t1.5\t1000\tA\tG\n24\trs2\t0\t2000\tC\tT\n")
    b = read_plink_bim(tmp_path / "a.bim")
    assert list(b.chrom) == ["1", "Y"] and b.genpos[0] == pytest.approx(0.015)
    write_panel_parquet(p, tmp_path / "p.parquet")
    q = read_panel_parquet(tmp_path / "p.parquet")
    assert q.build == "GRCh37" and list(q.rsid) == ["rs1", "rs2"]
    np.testing.assert_allclose(q.genpos, p.genpos)


def test_merge_sample(tmp_path):
    ds = _dataset(12, 50)
    write_eigenstrat_dataset(tmp_path / "ref", ds)
    dosage = np.full(50, np.nan)
    dosage[:10] = [0, 1, 2, 2, 1, 0, 0, 1, 2, 2]
    merged = merge_sample_into_reference(
        tmp_path / "ref",
        tmp_path / "out",
        sample_id="user1",
        sample_population="Target",
        dosage=dosage,
        populations=["P0", "P2"],
    )
    back = read_eigenstrat_dataset(tmp_path / "out")
    assert back.inds[-1].id == "user1" and back.inds[-1].population == "Target"
    assert len(back.inds) == 1 + sum(r.population in ("P0", "P2") for r in ds.inds)
    np.testing.assert_array_equal(back.geno[-1, :10], dosage[:10])
    assert np.all(back.geno[-1, 10:] == MISSING)
    np.testing.assert_array_equal(back.geno, merged.geno)
    with pytest.raises(ValueError):
        merge_sample_into_reference(
            tmp_path / "ref",
            tmp_path / "o2",
            sample_id="I0",
            sample_population="T",
            dosage=dosage,
        )
