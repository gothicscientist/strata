"""Individual-level QC and population assembly.

Turns a parsed ``.anno`` file into the rows that go into
``populations.parquet`` / ``samples.parquet``, applying the exclusions that
make an f-statistic panel usable:

* low coverage — below ``QC.min_snps`` autosomal SNPs,
* AADR's own quality verdict — ``ASSESSMENT`` other than ``PASS``, or warnings
  naming ``QUESTIONABLE`` / ``FAIL`` (nuclear contamination),
* duplicates and relatives — AADR flags these in the ``Group ID`` itself, and
  individuals sharing a ``Master ID`` are the same person sequenced twice,
* withdrawn individuals — ``Ignore_`` labels.

Every exclusion is counted and reported rather than applied silently: the
reason an individual is absent from the panel is part of the panel's
provenance.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .anno import AnnoRecord
from .config import QC, QcThresholds

# AADR labels a group "_outlier" when its individuals are genuine analysis
# units that sit off their site's main cluster. Those are wanted. The markers
# in QcThresholds.reject_group_substrings are the ones that mean "do not use".
_KEEP_OUTLIER = re.compile(r"_outlier(\d*)$", re.IGNORECASE)


@dataclass
class ExclusionLog:
    """Why individuals were dropped, for the MANIFEST and the build log."""

    counts: Counter[str] = field(default_factory=Counter)
    examples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def add(self, reason: str, genetic_id: str) -> None:
        self.counts[reason] += 1
        if len(self.examples[reason]) < 5:
            self.examples[reason].append(genetic_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_excluded": int(sum(self.counts.values())),
            "by_reason": dict(sorted(self.counts.items())),
            "examples": {k: v for k, v in sorted(self.examples.items())},
        }


def slugify(value: str) -> str:
    """Stable, filesystem- and URL-safe population id from a group label."""
    norm = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    norm = re.sub(r"[^A-Za-z0-9]+", "-", norm).strip("-").lower()
    return norm or "unknown"


def group_is_usable(group_id: str, qc: QcThresholds = QC) -> tuple[bool, str | None]:
    """Whether a ``Group ID`` denotes an analysis group.

    Returns ``(usable, reason_if_not)``.
    """
    low = group_id.lower()
    if low.startswith("ignore") or "ignore_" in low:
        return False, "group_ignored"
    if _KEEP_OUTLIER.search(group_id):
        # Genuine analysis group; skip the "_outlier_" rejection substring.
        return True, None
    for marker in qc.reject_group_substrings:
        if marker == "ignore":
            continue
        if marker in low:
            return False, f"group_marker{marker}"
    return True, None


def assessment_is_ok(record: AnnoRecord, qc: QcThresholds = QC) -> tuple[bool, str | None]:
    """Whether AADR's own quality verdict permits using this individual."""
    text = record.assessment_text()
    if not text:
        # No verdict recorded. Present-day array data has none by design;
        # an ancient individual without one is not trusted.
        return (True, None) if record.is_present_day else (False, "assessment_missing")
    for bad in qc.reject_assessment_substrings:
        if bad in text:
            return False, f"assessment_{bad.lower()}"
    if not any(ok in text for ok in qc.allowed_assessments):
        return False, "assessment_not_pass"
    return True, None


@dataclass
class CuratedSample:
    """One individual that survived QC."""

    id: str
    population_id: str
    group_id: str
    master_id: str | None
    sex: str
    date_mean_bp: float | None
    date_sd: float | None
    lat: float | None
    lon: float | None
    country: str | None
    locality: str | None
    data_type: str | None
    n_snps: int | None
    pseudohaploid: bool
    publication_id: str | None
    assessment: str | None
    is_present_day: bool
    panel_block: str | None = None
    role: str | None = None


def _publication_slug(record: AnnoRecord) -> str | None:
    pub = record.publication
    if not pub:
        return None
    # AADR writes keys like "NarasimhanPatterson2019" or a comma-separated list.
    first = pub.split(",")[0].strip()
    return slugify(first) or None


