"""Pydantic models for the ADMIXTOOLS 2 bridge.

Every result model carries ``kind="formal"`` to distinguish f-statistic
inference from the exploratory G25/PCA fits in :mod:`strata.analysis`. The two
must never be presented as equivalent evidence: see :data:`FORMAL_CAVEAT`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

PopName = Annotated[str, Field(min_length=1, max_length=120)]

FORMAL_CAVEAT = (
    "Formal f-statistic result (ADMIXTOOLS 2). qpAdm tests whether a proposed "
    "set of source populations can explain the target's allele-frequency "
    "relationships to the right (outgroup) populations. A model that is not "
    "rejected is consistent with the data, not proven: other untested models "
    "may fit equally well or better, and the p-value depends strongly on the "
    "choice of right populations, on SNP coverage, and on the jackknife block "
    "size. Admixture weights are estimates with standard errors, not exact "
    "ancestry percentages."
)

ROTATION_CAVEAT = (
    "Rotating qpAdm fits many models to the same data. The p-values are not "
    "independent and are not corrected for multiple testing, so the number of "
    "models tested must be reported alongside any 'best' model. Ranking by "
    "p-value selects for models that happen to fit this SNP set; treat the "
    "ranking as a shortlist for scrutiny, not as a posterior over histories."
)


class StrataModel(BaseModel):
    """Base: reject unknown fields on input, keep field order on output."""

    model_config = ConfigDict(extra="forbid", frozen=False, populate_by_name=True)


class RLenientModel(BaseModel):
    """Base for models populated from R output.

    R's table columns vary between ADMIXTOOLS versions (and ``popdrop`` has one
    column per population), so these models keep unknown keys instead of
    failing the whole analysis.
    """

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _drop_r_nulls(cls, data: Any) -> Any:
        """Treat R's ``null`` as "field absent" so the declared default applies.

        ADMIXTOOLS returns an absent table or scalar as JSON ``null`` -- e.g.
        ``f4_var_singular_loadings`` is null whenever the f4 variance matrix is
        well conditioned, and ``popdrop`` is null for a qpWave-style fit. A
        declared ``list[...]`` field rejects an explicit ``None``, so without
        this a perfectly healthy result would fail validation. Every nullable
        field on these models already defaults to ``None``, so dropping the key
        is equivalent for those and correct for the collection fields.
        """
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


# --------------------------------------------------------------------------
# input specs
# --------------------------------------------------------------------------


class _DataSourceMixin(StrataModel):
    """Exactly one of an f2 cache directory or a genotype file prefix."""

    f2_dir: str | None = Field(
        default=None,
        description="Directory of precomputed f2 blocks, as written by extract_f2.",
    )
    geno_prefix: str | None = Field(
        default=None,
        description="EIGENSTRAT/PACKEDANCESTRYMAP/PLINK prefix (no extension).",
    )

    @model_validator(mode="after")
    def _exactly_one_source(self) -> _DataSourceMixin:
        if bool(self.f2_dir) == bool(self.geno_prefix):
            raise ValueError("specify exactly one of 'f2_dir' or 'geno_prefix'")
        return self

    @property
    def data_source(self) -> Literal["f2_dir", "geno_prefix"]:
        return "f2_dir" if self.f2_dir else "geno_prefix"


class _FstatOptions(StrataModel):
    """Options shared by the qpAdm-family wrappers."""

    blgsize: float = Field(
        default=0.05,
        gt=0,
        description="Jackknife block size in Morgan; >=100 is read as base pairs.",
    )
    fudge: float = Field(
        default=1e-4, ge=0, description="Ridge added to the f4 variance diagonal."
    )
    fudge_twice: bool = Field(
        default=False, description="Apply the ridge twice, matching classic qpAdm p-values."
    )
    auto_only: bool = Field(default=True, description="Use autosomes only.")
    poly_only: bool = Field(default=False, description="Drop non-polymorphic sites.")
    constrained: bool = Field(default=False, description="Constrain weights to be >= 0.")
    boot: bool | int = Field(
        default=False,
        description="Block bootstrap instead of jackknife; an int sets the resampling count.",
    )
    allsnps: bool = Field(
        default=False,
        description="Genotype input only: choose SNPs per f4-statistic (classic 'allsnps').",
    )
    maxmiss: float | None = Field(
        default=None, ge=0, le=1, description="Genotype input only: max per-SNP missingness."
    )
    singular_threshold: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Fail if the f4 variance matrix's reciprocal condition number falls below "
            "this (e.g. 1e-12), which signals linearly dependent right populations."
        ),
    )
    threads: int = Field(default=1, ge=1, le=64)

    @model_validator(mode="after")
    def _check_boot(self) -> _FstatOptions:
        if isinstance(self.boot, int) and not isinstance(self.boot, bool) and self.boot < 2:
            raise ValueError("'boot' as an integer must be >= 2")
        return self


class QpAdmSpec(_DataSourceMixin, _FstatOptions):
    """One qpAdm model: a target explained by `left` sources, tested against `right`."""

    target: PopName
    left: list[PopName] = Field(min_length=1, description="Source populations.")
    right: list[PopName] = Field(min_length=2, description="Right / outgroup populations.")
    getcov: bool = Field(default=True, description="Compute weight standard errors.")
    return_f4: bool = Field(default=True, description="Include the fitted-vs-estimated f4 table.")

    @model_validator(mode="after")
    def _check_pops(self) -> QpAdmSpec:
        if len(set(self.left)) != len(self.left):
            raise ValueError("'left' contains duplicate populations")
        if len(set(self.right)) != len(self.right):
            raise ValueError("'right' contains duplicate populations")
        if self.target in self.left:
            raise ValueError("target must not also appear in 'left'")
        if self.target in self.right:
            raise ValueError("target must not also appear in 'right'")
        both = sorted(set(self.left) & set(self.right))
        if both:
            raise ValueError(f"populations on both sides: {', '.join(both)}")
        if len(self.right) <= len(self.left):
            raise ValueError(
                "qpAdm needs strictly more right than left populations "
                f"(got {len(self.left)} left, {len(self.right)} right)"
            )
        return self


class QpAdmRotateSpec(_DataSourceMixin, _FstatOptions):
    """Rotate a candidate pool between the left and right sides."""

    target: PopName
    # `candidates` / `right` are accepted as aliases because that is how the API
    # and agent layers name these in their request payloads.
    leftright: list[PopName] = Field(
        min_length=2,
        validation_alias=AliasChoices("leftright", "candidates"),
        description="Pool distributed between left and right across models.",
    )
    rightfix: list[PopName] = Field(
        default_factory=list,
        validation_alias=AliasChoices("rightfix", "right"),
        description="Populations pinned to the right in every model.",
    )
    min_sources: int = Field(default=1, ge=1)
    max_sources: int | None = Field(default=None, ge=1)
    max_models: int = Field(
        default=400, ge=1, le=20000, description="Refuse to run if enumeration exceeds this."
    )
    full_results: bool = Field(default=True, description="Include per-model weights.")

    @model_validator(mode="after")
    def _check_pops(self) -> QpAdmRotateSpec:
        if len(set(self.leftright)) != len(self.leftright):
            raise ValueError("'leftright' contains duplicate populations")
        if self.target in self.leftright:
            raise ValueError("target must not appear in 'leftright'")
        if self.target in self.rightfix:
            raise ValueError("target must not appear in 'rightfix'")
        clash = sorted(set(self.leftright) & set(self.rightfix))
        if clash:
            raise ValueError(f"populations in both 'leftright' and 'rightfix': {', '.join(clash)}")
        if self.max_sources is not None and self.max_sources < self.min_sources:
            raise ValueError("'max_sources' must be >= 'min_sources'")
        return self


class QpWaveSpec(_DataSourceMixin, _FstatOptions):
    """qpWave: how many admixture waves separate two population sets."""

    left: list[PopName] = Field(min_length=2)
    right: list[PopName] = Field(min_length=2)
    alpha: float = Field(default=0.05, gt=0, lt=1)

    @model_validator(mode="after")
    def _check_pops(self) -> QpWaveSpec:
        both = sorted(set(self.left) & set(self.right))
        if both:
            raise ValueError(f"populations on both sides: {', '.join(both)}")
        return self


class F4Spec(_DataSourceMixin):
    """f4(pop1, pop2; pop3, pop4) over the given population vectors."""

    pop1: list[PopName] = Field(min_length=1)
    pop2: list[PopName] = Field(min_length=1)
    pop3: list[PopName] = Field(min_length=1)
    pop4: list[PopName] = Field(min_length=1)
    comb: bool = Field(
        default=True,
        description="All combinations; if false the four vectors are zipped row-wise.",
    )
    unique_only: bool = Field(default=True, description="Drop permutation-equivalent quadruples.")
    f4mode: bool = Field(default=True, description="False gives D-statistics (genotype input).")
    afprod: bool = Field(
        default=True, description="f2 input only: compute from allele-frequency products."
    )
    blgsize: float = Field(default=0.05, gt=0)
    auto_only: bool = True
    allsnps: bool = False
    maxmiss: float | None = Field(default=None, ge=0, le=1)
    boot: bool | int = False
    threads: int = Field(default=1, ge=1, le=64)

    @model_validator(mode="after")
    def _check(self) -> F4Spec:
        if not self.comb:
            lens = {len(self.pop1), len(self.pop2), len(self.pop3), len(self.pop4)}
            if len(lens) != 1:
                raise ValueError("with comb=False, pop1..pop4 must all have the same length")
        if not self.f4mode and self.data_source != "geno_prefix":
            raise ValueError("D-statistics (f4mode=False) require 'geno_prefix'")
        return self


class ExtractF2Spec(StrataModel):
    """Precompute an f2 block cache from genotype files."""

    geno_prefix: str
    out_dir: str
    pops: list[PopName] = Field(default_factory=list)
    inds: list[str] = Field(default_factory=list)
    blgsize: float = Field(default=0.05, gt=0)
    maxmiss: float = Field(default=0.0, ge=0, le=1)
    minmaf: float = Field(default=0.0, ge=0, le=0.5)
    maxmaf: float = Field(default=0.5, gt=0, le=0.5)
    minac2: bool = False
    auto_only: bool = True
    transitions: bool = True
    transversions: bool = True
    adjust_pseudohaploid: bool = True
    maxmem: int = Field(default=8000, ge=256)
    cols_per_chunk: int | None = Field(default=None, ge=1)
    afprod: bool = True
    fst: bool = True
    overwrite: bool = False
    n_cores: int = Field(default=1, ge=1, le=64)
    threads: int = Field(default=1, ge=1, le=64)

    @model_validator(mode="after")
    def _check(self) -> ExtractF2Spec:
        if self.inds and len(self.inds) != len(self.pops):
            raise ValueError("'inds' and 'pops' must be the same length when 'inds' is given")
        if not self.inds and len(set(self.pops)) != len(self.pops):
            raise ValueError("'pops' contains duplicates; supply 'inds' to group individuals")
        if not self.transitions and not self.transversions:
            raise ValueError("cannot exclude both transitions and transversions")
        return self


# --------------------------------------------------------------------------
# R-side tables
# --------------------------------------------------------------------------


class WeightRow(RLenientModel):
    """One source population's admixture weight."""

    target: str | None = None
    left: str
    weight: float | None = None
    se: float | None = None
    z: float | None = None


