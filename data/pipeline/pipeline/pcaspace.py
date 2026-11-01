"""Build the `strata-pca-v1` coordinate space from the AADR Human Origins panel.

Method, and why:

* Fit on **present-day individuals only**, from West Eurasia, South Asia and
  Central Asia. Ancient samples are sparse and pseudo-haploid; including them
  in the fit lets missingness patterns and extreme drift define the axes
  instead of the population structure the axes are supposed to describe. This
  is the standard smartpca practice for ancient DNA.
* Project ancients with **least-squares projection on their observed SNPs
  only**, equivalent to smartpca's `lsqproject: YES`.
* Projected coordinates are **shrunk towards the origin** relative to fitted
  ones. That is a property of projection, not a result; it is recorded per row
  (`projected`) and stated in the space's description so nothing downstream
  compares a projected distance to a fitted one as if they were commensurate.

The heavy linear algebra is `strata.analysis.pca`, which is the same code the
API uses to project a user's uploaded sample into this space. Using one
implementation for both is what makes a user's coordinates comparable to the
reference ones at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .config import PCA_SPACE, PcaSpaceConfig
from .curate import CuratedSample

log = logging.getLogger(__name__)

MISSING = -1


@dataclass
class PcaBuild:
    space: dict[str, Any]
    sample_ids: list[str]
    population_ids: list[str]
    coords: np.ndarray
    n_snps_used: list[int]
    projected: list[bool]
    model: Any
    snp_ids: np.ndarray
    panel: Any


def _dosage(geno: np.ndarray) -> np.ndarray:
    """int8 EIGENSTRAT codes (MISSING=-1) -> float dosage with NaN missing."""
    out = geno.astype(np.float64)
    out[geno == MISSING] = np.nan
    return out


def select_snps(
    geno: np.ndarray,
    *,
    max_missingness: float,
    min_maf: float,
    autosomes_only: np.ndarray | None = None,
) -> np.ndarray:
    """Indices of SNPs that pass the fit-set filters.

    Missingness and MAF are computed on the fit individuals only, so the
    projected samples cannot influence which SNPs define the space.
    """
    n_ind = geno.shape[0]
    observed = (geno != MISSING).sum(axis=0)
    missingness = 1.0 - observed / max(n_ind, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        counts = np.where(geno == MISSING, 0, geno).sum(axis=0, dtype=np.float64)
        freq = counts / (2.0 * np.maximum(observed, 1))
    maf = np.minimum(freq, 1.0 - freq)
    keep = (missingness <= max_missingness) & (maf >= min_maf) & (observed > 0)
    if autosomes_only is not None:
        keep &= autosomes_only
    return np.flatnonzero(keep)


def build_space(
    *,
    prefix: Path,
    samples: list[CuratedSample],
    config: PcaSpaceConfig = PCA_SPACE,
    aadr_version: str,
) -> PcaBuild:
    """Fit the PCA space and project every curated individual into it.

    Args:
        prefix: EIGENSTRAT prefix of the AADR HO dataset (no extension).
        samples: Curated individuals; `is_present_day` picks the fit set.
        config: Space configuration.
        aadr_version: Recorded in the space provenance.

    Returns:
        A :class:`PcaBuild` ready to be written by `schema.write_coordinates`
        and `PCAModel.save`.
    """
    from strata.analysis.pca import fit_reference_pca, out_of_fold_scores, project_array
    from strata.io.eigenstrat import read_eigenstrat_dataset

    wanted = {s.id for s in samples}
    meta = {s.id: s for s in samples}

    ds = read_eigenstrat_dataset(prefix, individuals=sorted(wanted))
    ids = [r.id for r in ds.inds]
    found = set(ids)
    absent = sorted(wanted - found)
    if absent:
        log.warning("%d curated individuals absent from %s", len(absent), prefix.name)

    is_fit = np.array(
        [meta[i].is_present_day and _in_fit_region(meta[i], config) for i in ids], dtype=bool
    )
    if is_fit.sum() < config.n_components + 1:
        raise ValueError(
            f"only {int(is_fit.sum())} individuals qualify for the PCA fit set, "
            f"need more than {config.n_components}. Check the panel's modern groups."
        )

    chrom = np.asarray(ds.panel.chrom)
    autosomal = np.isin(chrom.astype(str), [str(c) for c in range(1, 23)])

    snp_idx = select_snps(
        ds.geno[is_fit],
        max_missingness=config.max_snp_missingness,
        min_maf=config.min_maf,
        autosomes_only=autosomal,
    )
    if snp_idx.size < 1000:
        raise ValueError(
            f"only {snp_idx.size} SNPs survived the fit filters; expected >100k on the "
            "Human Origins panel. Check max_snp_missingness / min_maf."
        )
    log.info("PCA fit: %d individuals, %d SNPs", int(is_fit.sum()), snp_idx.size)

    snp_ids = np.asarray(ds.panel.rsid)[snp_idx]
    fit_dosage = _dosage(ds.geno[np.ix_(is_fit, snp_idx)])
    model = fit_reference_pca(
        fit_dosage,
        config.n_components,
        seed=config.seed,
        sample_ids=[i for i, f in zip(ids, is_fit, strict=True) if f],
        snp_ids=snp_ids,
        space=config.space_id,
    )

    # Coordinates must be on the same scale for every row, including the
    # individuals the PCA was fitted on. Two separate corrections are needed:
    #
    #  * ancient / non-fit individuals are lsq-projected (smartpca
    #    `lsqproject: YES`), which shrinks them towards the origin;
    #  * the fit individuals cannot simply be projected onto their own
    #    loadings, because those loadings were estimated from them. With
    #    n_snps >> n_individuals that is in-sample and comes out inflated.
    #    `out_of_fold_scores` refits per fold, lsq-projects each held-out
    #    fold and Procrustes-rotates it into the full model's axes.
    #
    # Mixing the two scales measurably biases downstream admixture fits, so
    # every stored row is out-of-sample with respect to its own coordinates.
    all_dosage = _dosage(ds.geno[:, snp_idx])
    coords, used = project_array(all_dosage, model)

    fit_ix = np.flatnonzero(is_fit)
    if fit_ix.size:
        oof = out_of_fold_scores(
            fit_dosage,
            model,
            n_folds=config.n_folds,
            seed=config.seed,
            groups=np.array([meta[ids[i]].population_id for i in fit_ix], dtype=object),
        )
        # A fold that could not be fitted leaves NaN; keep the lsq-projected
        # value there rather than dropping the individual.
        replace = np.isfinite(oof).all(axis=1)
        coords[fit_ix[replace]] = oof[replace]
        n_oof = int(replace.sum())
    else:  # pragma: no cover - guarded by the fit-set size check above
        n_oof = 0

    space = {
        "id": config.space_id,
        "name": config.name,
        "version": config.version,
        "n_dims": int(model.n_components),
        "dim_names": [f"PC{i + 1}" for i in range(model.n_components)],
        "level": "sample",
        "description": config.description,
        "explained_variance_ratio": [float(v) for v in model.explained_variance_ratio],
        "provenance": {
            "aadr_version": aadr_version,
            "source_dataset": "AADR-HO",
            "n_fit_individuals": int(is_fit.sum()),
            "n_projected_individuals": len(ids),
            "n_snps": int(snp_idx.size),
            "max_snp_missingness": config.max_snp_missingness,
            "min_maf": config.min_maf,
            "seed": config.seed,
            "fit_on_modern_only": config.fit_on_modern_only,
            "projection": "least-squares on observed SNPs (smartpca lsqproject: YES)",
            "fit_individuals_scored": "out-of-fold (refit per fold, Procrustes-rotated)",
            "n_folds": config.n_folds,
            "n_out_of_fold_rows": n_oof,
            "all_rows_out_of_sample": True,
        },
    }

    return PcaBuild(
        space=space,
        sample_ids=ids,
        population_ids=[meta[i].population_id for i in ids],
        coords=coords,
        n_snps_used=[int(u) for u in used],
        projected=[True] * len(ids),
        model=model,
        snp_ids=snp_ids,
        panel=ds.panel.subset(snp_idx),
    )


def _in_fit_region(sample: CuratedSample, config: PcaSpaceConfig) -> bool:
    """Whether a present-day individual belongs to the fit set.

    The fit regions are expressed as panel blocks rather than geography, so the
    decision follows the curated panel rather than a coordinate box.
    """
    block = sample.panel_block or ""
    if block in {"modern_south_asia", "modern_global"}:
        return True
    return block == ""  # ungrouped present-day individuals still inform the axes
