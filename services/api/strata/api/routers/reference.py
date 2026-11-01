"""Reference library endpoints (public data: AADR-derived populations, publications, spaces)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Response

from strata.api import science
from strata.api.errors import ApiError, not_found

router = APIRouter(prefix="/reference", tags=["reference"])

CACHE = "public, max-age=300"


def _lib() -> Any:
    lib = science.try_reference_library()
    if lib is None:
        raise ApiError(
            503,
            "reference library is not installed in this deployment "
            "(build data/derived with the data pipeline)",
            "reference_unavailable",
        )
    return lib


def _facets(lib: Any) -> dict[str, list[str]]:
    f = lib.facets()
    return {
        "region": f.get("region", []),
        "period": f.get("period", []),
        "country": f.get("country", []),
        "source_dataset": f.get("data_source", []),
    }


@router.get("/populations", summary="Search the reference population library")
def list_populations(
    response: Response,
    q: str | None = Query(None, max_length=200),
    region: str | None = None,
    period: str | None = None,
    country: str | None = None,
    source_dataset: str | None = None,
    min_bp: float | None = Query(
        None, description="keep populations whose date range overlaps [min_bp, max_bp] (years BP)"
    ),
    max_bp: float | None = None,
    space: str | None = Query(None, description="only populations with coordinates here"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    lib = _lib()
    rows = lib.search(
        q,
        region=region,
        period=period,
        country=country,
        min_bp=min_bp,
        max_bp=max_bp,
        space=space,
        limit=1_000_000,
    )
    if source_dataset:
        rows = [p for p in rows if p.data_source == source_dataset]
    start = (page - 1) * page_size
    response.headers["Cache-Control"] = CACHE
    return {
        "items": [p.model_dump(mode="json") for p in rows[start : start + page_size]],
        "total": len(rows),
        "page": page,
        "page_size": page_size,
        "facets": _facets(lib),
    }


@router.get("/populations/{population_id}", summary="Population detail with samples")
def get_population(population_id: str, response: Response) -> dict[str, Any]:
    try:
        detail = _lib().get_population(population_id)
    except KeyError:
        raise not_found("population") from None
    response.headers["Cache-Control"] = CACHE
    return detail.model_dump(mode="json")


@router.get("/publications", summary="Source publications of reference samples")
def list_publications(response: Response) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = CACHE
    return [p.model_dump(mode="json") for p in _lib().publications()]


@router.get("/spaces", summary="Coordinate spaces with population-mean coordinates")
def list_spaces(response: Response) -> list[dict[str, Any]]:
    """Every coordinate space with its population means (all dimensions) for plotting.
    Spaces are never mixed: G25 coordinates and Strata's own PCA are separate spaces."""
    lib = _lib()
    pops = {p.id: p for p in lib.populations()}
    out = []
    for sp in lib.spaces():
        d = sp.model_dump(mode="json")
        d["explained_variance"] = sp.explained_variance_ratio
        try:
            table, counts = lib.population_table(sp.id)
        except FileNotFoundError:
            table, counts = None, {}
        d["populations"] = (
            []
            if table is None
            else [
                {
                    "population_id": n,
                    "name": pops[n].name if n in pops else n,
                    "region": pops[n].region if n in pops else None,
                    "n_samples": counts.get(n, 0),
                    "coords": [float(x) for x in table.matrix[i]],
                }
                for i, n in enumerate(table.names)
            ]
        )
        out.append(d)
    response.headers["Cache-Control"] = CACHE
    return out
