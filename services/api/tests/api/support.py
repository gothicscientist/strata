"""Shared platform test support.

Everything generated here is SYNTHETIC test data (random allele frequencies and coordinates
for made-up populations PopA/PopB/PopC). It exercises the code paths only and carries no
scientific meaning.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

SYNTHETIC_VERSION = "synthetic-test-v1"
POPS = ("PopA", "PopB", "PopC")
N_PER_POP = 8
N_SNPS = 400
G25_DIMS = 25
_PAIRS = [("A", "G"), ("C", "T"), ("A", "C"), ("G", "T"), ("G", "A"), ("T", "C")]


def env_for(tmp: Path, derived: Path | None = None, **extra: str) -> dict[str, str]:
    env = {
        "STRATA_ENV": "test",
        "DATABASE_URL": f"sqlite:///{tmp / 'strata-test.db'}",
        "STRATA_DATA_KEY": base64.b64encode(os.urandom(32)).decode(),
        "STRATA_JOB_MODE": "inline",
        "STRATA_STORAGE_BACKEND": "db",
        "STRATA_DATA_DIR": str(tmp / "data"),
        "STRATA_DERIVED_DIR": str(derived or tmp / "no-derived"),
        "STRATA_LLM_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
        "STRATA_RATE_LIMIT_PER_MINUTE": "100000",
        "STRATA_RATE_LIMIT_BURST": "100000",
        "STRATA_RATE_LIMIT_EXPENSIVE_PER_MINUTE": "100000",
        "STRATA_JOB_BACKOFF_BASE_S": "0.01",
    }
    env.update(extra)
    return env


def reset_platform_caches() -> None:
    from strata.api import deps, science
    from strata.config import reset_settings_cache
    from strata.db.session import reset_engine_cache

    reset_settings_cache()
    reset_engine_cache()
    science.reset_caches()
    deps.reset_rate_limits()
    try:
        from strata.reference import library

        library._load_cached.cache_clear()
    except ImportError:
        pass


def _rng() -> np.random.Generator:
    return np.random.default_rng(20261030)


def synthetic_panel() -> pd.DataFrame:
    rng = _rng()
    pairs = [_PAIRS[i % len(_PAIRS)] for i in range(N_SNPS)]
    chrom = (np.arange(N_SNPS) % 22) + 1
    pos = 1_000_000 + np.arange(N_SNPS) * 10_007
    _ = rng
    return pd.DataFrame(
        {
            "rsid": [f"rs{900000 + i}" for i in range(N_SNPS)],
            "chrom": chrom.astype(str),
            "pos": pos.astype(np.int64),
            "ref": [p[0] for p in pairs],
            "alt": [p[1] for p in pairs],
        }
    )


def population_frequencies() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(7)
    return {p: rng.uniform(0.05, 0.95, N_SNPS) for p in POPS}


def build_synthetic_reference(root: Path) -> Path:
    """Write a complete data/derived tree for SYNTHETIC populations."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from strata.analysis.pca import fit_reference_pca

    root.mkdir(parents=True, exist_ok=True)
    (root / "coordinates").mkdir(exist_ok=True)
    (root / "pca").mkdir(exist_ok=True)
    rng = np.random.default_rng(11)
    panel = synthetic_panel()
    table = pa.Table.from_pandas(panel, preserve_index=False).replace_schema_metadata(
        {"build": "GRCh37", "name": "synthetic-panel"}
    )
    pq.write_table(table, root / "snp_panel.parquet")

    freqs = population_frequencies()
    sample_ids, labels, geno = [], [], []
    for p in POPS:
        for j in range(N_PER_POP):
            sample_ids.append(f"{p}_I{j}")
            labels.append(p)
            geno.append(rng.binomial(2, freqs[p]))
    g_mat = np.vstack(geno).astype(np.float64)
    model = fit_reference_pca(
        g_mat, 4, seed=0, sample_ids=sample_ids, snp_ids=panel["rsid"].to_numpy()
    )
    model.save(root / "pca" / "strata-pca-v1.npz")
    pcs = [f"PC{i + 1}" for i in range(model.n_components)]
    pca_df = pd.DataFrame(model.reference_scores, columns=pcs)
    pca_df.insert(0, "population_id", labels)
    pca_df.insert(0, "sample_id", sample_ids)
    pca_df.to_parquet(root / "coordinates" / "strata-pca-v1.parquet")

    centers = {p: rng.normal(0, 0.05, G25_DIMS) * np.linspace(1, 0.1, G25_DIMS) for p in POPS}
    g_rows = [centers[lab] + rng.normal(0, 0.002, G25_DIMS) for lab in labels]
    g25 = pd.DataFrame(np.vstack(g_rows), columns=[f"PC{i + 1}" for i in range(G25_DIMS)])
    g25.insert(0, "population_id", labels)
    g25.insert(0, "sample_id", sample_ids)
    g25.to_parquet(root / "coordinates" / "g25.parquet")

    pd.DataFrame(
        [
            {
                "id": p,
                "name": f"Synthetic {p}",
                "region": "Testland",
                "country": "Nowhere",
                "period": "Synthetic",
                "date_mean_bp": 5000.0 + 1000 * i,
                "date_sd": 100.0,
                "n_samples": N_PER_POP,
                "data_source": "SYNTHETIC",
                "publication_ids": ["synth2026"],
                "spaces": ["g25", "strata-pca-v1"],
            }
            for i, p in enumerate(POPS)
        ]
    ).to_parquet(root / "populations.parquet")
    pd.DataFrame({"id": sample_ids, "population_id": labels}).to_parquet(root / "samples.parquet")
    pd.DataFrame(
        [{"id": "synth2026", "citation": "Synthetic test fixture (not real data)", "year": 2026}]
    ).to_parquet(root / "publications.parquet")
    spaces = {
        "spaces": [
            {
                "id": "g25",
                "name": "G25-style (synthetic)",
                "version": "1",
                "n_dims": G25_DIMS,
                "dim_names": [f"PC{i + 1}" for i in range(G25_DIMS)],
                "level": "sample",
            },
            {
                "id": "strata-pca-v1",
                "name": "Strata PCA (synthetic)",
                "version": "1",
                "n_dims": model.n_components,
                "dim_names": pcs,
                "level": "sample",
                "explained_variance_ratio": [float(x) for x in model.explained_variance_ratio],
            },
        ]
    }
    (root / "spaces.json").write_text(json.dumps(spaces))
    (root / "MANIFEST.json").write_text(
        json.dumps(
            {
                "version": SYNTHETIC_VERSION,
                "synthetic": True,
                # Shaped like the real pipeline's panel block. `limits` is
                # empty on purpose: a limit here would attach a caveat to
                # every other test's results, and the limit paths are tested
                # directly instead.
                "panel": {
                    "matched_groups": len(POPS),
                    "right_set": [POPS[-1]],
                    "roles": {"context": len(POPS)},
                    "limits": [],
                    "unavailable_labels": {},
                    "missing_labels": [],
                },
            }
        )
    )
    np.save(root / "_g25_centers.npy", np.vstack([centers[p] for p in POPS]))
    return root


