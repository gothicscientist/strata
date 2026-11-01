"""Add the 1000 Genomes Project's South Asian panels as a second reference source.

Why a second source at all: the public AADR carries only what its sample
consents allow to be redistributed, and the present-day South Asian groups it
does carry have one or two individuals each — enough for a population mean on
the PCA, thin for anything needing within-population variation. The 1000
Genomes Project publishes five South Asian panels of roughly a hundred samples
each with no access restriction, three of which are labels
:data:`pipeline.panel.UNAVAILABLE_IN_PUBLIC_AADR` records as
``in_1000_genomes`` for exactly this reason.

What this does *not* fix: there is no Andamanese-related population here
either, so the ``no_aasi_proxy`` limit stands. What it changes is the
exploratory side — PCA placement, distances and admixture fitting against
groups with real sample counts.

Scientific care taken here, since every one of these is a way to get plausible
numbers that are wrong:

* **Sites come from the reference panel, not from the VCF.** The output is
  aligned to the committed `snp_panel.parquet` (the same SNP set and order the
  PCA space and user harmonisation use), so a 1000 Genomes individual and an
  AADR individual are described by the same columns.
* **Alleles are oriented, never assumed.** A site is kept only when the VCF's
  REF/ALT pair is the panel's pair, in either order, or its strand complement
  where that is unambiguous. A strand-ambiguous site (A/T or C/G) whose alleles
  do not match directly is dropped rather than guessed, because guessing
  silently inverts the genotype.
* **Build matters.** Phase 3 is GRCh37, which is the panel's build. The
  function refuses a panel on another build rather than matching positions
  across assemblies.
* **Nothing is imputed.** Phase 3 genotypes are imputed by the project itself,
  which is recorded in the provenance; a missing call stays missing here.

The extraction streams each chromosome's VCF and keeps only panel positions,
so it never holds a whole chromosome in memory and caches per chromosome,
making a long run resumable.
"""

from __future__ import annotations

import gzip
import http.client
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

RELEASE = "20130502"  # phase 3, GRCh37
BUILD = "GRCh37"
BASE = f"https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/{RELEASE}"
PANEL_URL = f"{BASE}/integrated_call_samples_v3.20130502.ALL.panel"
VCF_TEMPLATE = (
    BASE + "/ALL.chr{chrom}.phase3_shapeit2_mvncall_integrated_v5b.{release}.genotypes.vcf.gz"
)
# chrX is phased and named differently, and f-statistics here are autosome-only.
AUTOSOMES: tuple[str, ...] = tuple(str(c) for c in range(1, 23))

CITATION = (
    "The 1000 Genomes Project Consortium (2015). A global reference for human "
    "genetic variation. Nature, 526(7571), 68-74. "
    "https://doi.org/10.1038/nature15393"
)
PUBLICATION_ID = "1000g-phase3-2015"
DATA_SOURCE = "1000G-phase3"

# The project's own population codes, with the Strata group ID each becomes.
#
# The group IDs are chosen so the panel's existing prefix labels resolve them:
# `panel.py` already asks for "Bengali*", "Tamil*", "Telugu*", "Gujarati*" and
# "Punjabi*". The `_1000G` suffix keeps them distinguishable from an AADR group
# of the same name, which matters because the two have different coverage and
# different provenance and must never be silently pooled.
#
# Coordinates are the sampling locality the project records, not a genetic
# centroid. Punjabi (PJL) were sampled in Lahore, Pakistan; Gujarati (GIH) and
# Indian Telugu (ITU) are diaspora cohorts (Houston, USA and the UK), recorded
# with their ancestral region and marked in `locality`.
@dataclass(frozen=True)
class OneKgPopulation:
    code: str
    group_id: str
    name: str
    country: str
    region: str = "South Asia"
    lat: float | None = None
    lon: float | None = None
    locality: str = ""


