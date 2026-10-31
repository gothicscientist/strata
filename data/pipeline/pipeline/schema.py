"""Parquet writers for `data/derived`.

Column names and types are fixed by `strata.reference.library.ReferenceLibrary`
and documented in `docs/notes/reference-schema.md`. Explicit pyarrow schemas
are declared rather than letting pandas infer them, so an all-null column keeps
its type and the loader's pydantic validation stays stable across builds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .curate import CuratedPopulation, CuratedSample

POPULATIONS_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("group_id", pa.string()),
        ("name", pa.string()),
        ("region", pa.string()),
        ("country", pa.string()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("period", pa.string()),
        ("culture", pa.string()),
        ("date_mean_bp", pa.float64()),
        ("date_sd", pa.float64()),
        ("date_min_bp", pa.float64()),
        ("date_max_bp", pa.float64()),
        ("n_samples", pa.int32()),
        ("data_source", pa.string()),
        ("publication_ids", pa.list_(pa.string())),
        ("spaces", pa.list_(pa.string())),
        ("role", pa.string()),
        ("panel_block", pa.string()),
    ]
)

SAMPLES_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("population_id", pa.string()),
        ("group_id", pa.string()),
        ("master_id", pa.string()),
        ("sex", pa.string()),
        ("date_mean_bp", pa.float64()),
        ("date_sd", pa.float64()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("country", pa.string()),
        ("locality", pa.string()),
        ("data_type", pa.string()),
        ("n_snps", pa.int64()),
        ("pseudohaploid", pa.bool_()),
        ("publication_id", pa.string()),
        ("assessment", pa.string()),
    ]
)

PUBLICATIONS_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("citation", pa.string()),
        ("year", pa.int32()),
        ("doi", pa.string()),
        ("url", pa.string()),
    ]
)


def _write(rows: list[dict[str, Any]], schema: pa.Schema, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = {
        field.name: [row.get(field.name) for row in rows] for field in schema
    }
    table = pa.table(cols, schema=schema)
    pq.write_table(table, path, compression="zstd")
    return table.num_rows


def write_populations(populations: list[CuratedPopulation], path: Path) -> int:
    rows = [
        {
            "id": p.id,
            "group_id": p.group_id,
            "name": p.name,
            "region": p.region,
            "country": p.country,
            "lat": p.lat,
            "lon": p.lon,
            "period": p.period,
            "culture": p.culture,
            "date_mean_bp": p.date_mean_bp,
            "date_sd": p.date_sd,
            "date_min_bp": p.date_min_bp,
            "date_max_bp": p.date_max_bp,
            "n_samples": p.n_samples,
            "data_source": p.data_source,
            "publication_ids": list(p.publication_ids),
            "spaces": list(p.spaces),
            "role": p.role,
            "panel_block": p.panel_block,
        }
        for p in populations
    ]
    return _write(rows, POPULATIONS_SCHEMA, path)


def write_samples(samples: list[CuratedSample], path: Path) -> int:
    rows = [
        {
            "id": s.id,
            "population_id": s.population_id,
            "group_id": s.group_id,
            "master_id": s.master_id,
            "sex": s.sex,
            "date_mean_bp": s.date_mean_bp,
            "date_sd": s.date_sd,
            "lat": s.lat,
            "lon": s.lon,
            "country": s.country,
            "locality": s.locality,
            "data_type": s.data_type,
            "n_snps": s.n_snps,
            "pseudohaploid": s.pseudohaploid,
            "publication_id": s.publication_id,
            "assessment": s.assessment,
        }
        for s in samples
    ]
    return _write(rows, SAMPLES_SCHEMA, path)


@dataclass
class PublicationRow:
    id: str
    citation: str
    year: int | None = None
    doi: str | None = None
    url: str | None = None


def write_publications(publications: list[PublicationRow], path: Path) -> int:
    rows = [
        {"id": p.id, "citation": p.citation, "year": p.year, "doi": p.doi, "url": p.url}
        for p in publications
    ]
    return _write(rows, PUBLICATIONS_SCHEMA, path)


def coordinates_schema(dim_names: list[str]) -> pa.Schema:
    return pa.schema(
        [("sample_id", pa.string()), ("population_id", pa.string())]
        + [(d, pa.float64()) for d in dim_names]
        + [("n_snps_used", pa.int64()), ("projected", pa.bool_())]
    )


def write_coordinates(
    *,
    sample_ids: list[str],
    population_ids: list[str],
    coords: Any,
    dim_names: list[str],
    n_snps_used: list[int],
    projected: list[bool],
    path: Path,
) -> int:
    """Write one coordinate space.

    `projected` marks rows produced by least-squares projection rather than by
    the PCA fit itself. Projected coordinates are shrunk towards the origin, so
    consumers that compare distances must know which rows are which.
    """
    schema = coordinates_schema(dim_names)
    rows: list[dict[str, Any]] = []
    for i, sid in enumerate(sample_ids):
        row: dict[str, Any] = {
            "sample_id": sid,
            "population_id": population_ids[i],
            "n_snps_used": int(n_snps_used[i]),
            "projected": bool(projected[i]),
        }
        for j, d in enumerate(dim_names):
            value = float(coords[i][j])
            row[d] = value
        rows.append(row)
    return _write(rows, schema, path)


def write_spaces(spaces: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"spaces": spaces}, indent=2) + "\n", encoding="utf-8")
