"""Adapter from the agent's ``ReferenceBackend`` protocol to ``strata.reference``.

All imports of the reference library happen here, so the tool layer depends only on the
protocol defined in ``tools.py``. Field names follow ``strata.reference.library``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np

from strata.agent.tools import ToolUnavailableError

# Fields of Population that are useful to the model. `group_id` is included because it, not
# `id`, is the name qpAdm keys on (it comes from the AADR "Group ID" column).
_SUMMARY_KEYS = (
    "id",
    "group_id",
    "name",
    "region",
    "country",
    "period",
    "culture",
    "date_mean_bp",
    "date_min_bp",
    "date_max_bp",
    "n_samples",
    "lat",
    "lon",
    "data_source",
    "publication_ids",
    "spaces",
)


def _dump(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return dict(obj)
    return {k: v for k, v in vars(obj).items() if not k.startswith("_")}


def _summary(p: dict[str, Any]) -> dict[str, Any]:
    out = {k: p[k] for k in _SUMMARY_KEYS if p.get(k) is not None}
    # The tools and corpus speak of dates as "date_bp"; keep that alias for the model.
    if "date_mean_bp" in out:
        out["date_bp"] = out["date_mean_bp"]
    return out


class LibraryReference:
    """Wraps a ``strata.reference.ReferenceLibrary``."""

    def __init__(self, lib: Any) -> None:
        self._lib = lib

    def _require(self) -> Any:
        if not getattr(self._lib, "available", False):
            missing = ", ".join(getattr(self._lib, "missing", None) or ["reference data"])
            raise ToolUnavailableError(
                f"the reference library has not been built in this deployment (missing: "
                f"{missing}); population lookups and coordinate analyses are unavailable"
            )
        return self._lib

    def search(
        self, query: str | None, region: str | None, period: str | None, limit: int
    ) -> list[dict[str, Any]]:
        rows = self._require().search(query, region=region, period=period, limit=limit)
        return [_summary(_dump(r)) for r in rows]

    def get(self, population_id: str) -> dict[str, Any] | None:
        try:
            detail = self._require().get_population(population_id)
        except KeyError:
            return None
        return _dump(detail)

    def coordinates(self, space: str) -> tuple[list[str], np.ndarray]:
        try:
            names, matrix = self._require().population_means(space)
        except KeyError as exc:
            raise ToolUnavailableError(f"unknown coordinate space {space!r}") from exc
        except FileNotFoundError as exc:
            raise ToolUnavailableError(
                f"coordinates for space {space!r} have not been built: {exc}"
            ) from exc
        return [str(n) for n in names], np.asarray(matrix, dtype=float)

    def population_samples(self, space: str, population_ids: list[str]) -> dict[str, np.ndarray]:
        """Per-individual coordinates, for bootstrap confidence intervals."""
        try:
            samples = self._require().population_samples(space, list(population_ids))
        except KeyError as exc:
            raise ToolUnavailableError(
                f"no individual-level coordinates in space {space!r} for {exc}"
            ) from exc
        return {k: np.asarray(v, dtype=float) for k, v in samples.items()}

    def all_metadata(self) -> list[dict[str, Any]]:
        lib = self._require()
        rows = [{"kind": "population", **_summary(_dump(p))} for p in lib.populations()]
        for pub in lib.publications():
            rows.append({"kind": "publication", **_dump(pub)})
        return rows


@lru_cache(maxsize=1)
def default_reference() -> LibraryReference:
    try:
        from strata.reference import load_library
    except ImportError as exc:
        raise ToolUnavailableError(f"strata.reference is not available: {exc}") from exc
    # load_library is cached and never raises; availability is checked per call.
    return LibraryReference(load_library())
