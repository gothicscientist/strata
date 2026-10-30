"""Single place where the platform reaches into the science modules (strata.reference,
strata.analysis, strata.qpadm, strata.agent). Every import is lazy so the API boots, and
reports capabilities honestly, before (or without) those modules and their data."""

from __future__ import annotations

import importlib
import logging
from functools import lru_cache
from typing import Any

log = logging.getLogger("strata.api")


class ScienceUnavailableError(RuntimeError):
    """A science component or its data is not installed in this deployment."""


def _module(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise ScienceUnavailableError(f"{name} is not available: {exc}") from exc


@lru_cache(maxsize=1)
def reference_library() -> Any:
    """The strata.reference library; ScienceUnavailableError if its data is not built."""
    mod = _module("strata.reference")
    lib = mod.load_library()
    if not getattr(lib, "available", True):
        missing = ", ".join(getattr(lib, "missing", []) or [])
        raise ScienceUnavailableError(f"reference data not built (missing: {missing})")
    return lib


def try_reference_library() -> Any | None:
    try:
        return reference_library()
    except ScienceUnavailableError:
        return None
    except Exception:  # noqa: BLE001 - corrupt data must not take the API down
        log.exception("reference library failed to load")
        return None


def reference_version() -> str | None:
    lib = try_reference_library()
    return None if lib is None else lib.version


@lru_cache(maxsize=1)
def snp_panel() -> Any | None:
    """The reference SNP panel used to harmonise raw DNA, or None if not built."""
    lib = try_reference_library()
    if lib is None:
        return None
    try:
        return lib.snp_panel()
    except FileNotFoundError:
        return None


_qpadm_cache: tuple[float, bool] | None = None


def qpadm_available(ttl_s: float = 60.0) -> bool:
    """R + ADMIXTOOLS 2 present (probe runs an Rscript, so cache it briefly)."""
    global _qpadm_cache
    import time

    now = time.monotonic()
    if _qpadm_cache is not None and now - _qpadm_cache[0] < ttl_s:
        return _qpadm_cache[1]
    try:
        mod = _module("strata.qpadm")
        ok = bool(mod.qpadm_available())
    except Exception:  # noqa: BLE001
        ok = False
    _qpadm_cache = (now, ok)
    return ok


def admixtools_version() -> str | None:
    try:
        return _module("strata.qpadm").admixtools_version()
    except Exception:  # noqa: BLE001
        return None


def llm_providers() -> list[str]:
    try:
        mod = _module("strata.agent")
        avail = mod.llm_available()
        return sorted(k for k, v in avail.items() if v)
    except Exception:  # noqa: BLE001 - fall back to settings
        from strata.config import get_settings

        s = get_settings()
        return [p for p, k in (("anthropic", s.anthropic_api_key),
                               ("openai", s.openai_api_key)) if k]


def reset_caches() -> None:
    global _qpadm_cache
    _qpadm_cache = None
    reference_library.cache_clear()
    snp_panel.cache_clear()


# ------------------------------------------------------------------ reference coordinates


def require_reference() -> Any:
    lib = try_reference_library()
    if lib is None:
        raise ScienceUnavailableError(
            "reference library is not installed: analyses against reference populations are "
            "unavailable (build data/derived with the data pipeline)"
        )
    return lib


def coordinate_table(space: str) -> Any:
    """Population-mean coordinates in `space` (strata.analysis CoordinateTable)."""
    lib = require_reference()
    try:
        table, _counts = lib.population_table(space)
    except FileNotFoundError as exc:
        raise ScienceUnavailableError(f"no reference coordinates for space {space!r}") from exc
    return table


def sample_coordinates(space: str, population: str) -> Any | None:
    """Individual coordinates of one reference population (for bootstrap), or None when the
    space stores only population means."""
    lib = require_reference()
    try:
        return lib.population_samples(space, [population])[population]
    except (KeyError, ValueError, FileNotFoundError):
        return None


def pca_model(space: str) -> Any:
    lib = require_reference()
    try:
        return lib.pca_model(space)
    except FileNotFoundError as exc:
        raise ScienceUnavailableError(f"no PCA model for space {space!r}") from exc


PCA_SPACE = "strata-pca-v1"


def default_pca_space() -> str | None:
    lib = try_reference_library()
    if lib is None:
        return None
    ids = [sp.id for sp in lib.spaces()]
    if PCA_SPACE in ids:
        return PCA_SPACE
    pcs = [i for i in ids if i != "g25"]
    return pcs[0] if pcs else None