SAS_POPULATIONS: tuple[OneKgPopulation, ...] = (
    OneKgPopulation(
        "GIH",
        "Gujarati_1000G",
        "Gujarati Indian (1000 Genomes)",
        "India",
        lat=22.3,
        lon=71.2,
        locality="sampled in Houston, USA; ancestral region Gujarat, India",
    ),
    OneKgPopulation(
        "PJL",
        "Punjabi_1000G",
        "Punjabi (1000 Genomes)",
        "Pakistan",
        lat=31.5,
        lon=74.3,
        locality="sampled in Lahore, Pakistan",
    ),
    OneKgPopulation(
        "BEB",
        "Bengali_1000G",
        "Bengali (1000 Genomes)",
        "Bangladesh",
        lat=23.8,
        lon=90.4,
        locality="sampled in Dhaka, Bangladesh",
    ),
    OneKgPopulation(
        "STU",
        "Tamil_SriLanka_1000G",
        "Sri Lankan Tamil (1000 Genomes)",
        "Sri Lanka",
        lat=9.7,
        lon=80.0,
        locality="sampled in the UK; ancestral region northern Sri Lanka",
    ),
    OneKgPopulation(
        "ITU",
        "Telugu_1000G",
        "Indian Telugu (1000 Genomes)",
        "India",
        lat=16.5,
        lon=79.9,
        locality="sampled in the UK; ancestral region Andhra Pradesh, India",
    ),
)

POPULATION_BY_CODE: dict[str, OneKgPopulation] = {p.code: p for p in SAS_POPULATIONS}

_COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}
# Pairs that are their own complement: strand cannot be resolved from alleles.
_AMBIGUOUS = ({"A", "T"}, {"C", "G"})

MISSING = np.int8(-1)


class OneKgError(RuntimeError):
    """A fetch or extraction that cannot be completed, with a message for a human."""


# --------------------------------------------------------------------------- samples


def parse_sample_panel(text: str, *, codes: Iterable[str] | None = None) -> dict[str, str]:
    """Map sample ID -> population code, for the populations asked for.

    Args:
        text: The release's ``.panel`` file: whitespace-separated
            ``sample pop super_pop gender``, with a header row.
        codes: Population codes to keep. Defaults to the South Asian panels.

    Returns:
        ``{sample_id: population_code}``, in file order.

    Raises:
        OneKgError: If the file has no usable rows, which would otherwise
            yield an empty dataset that looks like a successful run.
    """
    wanted = set(codes if codes is not None else POPULATION_BY_CODE)
    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] == "sample":
            continue
        sample, pop = parts[0], parts[1]
        if pop in wanted:
            out[sample] = pop
    if not out:
        raise OneKgError(
            f"no samples for {sorted(wanted)} in the 1000 Genomes panel file; "
            "the release layout may have changed"
        )
    return out


# --------------------------------------------------------------------------- alleles


def orientation_detail(ref: str, alt: str, a1: str, a2: str) -> tuple[int | None, bool]:
    """:func:`orientation`, and whether reaching it needed a strand flip.

    Separate because the flip count is a diagnostic worth reporting — a run
    with an unexpected share of flipped sites means the panel and the callset
    disagree about strand, which is worth seeing before the numbers are used —
    and deriving it from the same comparison keeps the count honest.
    """
    ref, alt, a1, a2 = ref.upper(), alt.upper(), a1.upper(), a2.upper()
    if len({ref, alt, a1, a2} - set(_COMPLEMENT)) > 0:
        return None, False  # indel, symbolic allele, or a panel row that is not a SNP
    if ref == alt or a1 == a2:
        return None, False
    if (ref, alt) == (a2, a1):
        return 1, False
    if (ref, alt) == (a1, a2):
        return -1, False
    if {a1, a2} in _AMBIGUOUS:
        return None, False
    flip_ref, flip_alt = _COMPLEMENT[ref], _COMPLEMENT[alt]
    if (flip_ref, flip_alt) == (a2, a1):
        return 1, True
    if (flip_ref, flip_alt) == (a1, a2):
        return -1, True
    return None, False


def orientation(ref: str, alt: str, a1: str, a2: str) -> int | None:
    """How a VCF site's alleles line up with the panel's.

    Args:
        ref, alt: The VCF's reference and alternate allele.
        a1, a2: The panel's counted allele and its other allele. EIGENSTRAT
            genotypes count copies of ``a1``.

    Returns:
        ``1`` when the ALT dosage already counts ``a1``; ``-1`` when the ALT
        dosage counts ``a2``, so copies of ``a1`` are ``2 - dosage``; ``None``
        when the site cannot be used.

    A strand flip is accepted only where the allele pair is not its own
    complement. For an A/T or C/G site a flip is indistinguishable from an
    allele swap, and choosing wrong inverts every genotype at that site, so
    such a site is dropped unless it matches without flipping.
    """
    return orientation_detail(ref, alt, a1, a2)[0]


# --------------------------------------------------------------------------- extraction


