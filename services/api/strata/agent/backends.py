"""Adapter from the agent's ``ReferenceBackend`` protocol to ``strata.reference``.

All imports of the reference library happen here, so the tool layer depends only on the
protocol defined in ``tools.py``.
"""

from __future__ import annotations

import importlib
from functools import lru_cache
from typing import Any

import numpy as np

from strata.agent.tools import ToolUnavailableError


def _dump(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return dict(obj)
    return {k: v for k, v in vars(obj).items() if not k.startswith("_")}


_SUMMARY_KEYS = (
    "id",
    "name",
    "region",
    "country",
    "period",
    "date_bp",
    "date_range_bp",
    "n_samples",
    "lat",
    "lon",
    "publication",
    "publication_id",
    "spaces",
)


class LibraryReference:
    """Wraps a loaded ``strata.reference`` library object."""

    def __init__(self, lib: Any) -> None:
        self._lib = lib

    def _populations(self) -> list[dict[str, Any]]:
        pops = getattr(self._lib, "populations", None)
        if callable(pops):
            pops = pops()
        if pops is None:
            raise ToolUnavailableError("reference library exposes no populations")
        return [_dump(p) for p in (pops.values() if isinstance(pops, dict) else pops)]

    def search(
        self, query: str | None, region: str | None, period: str | None, limit: int
    ) -> list[dict[str, Any]]:
        fn = getattr(self._lib, "search", None)
        if callable(fn):
            rows = fn(q=query, region=region, period=period, limit=limit)
            return [self._summary(_dump(r)) for r in rows][:limit]
        q = (query or "").lower()
        out = []
        for p in self._populations():
            hay = " ".join(str(v) for v in p.values() if isinstance(v, str)).lower()
            if q and q not in hay:
                continue
            if region and region.lower() not in str(p.get("region", "")).lower():
                continue
            if period and period.lower() not in str(p.get("period", "")).lower():
                continue
            out.append(self._summary(p))
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _summary(p: dict[str, Any]) -> dict[str, Any]:
        return {k: p[k] for k in _SUMMARY_KEYS if p.get(k) is not None}

    def get(self, population_id: str) -> dict[str, Any] | None:
        fn = getattr(self._lib, "get_population", None) or getattr(self._lib, "get", None)
        if callable(fn):
            try:
                row = fn(population_id)
            except KeyError:
                return None
            return _dump(row) if row is not None else None
        for p in self._populations():
            if p.get("id") == population_id:
                return p
        return None

    def coordinates(self, space: str) -> tuple[list[str], np.ndarray]:
        fn = getattr(self._lib, "population_means", None) or getattr(self._lib, "coordinates", None)
        if not callable(fn):
            raise ToolUnavailableError("reference library exposes no population coordinates")
        res = fn(space)
        if isinstance(res, tuple) and len(res) == 2:
            names, mat = res
        elif hasattr(res, "index") and hasattr(res, "to_numpy"):  # pandas DataFrame
            names, mat = list(res.index), res.to_numpy()
        else:
            raise ToolUnavailableError(f"unrecognised coordinate table type {type(res).__name__}")
        return [str(n) for n in names], np.asarray(mat, dtype=float)

    def all_metadata(self) -> list[dict[str, Any]]:
        rows = [{"kind": "population", **self._summary(p)} for p in self._populations()]
        pubs = getattr(self._lib, "publications", None)
        if callable(pubs):
            pubs = pubs()
        for pub in (pubs.values() if isinstance(pubs, dict) else pubs) or []:
            d = _dump(pub)
            rows.append({"kind": "publication", **d})
        return rows


@lru_cache(maxsize=1)
def default_reference() -> LibraryReference:
    try:
        mod = importlib.import_module("strata.reference")
    except ImportError as exc:
        raise ToolUnavailableError(f"strata.reference is not available: {exc}") from exc
    loader = getattr(mod, "load_library", None) or getattr(mod, "get_library", None)
    if loader is None:
        raise ToolUnavailableError("strata.reference provides no library loader")
    try:
        lib = loader()
    except FileNotFoundError as exc:
        raise ToolUnavailableError(f"reference data not built: {exc}") from exc
    return LibraryReference(lib)