class F4Row(RLenientModel):
    """One f4- or D-statistic."""

    pop1: str
    pop2: str
    pop3: str
    pop4: str
    est: float | None = None
    se: float | None = None
    z: float | None = None
    p: float | None = None
    n: float | None = Field(default=None, description="SNPs used (genotype input only).")
    fit: float | None = Field(default=None, description="Model-fitted f4, when available.")


class RankDropRow(RLenientModel):
    """One row of qpAdm/qpWave's rank-drop table."""

    f4rank: int | None = None
    dof: float | None = None
    chisq: float | None = None
    p: float | None = None
    dofdiff: float | None = None
    chisqdiff: float | None = None
    p_nested: float | None = None


class PopDropRow(RLenientModel):
    """One row of qpAdm's population-drop table.

    Also carries one extra float field per source population (the weight in
    that sub-model), which is why unknown keys are kept.
    """

    pat: str | None = None
    wt: float | None = None
    dof: float | None = None
    chisq: float | None = None
    p: float | None = None
    f4rank: int | None = None
    feasible: bool | None = None


class SingularLoadingRow(RLenientModel):
    """Per-right-population leverage on the near-singular f4-variance subspace."""


class RProvenance(RLenientModel):
    """What produced a result, for the report and the MANIFEST."""

    admixtools_version: str | None = None
    r_version: str | None = None
    r_version_string: str | None = None
    platform: str | None = None
    contract: str | None = None
    timestamp_utc: str | None = None


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------


