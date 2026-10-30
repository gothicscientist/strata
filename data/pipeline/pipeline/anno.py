"""Robust parser for AADR ``.anno`` annotation files.

The ``.anno`` header is not a schema: it is prose. Column names carry trailing
spaces, parenthetical explanations, and the method description for the whole
column, and they are reworded between releases. For example the SNP-count
columns in v54-v66 read:

    SNPs hit on autosomal targets (Computed using easystats on 1240k snpset)
    SNPs hit on autosomal targets (Computed using easystats on HO snpset)

so matching on a prefix collides, and matching on the full string breaks on the
next release. This module normalises each header and resolves it against an
ordered rule table: exact normalised aliases first, then regexes that key on
the few tokens that actually carry the meaning (``1240k`` vs ``ho``,
``coverage`` vs ``snps``).

Unrecognised columns are preserved under their normalised name rather than
dropped, so a new release's additions remain reachable without a code change.

Nothing here reads genotypes. The ``.anno`` file is metadata only.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Values AADR uses for "no data", in addition to the empty string.
MISSING_TOKENS = frozenset(
    {
        "",
        "..",
        "...",
        ".",
        "n/a",
        "na",
        "nan",
        "none",
        "null",
        "missing",
        "unknown",
        "not applicable",
        "not available",
        "no data",
        "-",
    }
)

# Date mean in BP for a present-day individual. AADR writes 0.
PRESENT_DAY_BP = 0.0


def normalise_header(raw: str) -> str:
    """Normalise a header cell to a lowercase underscore token.

    ``"1240k coverage (taken from original pulldown where possible) "`` becomes
    ``"1240k_coverage_taken_from_original_pulldown_where_possible"``.
    """
    s = raw.replace("﻿", "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


@dataclass(frozen=True)
class ColumnRule:
    """One canonical field and how to recognise its header."""

    canonical: str
    aliases: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    # Rules with a lower order win when two could match the same header.
    required: bool = False

    def matches(self, normalised: str) -> bool:
        if normalised in self.aliases:
            return True
        return any(re.search(p, normalised) for p in self.patterns)


# Order matters: the first matching rule claims the column. The narrow
# 1240k/HO/mtDNA rules therefore precede the generic ones.
COLUMN_RULES: tuple[ColumnRule, ...] = (
    ColumnRule(
        "genetic_id",
        aliases=("genetic_id", "instance_id", "index", "id"),
        patterns=(r"^genetic_id", r"^instance_id"),
        required=True,
    ),
    ColumnRule(
        "master_id",
        aliases=("master_id", "individual_id"),
        patterns=(r"^master_id",),
    ),
    ColumnRule(
        "group_id",
        aliases=("group_id", "group_label", "population_id", "population"),
        patterns=(r"^group_id", r"^group_label"),
        required=True,
    ),
    ColumnRule("skeletal_code", aliases=("skeletal_code",), patterns=(r"^skeletal_code",)),
    ColumnRule("skeletal_element", aliases=("skeletal_element",)),
    ColumnRule(
        "year_first_publication",
        patterns=(r"^year_(data_)?(from_this_individual_was_)?first_publi", r"^year_first_publi"),
    ),
    ColumnRule("publication", aliases=("publication", "publication_abbreviation")),
    ColumnRule("date_method", patterns=(r"^method_for_determining_date", r"^date_method")),
    # "Date mean in BP in years before 1950 CE [...]"
    ColumnRule(
        "date_mean_bp",
        aliases=("date_mean_bp",),
        patterns=(r"^date_mean_in_bp", r"date_mean.*_bp", r"^mean_bp"),
    ),
    ColumnRule(
        "date_sd_bp",
        aliases=("date_sd", "date_sd_bp"),
        patterns=(r"^date_standard_deviation_in_bp", r"^date_sd"),
    ),
    ColumnRule(
        "date_full_info",
        aliases=("date_full_info",),
        patterns=(r"^full_date", r"^date_full"),
    ),
    ColumnRule("age_death", patterns=(r"^age_at_death",)),
    ColumnRule("locality", aliases=("locality", "location")),
    ColumnRule(
        "political_entity",
        aliases=("political_entity", "country"),
        patterns=(r"^political_entity",),
    ),
    ColumnRule("lat", aliases=("lat", "lat_", "latitude")),
    ColumnRule("lon", aliases=("long", "long_", "lon", "longitude")),
    ColumnRule("pulldown_strategy", patterns=(r"^pulldown_strategy",)),
    ColumnRule("data_source", aliases=("data_source", "data_type"), patterns=(r"^data_source",)),
    ColumnRule("n_libraries", aliases=("no_libraries", "n_libraries"), patterns=(r"^no_librar",)),
    # Narrow coverage/SNP rules before any generic "coverage"/"snps" rule.
    ColumnRule("coverage_1240k", patterns=(r"1240k.*coverage", r"coverage.*1240k")),
    ColumnRule("coverage_mtdna", patterns=(r"mtdna.*coverage", r"coverage.*mtdna")),
    ColumnRule(
        "n_snps_1240k",
        patterns=(r"snps.*(hit|autosomal|targets).*1240k", r"1240k.*snps_hit", r"^snps_1240k"),
    ),
    ColumnRule(
        "n_snps_ho",
        patterns=(r"snps.*(hit|autosomal|targets).*_ho(_|$)", r"^snps_ho", r"_ho_snpset"),
    ),
    ColumnRule("molecular_sex", aliases=("molecular_sex", "sex"), patterns=(r"^molecular_sex",)),
    ColumnRule(
        "family_id",
        aliases=("family_id",),
        patterns=(r"^family_id", r"kinship"),
    ),
    ColumnRule(
        "y_haplogroup",
        patterns=(r"^y_haplogroup.*terminal", r"^y_haplogroup$", r"^y_hap"),
    ),
    ColumnRule("y_haplogroup_isogg", patterns=(r"y_haplogroup.*isogg",)),
    ColumnRule(
        "mtdna_haplogroup",
        patterns=(r"^mtdna_haplogroup", r"^mt_haplogroup"),
    ),
    ColumnRule("mtdna_match_consensus", patterns=(r"mtdna_match",)),
    ColumnRule("damage", aliases=("damage",), patterns=(r"^damage_rate",)),
    ColumnRule("sex_ratio", patterns=(r"^sex_ratio",)),
    ColumnRule("library_type", patterns=(r"^library_type",)),
    ColumnRule("libraries", aliases=("libraries", "library_names")),
    # ASSESSMENT must not swallow ASSESSMENT WARNINGS, so warnings come first.
    ColumnRule(
        "assessment_warnings",
        patterns=(r"^assessment_warning",),
    ),
    ColumnRule("assessment", aliases=("assessment",), patterns=(r"^assessment$",)),
    ColumnRule("xcontam", patterns=(r"^xcontam", r"x_contamination")),
)

REQUIRED_FIELDS: tuple[str, ...] = tuple(r.canonical for r in COLUMN_RULES if r.required)


class AnnoFormatError(ValueError):
    """The ``.anno`` file does not look like an AADR annotation file."""


def map_header(header: Iterable[str]) -> tuple[dict[int, str], dict[str, str]]:
    """Resolve raw header cells to canonical field names.

    Args:
        header: The raw header cells, in file order.

    Returns:
        ``(index_to_field, unmapped)`` where ``index_to_field`` maps column
        index to a canonical name (or to the normalised header for columns no
        rule claimed), and ``unmapped`` maps normalised header to the raw cell
        for those unclaimed columns.

    Raises:
        AnnoFormatError: A required field is missing, or two columns claim the
            same canonical field.
    """
    index_to_field: dict[int, str] = {}
    unmapped: dict[str, str] = {}
    claimed: dict[str, int] = {}

    for idx, raw in enumerate(header):
        norm = normalise_header(raw)
        if not norm:
            continue
        field_name: str | None = None
        for rule in COLUMN_RULES:
            if rule.canonical in claimed:
                continue  # already taken by an earlier column
            if rule.matches(norm):
                field_name = rule.canonical
                break
        if field_name is None:
            # Keep it reachable under its normalised name.
            if norm not in index_to_field.values():
                index_to_field[idx] = norm
                unmapped[norm] = raw.strip()
            continue
        claimed[field_name] = idx
        index_to_field[idx] = field_name

    missing = [f for f in REQUIRED_FIELDS if f not in claimed]
    if missing:
        raise AnnoFormatError(
            "AADR .anno header is missing required column(s): "
            + ", ".join(missing)
            + f". Header had {len(index_to_field)} recognised columns."
        )
    return index_to_field, unmapped


def clean(value: str | None) -> str | None:
    """Strip a cell and map AADR's missing-data tokens to None."""
    if value is None:
        return None
    s = value.strip().strip('"').strip()
    if s.lower() in MISSING_TOKENS:
        return None
    return s


