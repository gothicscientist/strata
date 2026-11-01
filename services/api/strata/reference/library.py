"""Reference library: populations, samples, publications and coordinates from ``data/derived``.

The on-disk schema is specified in ``docs/notes/reference-schema.md`` (written by the data
pipeline). If the derived data is absent the library loads empty with ``available=False``;
nothing is ever synthesised in its place.
"""

from __future__ import annotations

import json
import math
import os
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, computed_field

from strata.analysis.types import CoordinateTable
from strata.io.types import SnpPanel

SCHEMA_VERSION = "1"
_REPO_ROOT = Path(__file__).resolve().parents[4]


def default_root() -> Path:
    env = os.environ.get("STRATA_DERIVED_DIR")
    if env:
        return Path(env)
    data = os.environ.get("STRATA_DATA_DIR")
    return Path(data) / "derived" if data else _REPO_ROOT / "data" / "derived"


# --------------------------------------------------------------------------- models


class Publication(BaseModel):
    id: str
    citation: str
    year: int | None = None
    doi: str | None = None
    url: str | None = None


class Population(BaseModel):
    id: str
    group_id: str | None = Field(
        None, description="AADR Group ID verbatim; the label sent to ADMIXTOOLS / strata.qpadm"
    )
    name: str
    region: str | None = None
    country: str | None = None
    lat: float | None = None
    lon: float | None = None
    period: str | None = None
    culture: str | None = None
    date_mean_bp: float | None = None
    date_sd: float | None = None
    date_min_bp: float | None = None
    date_max_bp: float | None = None
    n_samples: int = 0
    data_source: str
    publication_ids: list[str] = Field(default_factory=list)
    spaces: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_dataset(self) -> str:
        return self.data_source

    def date_range(self) -> tuple[float, float] | None:
        lo, hi = self.date_min_bp, self.date_max_bp
        if lo is None and hi is None and self.date_mean_bp is not None:
            sd = self.date_sd or 0.0
            lo, hi = self.date_mean_bp - 2 * sd, self.date_mean_bp + 2 * sd
        if lo is None or hi is None:
            return None
        return (min(lo, hi), max(lo, hi))


class Sample(BaseModel):
    id: str
    population_id: str
    master_id: str | None = None
    sex: str | None = None
    date_mean_bp: float | None = None
    date_sd: float | None = None
    lat: float | None = None
    lon: float | None = None
    country: str | None = None
    locality: str | None = None
    data_type: str | None = None
    n_snps: int | None = None
    pseudohaploid: bool | None = None
    publication_id: str | None = None
    assessment: str | None = None


class PopulationDetail(Population):
    samples: list[Sample] = Field(default_factory=list)
    publications: list[Publication] = Field(default_factory=list)


class CoordinateSpace(BaseModel):
    id: str
    name: str
    version: str
    n_dims: int
    dim_names: list[str]
    level: str = Field(description="'sample' (per-individual rows) or 'population' (means)")
    description: str = ""
    explained_variance_ratio: list[float] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class PopulationPage(BaseModel):
    items: list[Population]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- helpers


def _clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, np.ndarray):
        return [_clean(x) for x in v.tolist()]
    if isinstance(v, np.generic):
        return _clean(v.item())
    return v


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    cols = list(df.columns)
    return [
        {c: _clean(v) for c, v in zip(cols, row, strict=True)}
        for row in df.itertuples(index=False, name=None)
    ]


# --------------------------------------------------------------------------- library