class FormalResult(RLenientModel):
    """Base for every f-statistic result."""

    kind: Literal["formal"] = "formal"
    engine: Literal["admixtools2"] = "admixtools2"
    analysis: str
    caveat: str = FORMAL_CAVEAT
    provenance: RProvenance = Field(default_factory=RProvenance)
    elapsed_seconds: float | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class Feasibility(StrataModel):
    """Interpretation of a qpAdm fit. Heuristic, and labelled as such."""

    verdict: Literal["plausible", "marginal", "rejected", "infeasible", "undetermined"]
    reasons: list[str] = Field(default_factory=list)
    p_passes: bool | None = None
    weights_in_unit_interval: bool | None = None
    weights_well_determined: bool | None = None
    well_conditioned: bool | None = None
    p_threshold: float = 0.05
    marginal_p_threshold: float = 0.01
    max_relative_se: float = 0.5
    note: str = (
        "Heuristic summary of standard qpAdm reporting conventions, not a formal "
        "model-selection procedure. 'plausible' means the model was not rejected "
        "and its weights are physically interpretable; it does not mean the model "
        "is correct or that competing models were excluded."
    )


class QpAdmResult(FormalResult):
    analysis: Literal["qpadm"] = "qpadm"
    target: str
    left: list[str]
    right: list[str]
    data_source: Literal["f2_dir", "geno_prefix"]
    weights: list[WeightRow] = Field(default_factory=list)
    f4: list[F4Row] = Field(default_factory=list)
    rankdrop: list[RankDropRow] = Field(default_factory=list)
    popdrop: list[PopDropRow] = Field(default_factory=list)
    p: float | None = None
    chisq: float | None = None
    dof: float | None = None
    f4rank: int | None = None
    f4_var_rcond: float | None = None
    f4_var_singular_loadings: list[SingularLoadingRow] = Field(default_factory=list)
    feasibility: Feasibility | None = None


