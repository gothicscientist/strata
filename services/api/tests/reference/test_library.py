"""ReferenceLibrary tests on a tiny SYNTHETIC derived directory (labels are made up)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from strata.analysis import pca
from strata.io import write_panel_parquet
from strata.io.types import SnpPanel
from strata.reference import ReferenceLibrary, load_library

POPS = [
    dict(
        id="SynA_N",
        group_id="SynA_N.AG",
        name="SynA Neolithic",
        region="West Asia",
        country="Synthland",
        lat=38.0,
        lon=35.0,
        period="Neolithic",
        culture=None,
        date_mean_bp=8000.0,
        date_sd=200.0,
        date_min_bp=7600.0,
        date_max_bp=8400.0,
        n_samples=3,
        data_source="SYNTHETIC",
        publication_ids=["pub1"],
        spaces=["strata-pca-v1"],
    ),
    dict(
        id="SynB_BA",
        group_id="SynB_BA",
        name="SynB Bronze Age",
        region="Europe",
        country="Fakeland",
        lat=50.0,
        lon=10.0,
        period="Bronze Age",
        culture="Corded Ware",
        date_mean_bp=4500.0,
        date_sd=100.0,
        date_min_bp=None,
        date_max_bp=None,
        n_samples=2,
        data_source="SYNTHETIC",
        publication_ids=["pub1", "pub2"],
        spaces=["strata-pca-v1"],
    ),
    dict(
        id="SynC",
        group_id="SynC",
        name="SynC present-day",
        region="Europe",
        country="Fakeland",
        lat=None,
        lon=None,
        period="Present-day",
        culture=None,
        date_mean_bp=0.0,
        date_sd=0.0,
        date_min_bp=0.0,
        date_max_bp=0.0,
        n_samples=1,
        data_source="SYNTHETIC",
        publication_ids=[],
        spaces=[],
    ),
]


@pytest.fixture()
def root(tmp_path):
    pd.DataFrame(POPS).to_parquet(tmp_path / "populations.parquet")
    samples = [
        ("a1", "SynA_N"),
        ("a2", "SynA_N"),
        ("a3", "SynA_N"),
        ("b1", "SynB_BA"),
        ("b2", "SynB_BA"),
        ("c1", "SynC"),
    ]
    pd.DataFrame(
        [
            dict(
                id=s,
                population_id=p,
                sex="U",
                date_mean_bp=None,
                pseudohaploid=True,
                publication_id="pub1",
            )
            for s, p in samples
        ]
    ).to_parquet(tmp_path / "samples.parquet")
    pd.DataFrame(
        [
            dict(id="pub1", citation="Synthetic et al. 2099", year=2099, doi=None, url=None),
            dict(id="pub2", citation="Fixture & Test 2100", year=2100, doi="10.0/x", url=None),
        ]
    ).to_parquet(tmp_path / "publications.parquet")
    (tmp_path / "spaces.json").write_text(
        json.dumps(
            {
                "spaces": [
                    dict(
                        id="strata-pca-v1",
                        name="Synthetic PCA",
                        version="1",
                        n_dims=2,
                        dim_names=["PC1", "PC2"],
                        level="sample",
                    )
                ]
            }
        )
    )
    (tmp_path / "coordinates").mkdir()
    pd.DataFrame(
        dict(
            sample_id=["a1", "a2", "a3", "b1", "b2"],
            PC1=[0.0, 1.0, 2.0, 10.0, 12.0],
            PC2=[0.0, 0.0, 3.0, 1.0, 1.0],
        )
    ).to_parquet(tmp_path / "coordinates" / "strata-pca-v1.parquet")
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"version": "synthetic-test-1"}))
    return tmp_path


def test_absent_data_is_empty_not_invented(tmp_path):
    lib = ReferenceLibrary(tmp_path / "missing")
    assert lib.available is False and lib.version is None
    assert lib.populations() == [] and lib.search("x") == [] and lib.spaces() == []
    with pytest.raises(FileNotFoundError):
        lib.snp_panel()
    with pytest.raises(FileNotFoundError):
        lib.population_means("strata-pca-v1")
    assert lib.status()["missing"] == ["populations.parquet", "samples.parquet"]


def test_load_and_detail(root):
    lib = load_library(root)
    assert lib is load_library(root)  # cached
    assert lib.available and lib.version == "synthetic-test-1"
    det = lib.get_population("SynB_BA")
    assert [p.id for p in det.publications] == ["pub1", "pub2"]
    assert [s.id for s in det.samples] == ["b1", "b2"]
    assert det.group_id == "SynB_BA" and det.culture == "Corded Ware"
    d = det.model_dump(mode="json")
    assert d["source_dataset"] == "SYNTHETIC" and d["lat"] == 50.0
    assert lib.get_population("SynC").lat is None  # null stays null
    with pytest.raises(KeyError):
        lib.get_population("nope")


def test_search(root):
    lib = ReferenceLibrary(root)
    assert [p.id for p in lib.search("syn")] == ["SynA_N", "SynB_BA", "SynC"]
    assert [p.id for p in lib.search("bronze fakeland")] == ["SynB_BA"]
    assert [p.id for p in lib.search("corded")] == ["SynB_BA"]
    assert [p.id for p in lib.search(region="europe")] == ["SynB_BA", "SynC"]
    assert [p.id for p in lib.search(period="Neolithic")] == ["SynA_N"]
    # Date overlap: SynB uses mean +/- 2 sd = 4300..4700.
    assert [p.id for p in lib.search(min_bp=4600, max_bp=7700)] == ["SynA_N", "SynB_BA"]
    assert [p.id for p in lib.search(space="strata-pca-v1")] == ["SynA_N", "SynB_BA"]
    page = lib.search_page("syn", page=2, page_size=2)
    assert page.total == 3 and [p.id for p in page.items] == ["SynC"]
    assert lib.search("SynC")[0].id == "SynC"  # exact match ranks first
    assert lib.facets()["region"] == ["Europe", "West Asia"]


def test_coordinates_and_means(root):
    lib = ReferenceLibrary(root)
    names, mat = lib.population_means("strata-pca-v1")
    assert names == ["SynA_N", "SynB_BA"]
    np.testing.assert_allclose(mat, [[1.0, 1.0], [11.0, 1.0]])
    table, counts = lib.population_table("strata-pca-v1")
    assert counts == {"SynA_N": 3, "SynB_BA": 2} and table.space == "strata-pca-v1"
    ind = lib.population_samples("strata-pca-v1", ["SynB_BA"])
    np.testing.assert_allclose(ind["SynB_BA"], [[10, 1], [12, 1]])
    assert lib.coordinates("strata-pca-v1").names[0] == "a1"
    with pytest.raises(KeyError):
        lib.population_samples("strata-pca-v1", ["SynC"])


def test_panel_and_pca_model(root):
    panel = SnpPanel(
        rsid=np.array(["rs1", "rs2"], dtype=object),
        chrom=np.array(["1", "2"], dtype=object),
        pos=np.array([5, 6]),
        ref=np.array(["A", "C"], dtype=object),
        alt=np.array(["G", "T"], dtype=object),
    )
    write_panel_parquet(panel, root / "snp_panel.parquet")
    (root / "pca").mkdir()
    g = np.random.default_rng(0).integers(0, 3, (10, 20))
    pca.fit_reference_pca(g, 2).save(root / "pca" / "strata-pca-v1.npz")
    lib = ReferenceLibrary(root)
    assert list(lib.snp_panel().rsid) == ["rs1", "rs2"]
    assert lib.pca_model().n_components == 2
