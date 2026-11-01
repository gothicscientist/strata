"""Typed containers for parsed inputs (G25 tables, raw genotypes, SNP panels, harmonised data).

NumPy arrays are carried in pydantic models via ``NDArray``. Arrays holding genotypes are
excluded from serialisation (``exclude=True``) so that a ``model_dump()`` of a parse result
never contains genotype calls; only QC summaries and coordinates serialise.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, PlainValidator


def _to_array(value: Any) -> np.ndarray:
    return value if isinstance(value, np.ndarray) else np.asarray(value)


def _serialise_array(arr: np.ndarray) -> list[Any]:
    out = arr.tolist()
    if arr.dtype.kind == "f":
        # JSON has no NaN; encode missing as null.
        def fix(x: Any) -> Any:
            if isinstance(x, list):
                return [fix(v) for v in x]
            return None if isinstance(x, float) and not np.isfinite(x) else x

        out = fix(out)
    return out


NDArray = Annotated[
    np.ndarray,
    PlainValidator(_to_array),
    PlainSerializer(_serialise_array, return_type=list, when_used="always"),
]

Build = Literal["NCBI36", "GRCh37", "GRCh38", "unknown"]
Vendor = Literal["23andme", "ancestrydna", "ftdna", "myheritage", "livingdna", "vcf", "generic"]


class ArrayModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)


class ParseWarning(BaseModel):
    code: str
    message: str
    count: int | None = None


class G25Table(ArrayModel):
    """Rows of Global25-style coordinates. ``matrix`` is float64 (n_rows, n_dims)."""

    names: list[str]
    matrix: NDArray
    n_dims: int
    scaled: bool | None = Field(
        None,
        description="True if values look like 'scaled' G25 coordinates, False if unscaled, "
        "None if undetermined. Scaled and unscaled coordinates must never be mixed.",
    )
    warnings: list[ParseWarning] = Field(default_factory=list)

    def row(self, name: str) -> np.ndarray:
        return self.matrix[self.names.index(name)]


class SexChromCounts(BaseModel):
    x: int = 0
    y: int = 0
    mt: int = 0
    x_called: int = 0
    y_called: int = 0
    x_het_rate: float | None = None


class InferredSex(BaseModel):
    call: Literal["XY", "XX", "undetermined"]
    method: str = (
        "heuristic: non-PAR chrX heterozygosity and chrY call rate; not a clinical or "
        "definitive determination"
    )
    heuristic: Literal[True] = True


class QCReport(BaseModel):
    vendor: Vendor
    vendor_detail: str | None = None
    build: Build
    build_source: Literal["header", "landmarks", "assumed", "unknown"]
    n_lines: int
    n_markers: int = Field(description="markers kept (SNVs, incl. no-calls)")
    n_called: int
    n_nocalls: int
    call_rate: float
    n_indels_dropped: int
    n_internal_ids: int = Field(description="vendor-internal ids (e.g. 23andMe i-ids), kept")
    n_invalid_dropped: int
    n_duplicates_dropped: int
    n_haploid_calls: int
    autosomal_het_rate: float | None
    sex_chromosomes: SexChromCounts
    inferred_sex: InferredSex
    warnings: list[ParseWarning] = Field(default_factory=list)


class RawGenotypes(ArrayModel):
    """Single-sample genotype calls. Missing calls have allele1 == allele2 == '-'.

    Hemizygous single-allele calls (e.g. male chrX) are stored as homozygous.
    """

    vendor: Vendor
    build: Build
    rsid: NDArray = Field(exclude=True)
    chrom: NDArray = Field(exclude=True, description="'1'..'22','X','Y','XY','MT'")
    pos: NDArray = Field(exclude=True)
    allele1: NDArray = Field(exclude=True)
    allele2: NDArray = Field(exclude=True)
    qc: QCReport

    @property
    def n(self) -> int:
        return int(self.rsid.shape[0])


class SnpPanel(ArrayModel):
    """SNP panel. ``ref`` is the *counted* allele (EIGENSTRAT .snp column 5 / PLINK A1): genotype
    values in EIGENSTRAT/PACKEDANCESTRYMAP files count copies of it. ``genpos`` is in Morgans."""

    name: str = "panel"
    build: Build = "GRCh37"
    rsid: NDArray
    chrom: NDArray
    pos: NDArray
    ref: NDArray
    alt: NDArray
    genpos: NDArray | None = None

    @property
    def n(self) -> int:
        return int(self.rsid.shape[0])

    def subset(self, idx: np.ndarray) -> SnpPanel:
        return SnpPanel(
            name=self.name,
            build=self.build,
            rsid=self.rsid[idx],
            chrom=self.chrom[idx],
            pos=self.pos[idx],
            ref=self.ref[idx],
            alt=self.alt[idx],
            genpos=None if self.genpos is None else self.genpos[idx],
        )


class OverlapStats(BaseModel):
    n_panel: int
    n_input: int
    matched_by_rsid: int
    matched_by_position: int
    n_matched: int
    n_strand_flipped: int
    n_ambiguous_dropped: int
    n_allele_mismatch: int
    n_nocall: int
    n_usable: int
    overlap_fraction: float = Field(description="n_usable / n_panel")
    mismatch_examples: list[str] = Field(default_factory=list, description="rsIDs only")
    position_fallback_used: bool


class HarmonizedGenotypes(ArrayModel):
    """Dosage aligned to panel order: copies of ``counted_allele`` (0/1/2), NaN missing."""

    panel_name: str
    build: Build
    counted_allele: Literal["ref", "alt"] = "ref"
    dosage: NDArray = Field(exclude=True)
    overlap: OverlapStats
    warnings: list[ParseWarning] = Field(default_factory=list)


class IndRecord(BaseModel):
    id: str
    sex: Literal["M", "F", "U"] = "U"
    population: str