def to_float(value: str | None) -> float | None:
    """Parse a numeric cell, tolerating thousands separators and stray signs.

    AADR numeric columns can contain ``"1,234"``, ``">100"``, ``"0.0123"`` or
    a free-text note. Anything that is not a number becomes None rather than
    raising, because one malformed cell must not abort a 20k-row parse.
    """
    s = clean(value)
    if s is None:
        return None
    s = s.replace(",", "").replace("%", "").lstrip("><~=").strip()
    try:
        return float(s)
    except ValueError:
        # Pull a leading number out of something like "3400-3100 BCE".
        m = re.match(r"[-+]?\d*\.?\d+", s)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
        return None


def to_int(value: str | None) -> int | None:
    f = to_float(value)
    return None if f is None else int(round(f))


def normalise_sex(value: str | None) -> str:
    """Map AADR's Molecular Sex to ``M`` / ``F`` / ``U``.

    AADR writes ``M``, ``F``, ``U``, and uncertain calls such as ``M?`` or
    ``F..``; anything not confidently male or female becomes ``U``.
    """
    s = clean(value)
    if not s:
        return "U"
    head = s[0].upper()
    if head == "M" and "?" not in s:
        return "M"
    if head == "F" and "?" not in s:
        return "F"
    return "U"


@dataclass
class AnnoRecord:
    """One individual's annotation, with the fields the pipeline uses typed."""

    genetic_id: str
    group_id: str
    master_id: str | None = None
    molecular_sex: str = "U"
    date_mean_bp: float | None = None
    date_sd_bp: float | None = None
    date_full_info: str | None = None
    date_method: str | None = None
    lat: float | None = None
    lon: float | None = None
    locality: str | None = None
    political_entity: str | None = None
    publication: str | None = None
    year_first_publication: int | None = None
    data_source: str | None = None
    n_snps_1240k: int | None = None
    n_snps_ho: int | None = None
    coverage_1240k: float | None = None
    assessment: str | None = None
    assessment_warnings: str | None = None
    family_id: str | None = None
    y_haplogroup: str | None = None
    mtdna_haplogroup: str | None = None
    libraries: str | None = None
    extra: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.extra is None:
            self.extra = {}

    @property
    def is_present_day(self) -> bool:
        """True when AADR records this individual as present-day.

        Date mean is 0 for present-day individuals. A missing date is treated
        as present-day only when the data source says it is array data, which
        is how AADR records the Human Origins present-day panel.
        """
        if self.date_mean_bp is not None:
            return self.date_mean_bp <= PRESENT_DAY_BP
        source = (self.data_source or "").lower()
        return "human origins" in source or source.startswith("ho")

    def n_snps(self, snpset: str) -> int | None:
        """Autosomal SNPs hit on the given panel (``"1240K"`` or ``"HO"``)."""
        key = snpset.upper()
        if key in {"HO", "HUMANORIGINS", "HUMAN_ORIGINS"}:
            return self.n_snps_ho
        if key in {"1240K", "1240000"}:
            return self.n_snps_1240k
        raise ValueError(f"unknown snpset {snpset!r}")

    def assessment_text(self) -> str:
        return " ".join(filter(None, (self.assessment, self.assessment_warnings))).upper()


