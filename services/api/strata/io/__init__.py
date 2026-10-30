"""Input parsing, validation and harmonisation (pure, no network)."""

from strata.io.eigenstrat import (
    MISSING,
    GenotypeDataset,
    merge_sample_into_reference,
    read_eigenstrat_dataset,
    read_eigenstrat_snp,
    read_geno,
    read_ind,
    read_panel_parquet,
    read_plink_bim,
    write_eigenstrat_dataset,
    write_geno,
    write_panel_parquet,
)
from strata.io.errors import InputFormatError
from strata.io.g25 import parse_g25
from strata.io.harmonize import harmonize
from strata.io.rawdna import detect_format, parse_raw_dna
from strata.io.types import (
    G25Table,
    HarmonizedGenotypes,
    IndRecord,
    OverlapStats,
    QCReport,
    RawGenotypes,
    SnpPanel,
)

__all__ = [
    "MISSING",
    "G25Table",
    "GenotypeDataset",
    "HarmonizedGenotypes",
    "IndRecord",
    "InputFormatError",
    "OverlapStats",
    "QCReport",
    "RawGenotypes",
    "SnpPanel",
    "detect_format",
    "harmonize",
    "merge_sample_into_reference",
    "parse_g25",
    "parse_raw_dna",
    "read_eigenstrat_dataset",
    "read_eigenstrat_snp",
    "read_geno",
    "read_ind",
    "read_panel_parquet",
    "read_plink_bim",
    "write_eigenstrat_dataset",
    "write_geno",
    "write_panel_parquet",
]
