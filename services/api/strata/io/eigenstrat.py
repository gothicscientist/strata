"""EIGENSTRAT / PACKEDANCESTRYMAP / PLINK .bim readers and writers.

In-memory genotype matrices are ``int8`` arrays of shape (n_individuals, n_snps) holding the
number of copies of the panel's counted allele (``SnpPanel.ref``, .snp column 5) with
``MISSING = -1``. Readers support individual and SNP subsetting through ``np.memmap`` so only
the requested rows are paged in; PACKEDANCESTRYMAP is decoded with vectorised bit shifts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from strata.io.errors import InputFormatError
from strata.io.types import Build, IndRecord, SnpPanel

MISSING = -1
GenoFormat = Literal["eigenstrat", "packedancestrymap"]

_CHROM_IN = {"23": "X", "24": "Y", "90": "MT", "91": "XY", "25": "XY", "26": "MT"}
_CHROM_OUT = {"X": "23", "Y": "24", "MT": "90", "XY": "91"}


# --------------------------------------------------------------------------- SNP / IND files


def _norm_chrom(s: pd.Series) -> np.ndarray:
    c = s.astype(str).str.upper().str.removeprefix("CHR").replace(_CHROM_IN)
    return c.to_numpy(dtype=object)


def read_eigenstrat_snp(
    path: str | Path, *, build: Build = "GRCh37", name: str | None = None
) -> SnpPanel:
    """Read an EIGENSTRAT ``.snp`` file: id chrom genpos(Morgans) physpos [ref alt]."""
    df = pd.read_csv(path, sep=r"\s+", header=None, dtype=str, engine="c")
    if df.shape[1] < 4:
        raise InputFormatError(".snp file needs at least 4 columns")
    ref = df[4] if df.shape[1] > 4 else pd.Series("X", index=df.index)
    alt = df[5] if df.shape[1] > 5 else pd.Series("X", index=df.index)
    return SnpPanel(
        name=name or Path(path).stem,
        build=build,
        rsid=df[0].to_numpy(dtype=object),
        chrom=_norm_chrom(df[1]),
        pos=pd.to_numeric(df[3]).to_numpy(dtype=np.int64),
        ref=ref.str.upper().to_numpy(dtype=object),
        alt=alt.str.upper().to_numpy(dtype=object),
        genpos=pd.to_numeric(df[2]).to_numpy(dtype=np.float64),
    )


def read_plink_bim(
    path: str | Path, *, build: Build = "GRCh37", name: str | None = None
) -> SnpPanel:
    """Read a PLINK ``.bim``: chrom id cM pos A1 A2. ``ref`` = A1 (the allele PLINK counts and
    convertf maps to .snp column 5), ``alt`` = A2. Genetic position converted to Morgans."""
    df = pd.read_csv(path, sep=r"\s+", header=None, dtype=str, engine="c")
    if df.shape[1] != 6:
        raise InputFormatError(".bim file must have 6 columns")
    return SnpPanel(
        name=name or Path(path).stem,
        build=build,
        rsid=df[1].to_numpy(dtype=object),
        chrom=_norm_chrom(df[0]),
        pos=pd.to_numeric(df[3]).to_numpy(dtype=np.int64),
        ref=df[4].str.upper().to_numpy(dtype=object),
        alt=df[5].str.upper().to_numpy(dtype=object),
        genpos=pd.to_numeric(df[2]).to_numpy(dtype=np.float64) / 100.0,
    )


def read_panel_parquet(path: str | Path, *, name: str | None = None) -> SnpPanel:
    """Read a panel parquet (columns rsid, chrom, pos, ref, alt[, genpos]; build in metadata)."""
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    meta = table.schema.metadata or {}
    build = meta.get(b"build", b"GRCh37").decode()
    df = table.to_pandas()
    return SnpPanel(
        name=name or meta.get(b"name", Path(path).stem.encode()).decode(),
        build=build,  # type: ignore[arg-type]
        rsid=df["rsid"].astype(str).to_numpy(dtype=object),
        chrom=df["chrom"].astype(str).to_numpy(dtype=object),
        pos=df["pos"].to_numpy(dtype=np.int64),
        ref=df["ref"].astype(str).to_numpy(dtype=object),
        alt=df["alt"].astype(str).to_numpy(dtype=object),
        genpos=df["genpos"].to_numpy(dtype=np.float64) if "genpos" in df else None,
    )


def write_panel_parquet(panel: SnpPanel, path: str | Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    cols = {
        "rsid": pa.array(panel.rsid.astype(str)),
        "chrom": pa.array(panel.chrom.astype(str)),
        "pos": pa.array(panel.pos.astype(np.int64)),
        "ref": pa.array(panel.ref.astype(str)),
        "alt": pa.array(panel.alt.astype(str)),
    }
    if panel.genpos is not None:
        cols["genpos"] = pa.array(panel.genpos.astype(np.float64))
    table = pa.table(cols).replace_schema_metadata({"build": panel.build, "name": panel.name})
    pq.write_table(table, path)


def read_ind(path: str | Path) -> list[IndRecord]:
    df = pd.read_csv(path, sep=r"\s+", header=None, dtype=str, engine="c")
    sex = df[1].str.upper().where(df[1].str.upper().isin(["M", "F"]), "U")
    return [IndRecord(id=i, sex=s, population=p) for i, s, p in zip(df[0], sex, df[2], strict=True)]


def write_ind(inds: list[IndRecord], path: str | Path) -> None:
    with open(path, "w") as fh:
        for r in inds:
            fh.write(f"{r.id:>20} {r.sex} {r.population:>20}\n")


def write_eigenstrat_snp(panel: SnpPanel, path: str | Path) -> None:
    gen = panel.genpos if panel.genpos is not None else np.zeros(panel.n)
    with open(path, "w") as fh:
        for i in range(panel.n):
            c = _CHROM_OUT.get(str(panel.chrom[i]), str(panel.chrom[i]))
            fh.write(
                f"{panel.rsid[i]:>20} {c:>2} {gen[i]:.6f} {int(panel.pos[i]):>12} "
                f"{panel.ref[i]} {panel.alt[i]}\n"
            )


# --------------------------------------------------------------------------- hashing


def _hashit(s: str) -> int:
    h = 0
    for ch in s.encode():
        h = (h * 23 + (ch - 256 if ch > 127 else ch)) & 0xFFFFFFFF
    return h


def eigensoft_hash(names: list[str]) -> int:
    """EIGENSOFT ``hasharr`` (32-bit wraparound) over individual or SNP ids."""
    h = 0
    for n in names:
        h = ((h * 17) & 0xFFFFFFFF) ^ _hashit(n)
    return h


# --------------------------------------------------------------------------- geno


def detect_geno_format(path: str | Path) -> GenoFormat:
    with open(path, "rb") as fh:
        head = fh.read(5)
    if head.startswith(b"GENO"):
        return "packedancestrymap"
    if head.startswith(b"TGENO"):
        raise InputFormatError("Transposed packed format (TGENO) is not supported; use convertf.")
    return "eigenstrat"


def _packed_rlen(n_ind: int) -> int:
    return max(48, math.ceil(n_ind * 2 / 8))


def _as_index(idx: np.ndarray | None, n: int) -> np.ndarray:
    if idx is None:
        return np.arange(n, dtype=np.int64)
    idx = np.asarray(idx)
    if idx.dtype == bool:
        return np.flatnonzero(idx)
    return idx.astype(np.int64)


def read_geno(
    path: str | Path,
    n_ind: int,
    n_snp: int,
    *,
    ind_idx: np.ndarray | None = None,
    snp_idx: np.ndarray | None = None,
    chunk_snps: int = 65536,
) -> np.ndarray:
    """Read genotypes as int8 (n_selected_ind, n_selected_snp), MISSING=-1."""
    ii = _as_index(ind_idx, n_ind)
    ss = _as_index(snp_idx, n_snp)
    out = np.empty((ii.size, ss.size), dtype=np.int8)
    fmt = detect_geno_format(path)
    if fmt == "packedancestrymap":
        rlen = _packed_rlen(n_ind)
        with open(path, "rb") as fh:
            header = fh.read(rlen).split(b"\x00", 1)[0].split()
        hn_ind, hn_snp = int(header[1]), int(header[2])
        if (hn_ind, hn_snp) != (n_ind, n_snp):
            raise InputFormatError(
                f"geno header ({hn_ind} ind, {hn_snp} snp) disagrees with .ind/.snp "
                f"({n_ind}, {n_snp})"
            )
        mm = np.memmap(path, dtype=np.uint8, mode="r", offset=rlen, shape=(n_snp, rlen))
        byte_ix = ii // 4
        shift = (6 - 2 * (ii % 4)).astype(np.uint8)
        for start in range(0, ss.size, chunk_snps):
            rows = np.asarray(mm[ss[start : start + chunk_snps]][:, byte_ix])
            vals = (rows >> shift[None, :]) & 3
            v = vals.astype(np.int8)
            v[vals == 3] = MISSING
            out[:, start : start + chunk_snps] = v.T
        del mm
        return out
    # Text EIGENSTRAT: one line per SNP, one character per individual.
    size = Path(path).stat().st_size
    width = n_ind + 1
    if size == n_snp * width:
        mm = np.memmap(path, dtype=np.uint8, mode="r", shape=(n_snp, width))
        for start in range(0, ss.size, chunk_snps):
            rows = np.asarray(mm[ss[start : start + chunk_snps]][:, ii])
            v = rows.astype(np.int16) - 48
            v[(v < 0) | (v > 2)] = MISSING
            out[:, start : start + chunk_snps] = v.T.astype(np.int8)
        del mm
        return out
    # Irregular line endings (e.g. CRLF): parse line-wise.
    with open(path, "rb") as fh:
        lines = fh.read().splitlines()
    lines = [ln for ln in lines if ln]
    if len(lines) != n_snp:
        raise InputFormatError(f".geno has {len(lines)} lines, expected {n_snp}")
    for j, s in enumerate(ss):
        row = np.frombuffer(lines[s], dtype=np.uint8)
        if row.size != n_ind:
            raise InputFormatError(f".geno line {s + 1} has {row.size} columns, expected {n_ind}")
        v = row[ii].astype(np.int16) - 48
        v[(v < 0) | (v > 2)] = MISSING
        out[:, j] = v
    return out


def write_geno(
    path: str | Path,
    geno: np.ndarray,
    *,
    fmt: GenoFormat = "packedancestrymap",
    ind_ids: list[str] | None = None,
    snp_ids: list[str] | None = None,
) -> None:
    """Write (n_ind, n_snp) int8 genotypes (MISSING=-1 or any value outside 0..2)."""
    g = np.asarray(geno)
    n_ind, n_snp = g.shape
    valid = (g >= 0) & (g <= 2)
    if fmt == "eigenstrat":
        codes = np.where(valid, g, 9).astype(np.uint8) + 48
        lines = np.concatenate([codes.T, np.full((n_snp, 1), 10, dtype=np.uint8)], axis=1)
        Path(path).write_bytes(lines.tobytes())
        return
    rlen = _packed_rlen(n_ind)
    ih = eigensoft_hash(ind_ids or [])
    sh = eigensoft_hash(snp_ids or [])
    header = f"GENO {n_ind:7d} {n_snp:7d} {ih:x} {sh:x}".encode()
    hdr = header + b"\x00" * (rlen - len(header))
    nb = math.ceil(n_ind / 4)
    v = np.where(valid, g, 3).astype(np.uint8).T  # (n_snp, n_ind)
    pad = nb * 4 - n_ind
    if pad:
        v = np.concatenate([v, np.zeros((n_snp, pad), dtype=np.uint8)], axis=1)
    v = v.reshape(n_snp, nb, 4)
    packed = (v[:, :, 0] << 6) | (v[:, :, 1] << 4) | (v[:, :, 2] << 2) | v[:, :, 3]
    body = np.zeros((n_snp, rlen), dtype=np.uint8)
    body[:, :nb] = packed
    with open(path, "wb") as fh:
        fh.write(hdr)
        fh.write(body.tobytes())


# --------------------------------------------------------------------------- datasets


@dataclass
class GenotypeDataset:
    inds: list[IndRecord]
    panel: SnpPanel
    geno: np.ndarray  # int8 (n_ind, n_snp), MISSING=-1

    @property
    def populations(self) -> np.ndarray:
        return np.array([r.population for r in self.inds], dtype=object)


def read_eigenstrat_dataset(
    prefix: str | Path,
    *,
    populations: list[str] | None = None,
    individuals: list[str] | None = None,
    snp_ids: list[str] | None = None,
    build: Build = "GRCh37",
) -> GenotypeDataset:
    """Read ``prefix.{geno,snp,ind}`` with optional population/individual/SNP subsetting."""
    prefix = str(prefix)
    inds = read_ind(prefix + ".ind")
    panel = read_eigenstrat_snp(prefix + ".snp", build=build)
    keep = np.ones(len(inds), dtype=bool)
    if populations is not None:
        keep &= np.isin([r.population for r in inds], populations)
    if individuals is not None:
        keep &= np.isin([r.id for r in inds], individuals)
    ind_idx = np.flatnonzero(keep)
    snp_idx = None
    if snp_ids is not None:
        pos_of = {s: i for i, s in enumerate(panel.rsid)}
        snp_idx = np.array([pos_of[s] for s in snp_ids if s in pos_of], dtype=np.int64)
    geno = read_geno(prefix + ".geno", len(inds), panel.n, ind_idx=ind_idx, snp_idx=snp_idx)
    sub_panel = panel if snp_idx is None else panel.subset(snp_idx)
    return GenotypeDataset(inds=[inds[i] for i in ind_idx], panel=sub_panel, geno=geno)


def write_eigenstrat_dataset(
    prefix: str | Path, ds: GenotypeDataset, *, fmt: GenoFormat = "packedancestrymap"
) -> None:
    prefix = str(prefix)
    write_ind(ds.inds, prefix + ".ind")
    write_eigenstrat_snp(ds.panel, prefix + ".snp")
    write_geno(
        prefix + ".geno",
        ds.geno,
        fmt=fmt,
        ind_ids=[r.id for r in ds.inds],
        snp_ids=[str(s) for s in ds.panel.rsid],
    )


def dosage_to_geno(dosage: np.ndarray) -> np.ndarray:
    """Float dosage (NaN missing) -> int8 genotype codes (MISSING=-1)."""
    d = np.asarray(dosage, dtype=np.float64)
    out = np.full(d.shape, MISSING, dtype=np.int8)
    ok = np.isfinite(d)
    out[ok] = np.clip(np.rint(d[ok]), 0, 2).astype(np.int8)
    return out


def geno_to_float(geno: np.ndarray) -> np.ndarray:
    g = geno.astype(np.float64)
    g[geno < 0] = np.nan
    return g


def merge_sample_into_reference(
    reference_prefix: str | Path,
    out_prefix: str | Path,
    *,
    sample_id: str,
    sample_population: str,
    dosage: np.ndarray,
    populations: list[str] | None = None,
    fmt: GenoFormat = "packedancestrymap",
    build: Build = "GRCh37",
) -> GenotypeDataset:
    """Write a reference subset plus one user sample (for qpAdm on genotypes).

    ``dosage`` must be aligned to the reference .snp order and count the .snp column-5 allele,
    i.e. the output of ``harmonize(raw, panel)`` with that reference's panel.
    """
    ds = read_eigenstrat_dataset(reference_prefix, populations=populations, build=build)
    if dosage.shape[0] != ds.panel.n:
        raise ValueError("dosage length must equal the number of reference SNPs")
    if any(r.id == sample_id for r in ds.inds):
        raise ValueError("sample_id collides with a reference individual id")
    merged = GenotypeDataset(
        inds=[*ds.inds, IndRecord(id=sample_id, sex="U", population=sample_population)],
        panel=ds.panel,
        geno=np.vstack([ds.geno, dosage_to_geno(dosage)[None, :]]),
    )
    write_eigenstrat_dataset(out_prefix, merged, fmt=fmt)
    return merged