_FLOAT_FIELDS = {"date_mean_bp", "date_sd_bp", "lat", "lon", "coverage_1240k"}
_INT_FIELDS = {"n_snps_1240k", "n_snps_ho", "year_first_publication"}
_KNOWN_FIELDS = set(AnnoRecord.__dataclass_fields__) - {"extra"}


def _record_from_row(row: Mapping[str, str | None]) -> AnnoRecord:
    kwargs: dict[str, Any] = {}
    extra: dict[str, str] = {}
    for key, raw in row.items():
        if key not in _KNOWN_FIELDS:
            value = clean(raw)
            if value is not None:
                extra[key] = value
            continue
        if key in _FLOAT_FIELDS:
            kwargs[key] = to_float(raw)
        elif key in _INT_FIELDS:
            kwargs[key] = to_int(raw)
        elif key == "molecular_sex":
            kwargs[key] = normalise_sex(raw)
        else:
            kwargs[key] = clean(raw)
    gid = kwargs.get("genetic_id")
    grp = kwargs.get("group_id")
    if not gid:
        raise AnnoFormatError("row has an empty Genetic ID")
    if not grp:
        # AADR occasionally leaves Group ID blank for withdrawn rows; make the
        # row explicit rather than silently inventing a population.
        kwargs["group_id"] = f"Ignore_{gid}"
    kwargs["extra"] = extra
    return AnnoRecord(**kwargs)