class RotateModelResult(RLenientModel):
    """One model from a rotation run."""

    model_config = ConfigDict(extra="allow", protected_namespaces=())

    model_index: int
    rank: int | None = None
    left: list[str]
    right: list[str]
    n_sources: int
    f4rank: int | None = None
    p: float | None = None
    chisq: float | None = None
    dof: float | None = None
    feasible: bool | None = None
    f4_var_rcond: float | None = None
    weights: list[WeightRow] = Field(default_factory=list)
    feasibility: Feasibility | None = None


class QpAdmRotateResult(FormalResult):
    analysis: Literal["qpadm_rotate"] = "qpadm_rotate"
    target: str
    leftright: list[str]
    rightfix: list[str] = Field(default_factory=list)
    data_source: Literal["f2_dir", "geno_prefix"]
    n_models_enumerated: int
    n_models_tested: int
    models: list[RotateModelResult] = Field(default_factory=list)
    rotation_caveat: str = ROTATION_CAVEAT


class QpWaveResult(FormalResult):
    analysis: Literal["qpwave"] = "qpwave"
    left: list[str]
    right: list[str]
    data_source: Literal["f2_dir", "geno_prefix"]
    rankdrop: list[RankDropRow] = Field(default_factory=list)
    f4: list[F4Row] = Field(default_factory=list)
    alpha: float = 0.05
    min_rank_not_rejected: int | None = None
    f4_var_rcond: float | None = None
    f4_var_singular_loadings: list[SingularLoadingRow] = Field(default_factory=list)


class F4Result(FormalResult):
    analysis: Literal["f4", "dstat"] = "f4"
    data_source: Literal["f2_dir", "geno_prefix"]
    f4: list[F4Row] = Field(default_factory=list)
    n_statistics: int = 0


class ExtractF2Result(FormalResult):
    analysis: Literal["extract_f2"] = "extract_f2"
    f2_dir: str
    pops: list[str] = Field(default_factory=list)
    n_pops: int = 0
    n_snps: float | None = None
    n_blocks: float | None = None
    cache_id: str | None = None
    cache_metadata: dict[str, Any] | None = None
    caveat: str = (
        "An f2 cache fixes the SNP set and the filtering options for every "
        "downstream f-statistic. Models built on different caches are not "
        "directly comparable."
    )