def curate_samples(
    records: list[AnnoRecord],
    *,
    snpset: str,
    keep_groups: set[str] | None = None,
    roles: dict[str, str] | None = None,
    blocks: dict[str, str] | None = None,
    qc: QcThresholds = QC,
) -> tuple[list[CuratedSample], ExclusionLog]:
    """Apply QC to parsed ``.anno`` records.

    Args:
        records: Parsed annotation rows.
        snpset: ``"1240K"`` or ``"HO"`` — selects which SNP-count column the
            coverage filter reads, because the two panels differ by ~2x.
        keep_groups: Restrict to these ``Group ID``s (the resolved panel). None
            keeps every group that passes the other filters.
        roles: ``group_id -> role`` from :func:`panel.resolve`.
        blocks: ``group_id -> panel block name``.
        qc: Thresholds.

    Returns:
        ``(samples, exclusions)``. Order is stable: by group, then by
        descending SNP count, so the retained duplicate is deterministic.
    """
    log = ExclusionLog()
    kept: list[CuratedSample] = []

    for rec in records:
        if keep_groups is not None and rec.group_id not in keep_groups:
            log.add("not_in_panel", rec.genetic_id)
            continue

        usable, reason = group_is_usable(rec.group_id, qc)
        if not usable:
            log.add(reason or "group_rejected", rec.genetic_id)
            continue

        ok, reason = assessment_is_ok(rec, qc)
        if not ok:
            log.add(reason or "assessment_rejected", rec.genetic_id)
            continue

        n_snps = rec.n_snps(snpset)
        threshold = qc.min_snps_modern if rec.is_present_day else qc.min_snps
        if n_snps is None:
            if not rec.is_present_day:
                log.add("snp_count_missing", rec.genetic_id)
                continue
        elif n_snps < threshold:
            log.add("low_coverage", rec.genetic_id)
            continue

        kept.append(
            CuratedSample(
                id=rec.genetic_id,
                population_id=slugify(rec.group_id),
                group_id=rec.group_id,
                master_id=rec.master_id,
                sex=rec.molecular_sex,
                date_mean_bp=rec.date_mean_bp,
                date_sd=rec.date_sd_bp,
                lat=rec.lat,
                lon=rec.lon,
                country=rec.political_entity,
                locality=rec.locality,
                data_type=rec.data_source,
                n_snps=n_snps,
                pseudohaploid=not rec.is_present_day,
                publication_id=_publication_slug(rec),
                assessment=rec.assessment,
                is_present_day=rec.is_present_day,
                panel_block=(blocks or {}).get(rec.group_id),
                role=(roles or {}).get(rec.group_id),
            )
        )

    if qc.deduplicate_on_master_id:
        kept = _deduplicate(kept, log)

    kept.sort(key=lambda s: (s.group_id, -(s.n_snps or 0), s.id))
    return kept, log


def _deduplicate(samples: list[CuratedSample], log: ExclusionLog) -> list[CuratedSample]:
    """Keep the highest-coverage individual per Master ID.

    Two rows with the same Master ID are the same person, usually the same
    individual sequenced in two publications. Keeping both would make an f2
    block treat one genome as two independent observations and understate the
    standard errors.
    """
    by_master: dict[str, list[CuratedSample]] = defaultdict(list)
    singletons: list[CuratedSample] = []
    for s in samples:
        if s.master_id:
            by_master[s.master_id].append(s)
        else:
            singletons.append(s)

    out = list(singletons)
    for master, group in by_master.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        group.sort(key=lambda s: (-(s.n_snps or 0), s.id))
        out.append(group[0])
        for dropped in group[1:]:
            log.add("duplicate_master_id", dropped.id)
        del master
    return out


@dataclass
class CuratedPopulation:
    """One population aggregated from its curated samples."""

    id: str
    group_id: str
    name: str
    region: str | None
    country: str | None
    lat: float | None
    lon: float | None
    period: str | None
    culture: str | None
    date_mean_bp: float | None
    date_sd: float | None
    date_min_bp: float | None
    date_max_bp: float | None
    n_samples: int
    data_source: str
    publication_ids: list[str]
    spaces: list[str]
    role: str | None = None
    panel_block: str | None = None