def iter_anno(path: str | Path, *, strict: bool = False) -> Iterator[AnnoRecord]:
    """Stream an AADR ``.anno`` file as :class:`AnnoRecord` values.

    The file is tab-separated in every release seen so far, but the delimiter
    is sniffed so a comma- or semicolon-separated export still parses.

    Args:
        path: Path to the ``.anno`` file.
        strict: Raise on a row whose column count disagrees with the header.
            The default skips such rows after counting them, because AADR
            occasionally ships a row with an unescaped tab in a free-text
            field and one bad row should not abort the build.

    Raises:
        AnnoFormatError: The header is unusable, or a row is malformed and
            ``strict`` is set.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        first = fh.readline()
        if not first:
            raise AnnoFormatError(f"{path} is empty")
        delimiter = _sniff_delimiter(first)
        fh.seek(0)
        reader = csv.reader(fh, delimiter=delimiter, quoting=csv.QUOTE_NONE)
        try:
            header = next(reader)
        except StopIteration as exc:  # pragma: no cover - guarded by the check above
            raise AnnoFormatError(f"{path} has no header") from exc
        index_to_field, _ = map_header(header)
        n_cols = len(header)

        for lineno, raw_row in enumerate(reader, start=2):
            if not raw_row or all(not c.strip() for c in raw_row):
                continue
            if len(raw_row) != n_cols:
                if strict:
                    raise AnnoFormatError(
                        f"{path}:{lineno} has {len(raw_row)} fields, header has {n_cols}"
                    )
                # Too few fields: pad. Too many: a free-text field contained the
                # delimiter, so keep the leading columns, which are the IDs.
                if len(raw_row) < n_cols:
                    raw_row = [*raw_row, *([""] * (n_cols - len(raw_row)))]
                else:
                    raw_row = raw_row[:n_cols]
            row = {
                field_name: raw_row[idx]
                for idx, field_name in index_to_field.items()
                if idx < len(raw_row)
            }
            yield _record_from_row(row)


def _sniff_delimiter(header_line: str) -> str:
    counts = {d: header_line.count(d) for d in ("\t", ",", ";")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else "\t"


def read_anno(path: str | Path, *, strict: bool = False) -> list[AnnoRecord]:
    """Read a whole ``.anno`` file into memory (AADR releases are ~20k rows)."""
    return list(iter_anno(path, strict=strict))


def header_report(path: str | Path) -> dict[str, Any]:
    """Describe how a file's header was resolved, for debugging a new release."""
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        first = fh.readline()
        if not first:
            raise AnnoFormatError(f"{path} is empty")
        delimiter = _sniff_delimiter(first)
        header = next(csv.reader([first], delimiter=delimiter, quoting=csv.QUOTE_NONE))
    index_to_field, unmapped = map_header(header)
    mapped = {
        field_name: header[idx].strip()
        for idx, field_name in index_to_field.items()
        if field_name not in unmapped
    }
    return {
        "path": str(path),
        "delimiter": "tab" if delimiter == "\t" else delimiter,
        "n_columns": len(header),
        "mapped": mapped,
        "unmapped": unmapped,
        "missing_optional": sorted(
            r.canonical
            for r in COLUMN_RULES
            if r.canonical not in mapped and not r.required
        ),
    }