@dataclass
class ChromExtract:
    """Genotypes for one chromosome, aligned to the reference panel."""

    chrom: str
    snp_idx: np.ndarray  # positions in the reference panel, ascending
    geno: np.ndarray  # int8 (n_sample, n_snp_kept), MISSING = -1
    stats: dict[str, int] = field(default_factory=dict)


def _targets(panel: Any, chrom: str) -> tuple[dict[int, int], np.ndarray, np.ndarray]:
    """Panel rows on this chromosome: position -> row index, plus the allele pair."""
    on_chrom = np.flatnonzero(np.asarray(panel.chrom, dtype=object) == chrom)
    pos = np.asarray(panel.pos, dtype=np.int64)[on_chrom]
    # A position carrying two panel rows cannot be matched unambiguously by
    # position, so neither row is offered as a target.
    seen: dict[int, int] = {}
    duplicated: set[int] = set()
    for row, p in zip(on_chrom, pos, strict=True):
        p = int(p)
        if p in seen:
            duplicated.add(p)
        seen[p] = int(row)
    for p in duplicated:
        seen.pop(p, None)
    return seen, np.asarray(panel.ref, dtype=object), np.asarray(panel.alt, dtype=object)


def _genotype_dosage(field_value: str) -> int:
    """ALT dosage from a VCF genotype field, or -1 when any allele is missing."""
    gt = field_value.split(":", 1)[0]
    a, sep, b = gt.partition("|") if "|" in gt else gt.partition("/")
    if not sep:  # haploid call
        return -1 if a in (".", "") else (1 if a != "0" else 0)
    if a in (".", "") or b in (".", ""):
        return -1
    return (0 if a == "0" else 1) + (0 if b == "0" else 1)


def extract_chromosome(
    lines: Iterable[bytes],
    *,
    panel: Any,
    chrom: str,
    samples: dict[str, str],
) -> ChromExtract:
    """Pull the panel's sites for `samples` out of one chromosome's VCF stream.

    `lines` is the decompressed VCF, byte lines. Only sites at a panel
    position, biallelic, and allele-compatible with the panel are kept; the
    rest are counted in ``stats`` so a run can be judged rather than trusted.
    """
    if getattr(panel, "build", BUILD) != BUILD:
        raise OneKgError(
            f"1000 Genomes phase 3 is {BUILD}; the reference panel is "
            f"{panel.build}. Positions must not be matched across builds."
        )
    targets, panel_ref, panel_alt = _targets(panel, chrom)
    stats = {
        "sites_seen": 0,
        "at_panel_position": 0,
        "not_biallelic": 0,
        "allele_mismatch": 0,
        "kept": 0,
        "strand_flipped": 0,
    }
    order: list[int] = []
    columns: list[np.ndarray] = []
    sample_cols: list[int] | None = None
    ids: list[str] = []

    for raw in lines:
        if raw.startswith(b"##"):
            continue
        if raw.startswith(b"#CHROM"):
            header = raw.decode().rstrip("\n").split("\t")
            ids = [s for s in header[9:] if s in samples]
            index_of = {s: i for i, s in enumerate(header)}
            sample_cols = [index_of[s] for s in ids]
            missing = sorted(set(samples) - set(ids))
            if missing:
                log.warning("chr%s: %d requested samples absent", chrom, len(missing))
            continue
        if sample_cols is None:
            raise OneKgError(f"chr{chrom}: data line before the #CHROM header")
        stats["sites_seen"] += 1
        # Parse the position before anything else: almost every line is
        # discarded, and splitting a 2,504-sample line to decide that is the
        # difference between minutes and hours.
        first = raw.find(b"\t")
        second = raw.find(b"\t", first + 1)
        if second < 0:
            continue
        try:
            pos = int(raw[first + 1 : second])
        except ValueError:
            continue
        row = targets.get(pos)
        if row is None:
            continue
        stats["at_panel_position"] += 1
        parts = raw.decode().rstrip("\n").split("\t")
        ref, alt = parts[3], parts[4]
        if "," in alt:
            stats["not_biallelic"] += 1
            continue
        sign, flipped = orientation_detail(ref, alt, str(panel_ref[row]), str(panel_alt[row]))
        if sign is None:
            stats["allele_mismatch"] += 1
            continue
        if flipped:
            stats["strand_flipped"] += 1
        dose = np.fromiter(
            (_genotype_dosage(parts[c]) for c in sample_cols),
            dtype=np.int8,
            count=len(sample_cols),
        )
        counted = dose if sign == 1 else np.where(dose < 0, MISSING, 2 - dose).astype(np.int8)
        order.append(row)
        columns.append(counted)
        stats["kept"] += 1

    if not columns:
        return ChromExtract(
            chrom=chrom,
            snp_idx=np.zeros(0, dtype=np.int64),
            geno=np.zeros((len(ids), 0), dtype=np.int8),
            stats=stats,
        )
    snp_idx = np.asarray(order, dtype=np.int64)
    geno = np.stack(columns, axis=1)  # (n_sample, n_kept)
    # VCFs are position-sorted, so this is already ascending; sort rather than
    # assume, because the panel's row order is what downstream code indexes by.
    if not np.all(np.diff(snp_idx) > 0):
        keep = np.argsort(snp_idx, kind="stable")
        snp_idx, geno = snp_idx[keep], geno[:, keep]
    return ChromExtract(chrom=chrom, snp_idx=snp_idx, geno=geno, stats=stats)