def _mean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def infer_period(date_mean_bp: float | None, is_present_day: bool) -> str:
    """Coarse period label from the mean date, for faceted search.

    Boundaries are conventional calendar-era boundaries converted to years
    before 1950 CE. They are a browsing aid, not an archaeological claim.
    """
    if is_present_day or date_mean_bp is None or date_mean_bp <= 0:
        return "Modern"
    bp = date_mean_bp
    if bp < 500:
        return "Early Modern"
    if bp < 1500:
        return "Medieval"
    if bp < 2500:
        return "Iron Age"
    if bp < 4200:
        return "Bronze Age"
    if bp < 6000:
        return "Chalcolithic"
    if bp < 10000:
        return "Neolithic"
    if bp < 12000:
        return "Mesolithic"
    return "Upper Palaeolithic"


_REGION_BY_BLOCK = {
    "ancient_south_asia": "South Asia",
    "modern_south_asia": "South Asia",
    "ancient_iran_anatolia": "West Asia",
    "ancient_steppe_siberia": "Steppe/Siberia",
    "ancient_central_asia": "Central Asia",
    "modern_global": "Global",
    "right": "Outgroup",
}


def _culture_from_group(group_id: str) -> str | None:
    """Pull an archaeological culture out of an AADR label when it has one.

    AADR labels read ``Country_Site_Period`` or ``Country_Culture_Period``;
    the middle token is the site or culture. Returns None for one-token labels
    such as present-day group names.
    """
    parts = [p for p in group_id.replace(".", "_").split("_") if p]
    if len(parts) < 3:
        return None
    return parts[1].replace("-", " ") or None


def build_populations(
    samples: list[CuratedSample],
    *,
    data_source: str,
    spaces: list[str] | None = None,
    qc: QcThresholds = QC,
) -> tuple[list[CuratedPopulation], ExclusionLog]:
    """Aggregate curated samples into populations.

    Populations below ``qc.min_population_size`` are dropped and logged.
    """
    log = ExclusionLog()
    by_group: dict[str, list[CuratedSample]] = defaultdict(list)
    for s in samples:
        by_group[s.group_id].append(s)

    out: list[CuratedPopulation] = []
    for group_id, members in sorted(by_group.items()):
        if len(members) < qc.min_population_size:
            for m in members:
                log.add("population_too_small", m.id)
            continue
        dates = [m.date_mean_bp for m in members if m.date_mean_bp is not None]
        sds = [m.date_sd for m in members if m.date_sd is not None]
        present_day = all(m.is_present_day for m in members)
        block = next((m.panel_block for m in members if m.panel_block), None)
        pubs = sorted({m.publication_id for m in members if m.publication_id})
        out.append(
            CuratedPopulation(
                id=slugify(group_id),
                group_id=group_id,
                name=group_id.replace("_", " "),
                region=_REGION_BY_BLOCK.get(block or "", None),
                country=next((m.country for m in members if m.country), None),
                lat=_mean([m.lat for m in members]),  # type: ignore[list-item]
                lon=_mean([m.lon for m in members]),  # type: ignore[list-item]
                period=infer_period(_mean(dates), present_day),
                culture=_culture_from_group(group_id),
                date_mean_bp=_mean(dates),
                date_sd=_mean(sds),
                date_min_bp=min(dates) if dates else None,
                date_max_bp=max(dates) if dates else None,
                n_samples=len(members),
                data_source=data_source,
                publication_ids=pubs,
                spaces=list(spaces or []),
                role=next((m.role for m in members if m.role), None),
                panel_block=block,
            )
        )
    return out, log


def f2_eligible(
    populations: list[CuratedPopulation], qc: QcThresholds = QC
) -> list[CuratedPopulation]:
    """Populations large enough to be used as an f-statistic unit."""
    return [p for p in populations if p.n_samples >= qc.min_population_size_for_f2]