class ReferenceLibrary:
    """Read-only view over ``data/derived``. Use ``load_library()`` for a cached instance."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()
        self.missing: list[str] = [
            f for f in ("populations.parquet", "samples.parquet") if not (self.root / f).exists()
        ]
        self.available: bool = not self.missing
        manifest_path = self.root / "MANIFEST.json"
        self.manifest: dict[str, Any] = (
            json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        )

    # ---- metadata -------------------------------------------------------------------------

    @property
    def version(self) -> str | None:
        if not self.available:
            return None
        return str(
            self.manifest.get("version") or self.manifest.get("reference_version") or "unversioned"
        )

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "root": str(self.root),
            "version": self.version,
            "missing": self.missing,
            "n_populations": len(self._populations),
            "spaces": [s.id for s in self.spaces()],
            "limits": self.limits(),
        }

    def panel(self) -> dict[str, Any]:
        """How the curated panel resolved against the release it was built from.

        The pipeline records this; the API only passes it on. It carries the
        standing outgroup set as it resolved, the panel's limits, and the
        labels the release renamed, does not carry, or does not carry for any
        recorded reason — so a caller can see what the panel is made of rather
        than inferring it from the population list.
        """
        panel = self.manifest.get("panel")
        if not isinstance(panel, dict):
            return {}
        return panel

    def limits(self) -> list[dict[str, Any]]:
        """Questions this panel cannot answer, as the pipeline computed them.

        Returned with every formal result and reported by `/health`, because a
        number returned for a question the panel cannot answer is worse than
        no number. Empty when the panel resolved with no known limits — or
        when the manifest predates limit reporting, which is why the shape is
        validated rather than trusted.
        """
        limits = self.panel().get("limits")
        if not isinstance(limits, list):
            return []
        return [limit for limit in limits if isinstance(limit, dict) and limit.get("id")]

    @cached_property
    def _populations(self) -> dict[str, Population]:
        path = self.root / "populations.parquet"
        if not path.exists():
            return {}
        df = pd.read_parquet(path)
        if "publications" in df.columns and "publication_ids" not in df.columns:
            df = df.rename(columns={"publications": "publication_ids"})
        out: dict[str, Population] = {}
        for rec in _records(df):
            rec["publication_ids"] = list(rec.get("publication_ids") or [])
            rec["spaces"] = list(rec.get("spaces") or [])
            p = Population.model_validate(rec)
            out[p.id] = p
        return out

    @cached_property
    def _samples(self) -> pd.DataFrame:
        path = self.root / "samples.parquet"
        if not path.exists():
            return pd.DataFrame(columns=["id", "population_id"])
        return pd.read_parquet(path)

    @cached_property
    def _publications(self) -> dict[str, Publication]:
        path = self.root / "publications.parquet"
        if not path.exists():
            return {}
        return {r["id"]: Publication.model_validate(r) for r in _records(pd.read_parquet(path))}

    @cached_property
    def _spaces(self) -> dict[str, CoordinateSpace]:
        path = self.root / "spaces.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text())
        items = data["spaces"] if isinstance(data, dict) else data
        return {s["id"]: CoordinateSpace.model_validate(s) for s in items}

    def populations(self) -> list[Population]:
        return list(self._populations.values())

    def publications(self) -> list[Publication]:
        return list(self._publications.values())

    def spaces(self) -> list[CoordinateSpace]:
        return list(self._spaces.values())

    def space(self, space_id: str) -> CoordinateSpace:
        try:
            return self._spaces[space_id]
        except KeyError:
            raise KeyError(f"unknown coordinate space {space_id!r}") from None

    def samples(self, population_id: str | None = None) -> list[Sample]:
        df = self._samples
        if population_id is not None:
            df = df[df["population_id"] == population_id]
        return [Sample.model_validate(r) for r in _records(df)]

    def get_population(self, population_id: str) -> PopulationDetail:
        """Population with its samples and resolved publication records. KeyError if absent."""
        p = self._populations[population_id]
        pubs = [self._publications[i] for i in p.publication_ids if i in self._publications]
        return PopulationDetail(
            **p.model_dump(exclude={"source_dataset"}),
            samples=self.samples(population_id),
            publications=pubs,
        )

    get = get_population

    # ---- search ---------------------------------------------------------------------------

    def _filter(
        self,
        q: str | None,
        region: str | None,
        period: str | None,
        country: str | None,
        min_bp: float | None,
        max_bp: float | None,
        space: str | None,
    ) -> list[Population]:
        tokens = [t for t in (q or "").lower().replace(",", " ").split() if t]
        ql = (q or "").strip().lower()
        hits: list[tuple[tuple[int, str], Population]] = []
        for p in self._populations.values():
            if region and (p.region or "").lower() != region.lower():
                continue
            if period and (p.period or "").lower() != period.lower():
                continue
            if country and (p.country or "").lower() != country.lower():
                continue
            if space and space not in p.spaces:
                continue
            if min_bp is not None or max_bp is not None:
                rng = p.date_range()
                if rng is None:
                    continue
                if min_bp is not None and rng[1] < min_bp:
                    continue
                if max_bp is not None and rng[0] > max_bp:
                    continue
            score = 0
            if tokens:
                fields = [p.id, p.name, p.region, p.country, p.period, p.culture]
                hay = " ".join(f for f in fields if f).lower()
                name = p.name.lower()
                if ql in (p.id.lower(), name):
                    score = 0
                elif name.startswith(ql) or p.id.lower().startswith(ql):
                    score = 1
                elif ql in name or ql in p.id.lower():
                    score = 2
                elif all(t in hay for t in tokens):
                    score = 3
                else:
                    continue
            hits.append(((score, p.name.lower()), p))
        hits.sort(key=lambda x: x[0])
        return [p for _, p in hits]

    def search(
        self,
        q: str | None = None,
        *,
        region: str | None = None,
        period: str | None = None,
        country: str | None = None,
        min_bp: float | None = None,
        max_bp: float | None = None,
        space: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Population]:
        """Substring/token search over id, name, region, country, period, culture; filters are
        exact (case-insensitive); the date filter keeps populations overlapping [min_bp, max_bp]."""
        rows = self._filter(q, region, period, country, min_bp, max_bp, space)
        return rows[offset : offset + limit]

    def search_page(
        self,
        q: str | None = None,
        *,
        page: int = 1,
        page_size: int = 50,
        **filters: Any,
    ) -> PopulationPage:
        rows = self._filter(
            q,
            filters.get("region"),
            filters.get("period"),
            filters.get("country"),
            filters.get("min_bp"),
            filters.get("max_bp"),
            filters.get("space"),
        )
        start = (max(page, 1) - 1) * page_size
        return PopulationPage(
            items=rows[start : start + page_size], total=len(rows), page=page, page_size=page_size
        )

    def facets(self) -> dict[str, list[str]]:
        pops = self._populations.values()
        return {
            k: sorted({str(getattr(p, k)) for p in pops if getattr(p, k)})
            for k in ("region", "period", "country", "data_source")
        }

    # ---- coordinates ----------------------------------------------------------------------

    @lru_cache(maxsize=8)  # noqa: B019 - library instances are long-lived singletons
    def _coord_frame(self, space: str) -> pd.DataFrame:
        path = self.root / "coordinates" / f"{space}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"no coordinates for space {space!r} in {self.root}")
        return pd.read_parquet(path)

    def _dim_cols(self, space: str, df: pd.DataFrame) -> list[str]:
        if space in self._spaces:
            return self._spaces[space].dim_names
        return [c for c in df.columns if c.upper().startswith("PC")]

    def coordinates(self, space: str) -> CoordinateTable:
        """Rows as stored: individuals (``sample_id``) or populations (``population_id``)."""
        df = self._coord_frame(space)
        dims = self._dim_cols(space, df)
        key = "sample_id" if "sample_id" in df.columns else "population_id"
        return CoordinateTable(
            space=space,
            names=df[key].astype(str).tolist(),
            matrix=df[dims].to_numpy(dtype=np.float64),
            dim_names=dims,
        )

    def _sample_frame(self, space: str) -> pd.DataFrame:
        df = self._coord_frame(space)
        if "sample_id" not in df.columns:
            raise ValueError(f"space {space!r} stores population means, not individuals")
        if "population_id" not in df.columns:
            df = df.merge(
                self._samples[["id", "population_id"]].rename(columns={"id": "sample_id"}),
                on="sample_id",
                how="left",
            )
        return df

    def population_table(self, space: str) -> tuple[CoordinateTable, dict[str, int]]:
        """Population mean coordinates and the number of individuals averaged."""
        df = self._coord_frame(space)
        dims = self._dim_cols(space, df)
        if "sample_id" not in df.columns:
            names = df["population_id"].astype(str).tolist()
            counts = {
                n: int(self._populations[n].n_samples) if n in self._populations else 0
                for n in names
            }
            if "n_samples" in df.columns:
                counts = dict(zip(names, df["n_samples"].astype(int).tolist(), strict=True))
            return (
                CoordinateTable(
                    space=space, names=names, matrix=df[dims].to_numpy(np.float64), dim_names=dims
                ),
                counts,
            )
        df = self._sample_frame(space).dropna(subset=["population_id"])
        g = df.groupby("population_id", sort=True)[dims]
        means = g.mean()
        counts = g.size().astype(int).to_dict()
        return (
            CoordinateTable(
                space=space,
                names=[str(i) for i in means.index],
                matrix=means.to_numpy(np.float64),
                dim_names=dims,
            ),
            {str(k): int(v) for k, v in counts.items()},
        )

    def population_means(self, space: str) -> tuple[list[str], np.ndarray]:
        table, _ = self.population_table(space)
        return table.names, table.matrix

    def population_samples(self, space: str, population_ids: list[str]) -> dict[str, np.ndarray]:
        """Individual coordinates per population (for bootstrap over individuals)."""
        df = self._sample_frame(space)
        dims = self._dim_cols(space, df)
        out: dict[str, np.ndarray] = {}
        for pid in population_ids:
            sub = df[df["population_id"] == pid]
            if sub.empty:
                raise KeyError(f"no individuals of {pid!r} in space {space!r}")
            out[pid] = sub[dims].to_numpy(np.float64)
        return out

    # ---- genotype-side artefacts ----------------------------------------------------------

    def snp_panel(self) -> SnpPanel:

        path = self.root / "snp_panel.parquet"
        if not path.exists():
            raise FileNotFoundError(f"snp_panel.parquet not found in {self.root}")
        return _cached_panel(str(path), path.stat().st_mtime)

    def pca_model(self, space: str = "strata-pca-v1"):  # noqa: ANN201
        from strata.analysis.pca import PCAModel

        path = self.root / "pca" / f"{space}.npz"
        if not path.exists():
            raise FileNotFoundError(f"PCA model for {space!r} not found in {self.root}")
        return PCAModel.load(path)


@lru_cache(maxsize=2)
def _cached_panel(path: str, _mtime: float) -> SnpPanel:
    from strata.io.eigenstrat import read_panel_parquet

    return read_panel_parquet(path)


@lru_cache(maxsize=4)
def _load_cached(root: str) -> ReferenceLibrary:
    return ReferenceLibrary(root)


def load_library(root: str | Path | None = None) -> ReferenceLibrary:
    """Cached library for ``root`` (default: $STRATA_DERIVED_DIR or data/derived). Never raises
    for missing data: check ``.available``."""
    return _load_cached(str(Path(root) if root is not None else default_root()))


get_library = load_library