# --------------------------------------------------------------------------- fetching


def vcf_url(chrom: str) -> str:
    return VCF_TEMPLATE.format(chrom=chrom, release=RELEASE)


def _open_stream(url: str, *, timeout: float = 120.0) -> Iterator[bytes]:
    try:
        response = urllib.request.urlopen(url, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise OneKgError(f"{url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise OneKgError(f"{url} is unreachable: {exc.reason}") from exc
    with response, gzip.GzipFile(fileobj=response) as gz:
        yield from gz


def fetch_sample_panel(*, cache: Path | None = None) -> dict[str, str]:
    """The release's sample-to-population table, cached on disk if asked."""
    if cache is not None and cache.is_file():
        return parse_sample_panel(cache.read_text(encoding="utf-8"))
    try:
        with urllib.request.urlopen(PANEL_URL, timeout=60) as response:
            text = response.read().decode()
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise OneKgError(f"{PANEL_URL} could not be read: {exc}") from exc
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    return parse_sample_panel(text)


def fetch_chromosome(
    chrom: str,
    *,
    panel: Any,
    samples: dict[str, str],
    cache_dir: Path | None = None,
    force: bool = False,
    attempts: int = 4,
) -> ChromExtract:
    """Extract one chromosome, reusing a cached extract when there is one.

    The cache is what makes a 22-chromosome run resumable: each chromosome is
    hours of streaming, and a run that dies on chr14 must not start over.

    A chromosome is also retried in place. Each one is a single ~1 GB gzip
    stream read to the end, so a reset at 90% loses the whole chromosome, and
    over 22 of them a transport that resets occasionally will reset at least
    once. There is no resuming mid-stream: the retry restarts the chromosome,
    which is correct precisely because a partial extract is discarded rather
    than cached. A refusal from the server (`OneKgError`) is not retried, since
    a wrong URL or a withdrawn release does not improve with waiting.
    """
    cache = None if cache_dir is None else cache_dir / f"chr{chrom}.npz"
    if cache is not None and cache.is_file() and not force:
        with np.load(cache, allow_pickle=False) as z:
            log.info("chr%s: reusing %s", chrom, cache)
            return ChromExtract(
                chrom=chrom,
                snp_idx=z["snp_idx"],
                geno=z["geno"],
                stats={"cached": 1, "kept": int(z["snp_idx"].shape[0])},
            )
    for attempt in range(1, max(1, attempts) + 1):
        try:
            extract = extract_chromosome(
                _open_stream(vcf_url(chrom)), panel=panel, chrom=chrom, samples=samples
            )
            break
        except (OSError, http.client.HTTPException) as exc:
            # ConnectionResetError, IncompleteRead, a read timeout: the transport
            # failed part-way, not the data. OneKgError is deliberately not caught.
            if attempt == max(1, attempts):
                raise OneKgError(
                    f"chr{chrom}: the stream failed {attempt} times; last error: {exc}"
                ) from exc
            delay = 5 * 2 ** (attempt - 1)
            log.warning(
                "chr%s: stream failed (%s); retrying in %ds (attempt %d of %d)",
                chrom,
                exc,
                delay,
                attempt + 1,
                max(1, attempts),
            )
            time.sleep(delay)
    log.info(
        "chr%s: kept %d of %d panel positions for %d samples",
        chrom,
        extract.stats["kept"],
        extract.stats.get("at_panel_position", 0),
        extract.geno.shape[0],
    )
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, snp_idx=extract.snp_idx, geno=extract.geno)
    return extract


# --------------------------------------------------------------------------- assembly


@dataclass
class OneKgBuild:
    prefix: Path
    sample_ids: list[str]
    populations: dict[str, int]  # group_id -> n samples
    n_snps_panel: int
    n_snps_called: int
    per_chromosome: dict[str, dict[str, int]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": DATA_SOURCE,
            "release": RELEASE,
            "build": BUILD,
            "prefix": str(self.prefix),
            "n_samples": len(self.sample_ids),
            "populations": self.populations,
            "n_snps_panel": self.n_snps_panel,
            "n_snps_called": self.n_snps_called,
            "call_rate_snps": (
                round(self.n_snps_called / self.n_snps_panel, 6) if self.n_snps_panel else 0.0
            ),
            "publication": {"id": PUBLICATION_ID, "citation": CITATION},
            "per_chromosome": self.per_chromosome,
        }


def assemble(
    extracts: list[ChromExtract],
    *,
    panel: Any,
    sample_ids: list[str],
    samples: dict[str, str],
) -> tuple[np.ndarray, np.ndarray]:
    """Merge per-chromosome extracts into one matrix on the panel's full SNP set.

    Returns ``(geno, snp_idx)`` where ``geno`` is int8 ``(n_sample, n_kept)``
    and ``snp_idx`` indexes the reference panel. Panel sites no chromosome
    supplied are left out entirely rather than filled with missing calls: a
    column of missing data costs space and tells a reader nothing, and the
    panel subset records exactly which sites are present.
    """
    if not extracts:
        raise OneKgError("no chromosome extracts to assemble")
    widths = {e.geno.shape[0] for e in extracts if e.geno.size}
    if len(widths) > 1:
        raise OneKgError(f"chromosome extracts disagree on sample count: {sorted(widths)}")
    snp_idx = np.concatenate([e.snp_idx for e in extracts])
    geno = np.concatenate([e.geno for e in extracts], axis=1)
    order = np.argsort(snp_idx, kind="stable")
    snp_idx, geno = snp_idx[order], geno[:, order]
    if np.any(np.diff(snp_idx) == 0):
        raise OneKgError("the same panel row was supplied by more than one chromosome")
    if geno.shape[0] != len(sample_ids):
        raise OneKgError(
            f"{geno.shape[0]} genotype rows for {len(sample_ids)} samples"
        )
    unknown = sorted(set(sample_ids) - set(samples))
    if unknown:
        raise OneKgError(f"samples with no population: {unknown[:5]}")
    return geno, snp_idx


def ind_records(sample_ids: list[str], samples: dict[str, str]) -> list[Any]:
    """EIGENSTRAT ``.ind`` rows, population = the Strata group ID."""
    from strata.io.types import IndRecord

    return [
        IndRecord(id=s, sex="U", population=POPULATION_BY_CODE[samples[s]].group_id)
        for s in sample_ids
    ]


def panel_dosage(geno: np.ndarray, snp_idx: np.ndarray, n_panel: int) -> np.ndarray:
    """Scatter extracted columns onto the panel's full SNP set.

    The PCA model is defined over every panel SNP in panel order, so
    projection needs a row per sample over all of them, with the sites this
    source did not supply left missing rather than zero — a zero is a genotype.
    """
    out = np.full((geno.shape[0], n_panel), MISSING, dtype=np.int8)
    out[:, snp_idx] = geno
    return out


def write_dataset(
    prefix: Path,
    *,
    panel: Any,
    geno: np.ndarray,
    snp_idx: np.ndarray,
    sample_ids: list[str],
    samples: dict[str, str],
) -> Path:
    """Write ``prefix.{geno,snp,ind}`` for the sites this source supplied.

    The `.snp` carries the reference panel's own rows, subset to those sites,
    so the output is on the same SNP set — and the same allele orientation —
    as everything else in the reference library.
    """
    from strata.io import write_eigenstrat_dataset
    from strata.io.eigenstrat import GenotypeDataset

    prefix.parent.mkdir(parents=True, exist_ok=True)
    ds = GenotypeDataset(
        inds=ind_records(sample_ids, samples),
        panel=panel.subset(snp_idx),
        geno=geno,
    )
    write_eigenstrat_dataset(prefix, ds)
    return prefix
