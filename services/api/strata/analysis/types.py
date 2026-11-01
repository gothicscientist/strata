"""Pydantic result types for analysis functions. All serialise to JSON via ``model_dump()``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from strata.io.types import ArrayModel, NDArray

EXPLORATORY_CAVEAT = (
    "Exploratory distance-based fit: the target's coordinates are approximated as a convex "
    "mixture of source coordinates in a reduced coordinate space (PCA/G25). This is NOT a "
    "formal test of admixture: a good fit does not show that the target descends from these "
    "sources, many different source sets can fit equally well, and proportions depend on "
    "which candidate populations are included. Use qpAdm (f-statistics) for formal testing."
)

FIT_QUALITY_CAVEAT = (
    "Fit quality is a heuristic label based on the residual distance relative to the spread "
    "of the candidate sources in this space; it is not a p-value or a goodness-of-fit test."
)


class CoordinateTable(ArrayModel):
    """Named rows of coordinates in one coordinate space."""

    space: str
    names: list[str]
    matrix: NDArray
    dim_names: list[str] | None = None

    def row(self, name: str):  # noqa: ANN201
        return self.matrix[self.names.index(name)]

    def subset(self, names: list[str]) -> CoordinateTable:
        ix = [self.names.index(n) for n in names]
        return CoordinateTable(
            space=self.space, names=list(names), matrix=self.matrix[ix], dim_names=self.dim_names
        )


class PCAProjection(BaseModel):
    space: str
    names: list[str]
    coordinates: list[list[float]]
    n_snps_used: list[int]
    explained_variance_ratio: list[float]
    note: str = (
        "Least-squares projection on observed SNPs only (smartpca lsqproject: YES). "
        "Projected samples with few SNPs have noisier coordinates; projection is not affected "
        "by the shrinkage of reference-sample scores toward zero, so projected individuals can "
        "appear slightly more spread out than fitted reference individuals."
    )


class Neighbor(BaseModel):
    rank: int
    name: str
    distance: float


class NearestResult(BaseModel):
    space: str
    target: str
    metric: Literal["euclidean", "weighted", "manhattan", "cosine"]
    neighbors: list[Neighbor]


class FitQuality(BaseModel):
    label: Literal["good", "fair", "poor"]
    distance: float
    relative_distance: float = Field(
        description="fit distance / median pairwise distance among the candidate sources"
    )
    best_single_source: str
    best_single_distance: float
    improvement_over_single: float = Field(
        description="1 - fit distance / best single-source distance (0 if no improvement)"
    )
    caveat: str = FIT_QUALITY_CAVEAT


class SourceWeight(BaseModel):
    name: str
    weight: float


class AdmixtureFit(BaseModel):
    kind: Literal["exploratory"] = "exploratory"
    caveat: str = EXPLORATORY_CAVEAT
    space: str
    target: str
    method: Literal["qp", "nnls", "slsqp"]
    sources: list[SourceWeight]
    distance: float = Field(description="Euclidean norm of (fitted - target)")
    residuals: list[float] = Field(description="per-dimension fitted - target")
    fitted: list[float]
    quality: FitQuality | None = None
    converged: bool = True

    def weights(self) -> dict[str, float]:
        return {s.name: s.weight for s in self.sources}


class WeightCI(BaseModel):
    name: str
    weight: float
    mean: float
    se: float
    ci_low: float
    ci_high: float


class BootstrapResult(BaseModel):
    kind: Literal["exploratory"] = "exploratory"
    caveat: str = EXPLORATORY_CAVEAT
    space: str
    target: str
    n_bootstrap: int
    seed: int
    resampled: str = Field(description="what was resampled")
    point: AdmixtureFit
    weights: list[WeightCI]
    distance_mean: float
    distance_ci: tuple[float, float]


class RotationModel(BaseModel):
    rank: int
    sources: list[SourceWeight]
    distance: float
    n_sources: int
    pruned_from: list[str] | None = None


class RotationResult(BaseModel):
    kind: Literal["exploratory"] = "exploratory"
    caveat: str = EXPLORATORY_CAVEAT
    space: str
    target: str
    k_range: tuple[int, int]
    n_candidates: int
    n_models_evaluated: int
    strategy: Literal["exhaustive", "prefiltered"]
    prefiltered_candidates: list[str] | None = None
    min_weight: float
    models: list[RotationModel]
    preferred_rank: int | None = Field(
        None,
        description="rank of the simplest model within the distance tolerance of the best",
    )
    tolerance: float


class LeaveOneOut(BaseModel):
    dropped: str
    distance: float
    delta_distance: float
    weights: list[SourceWeight]
    max_abs_weight_change: float


class JitterSummary(BaseModel):
    sd: float
    n: int
    weight_sd: list[SourceWeight]
    max_weight_sd: float


class SensitivityResult(BaseModel):
    kind: Literal["exploratory"] = "exploratory"
    caveat: str = EXPLORATORY_CAVEAT
    space: str
    target: str
    base: AdmixtureFit
    leave_one_source_out: list[LeaveOneOut]
    leave_one_dimension_out: list[LeaveOneOut]
    jitter: JitterSummary | None
    stable: bool
    stability_note: str


class FStatResult(BaseModel):
    stat: Literal["f2", "f3", "f4"]
    populations: list[str]
    estimate: float
    se: float
    z: float
    n_snps: int
    n_blocks: int
    method: str = (
        "Strata NumPy estimator: unbiased sample-size-corrected f-statistic, "
        "weighted block jackknife SE"
    )