def g25_centers(root: Path) -> dict[str, np.ndarray]:
    m = np.load(root / "_g25_centers.npy")
    return dict(zip(POPS, m, strict=True))


def make_23andme(pop: str = "PopB", seed: int = 3, nocall_every: int = 37) -> bytes:
    """A hand-made 23andMe v5-format file for one SYNTHETIC individual of `pop`."""
    panel = synthetic_panel()
    rng = np.random.default_rng(seed)
    dos = rng.binomial(2, population_frequencies()[pop])  # copies of the panel ref allele
    lines = [
        "# This data file generated by 23andMe at: Mon Jan 15 08:12:43 2024",
        "# SYNTHETIC TEST FIXTURE - not a real person's genotypes.",
        "# We are using reference human assembly build 37 (also known as Annotation Release 104).",
        "# rsid\tchromosome\tposition\tgenotype",
    ]
    for i, row in panel.iterrows():
        d = int(dos[i])
        g = row.ref * d + row.alt * (2 - d)
        if nocall_every and i % nocall_every == 0:
            g = "--"
        lines.append(f"{row.rsid}\t{row.chrom}\t{row.pos}\t{g}")
    lines.append("i5000001\t1\t500\tDI")  # an indel row (dropped by the parser)
    return ("\n".join(lines) + "\n").encode()
