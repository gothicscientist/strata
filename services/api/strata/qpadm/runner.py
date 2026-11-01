"""Subprocess bridge from Python to the ADMIXTOOLS 2 wrapper scripts.

Contract with ``services/worker/r/*.R``:

* the spec is written as JSON to a private temp directory,
* the script is invoked as ``Rscript <script> <spec.json> <out.json>``,
* the script always writes ``out.json`` with an ``"ok"`` boolean, so the exit
  code is only a hint and stderr is only ever used for diagnostics.

Nothing in this module logs genotype data. Specs contain file paths and
population labels; paths are logged, file contents never are, and stderr from R
is attached to exceptions rather than emitted at info level because ADMIXTOOLS
progress output can include per-population SNP counts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from .interpret import annotate_qpadm, annotate_rotate_model
from .types import (
    ExtractF2Result,
    ExtractF2Spec,
    F4Result,
    F4Spec,
    QpAdmResult,
    QpAdmRotateResult,
    QpAdmRotateSpec,
    QpAdmSpec,
    QpWaveResult,
    QpWaveSpec,
)

log = structlog.get_logger(__name__)

DEFAULT_TIMEOUT = 1800.0
# Candidate Rscript locations, used when STRATA_RSCRIPT is unset.
_FALLBACK_RSCRIPTS = (
    "/opt/strata-r/bin/Rscript",
    str(Path.home() / "strata-r" / "bin" / "Rscript"),
)

_ResultT = TypeVar("_ResultT", bound=BaseModel)


class QpAdmError(RuntimeError):
    """Base class for every failure of the R bridge."""


class QpAdmUnavailable(QpAdmError):  # noqa: N818 - "Unavailable" reads better than "Error"
    """R or ADMIXTOOLS 2 is not installed or not reachable."""


class QpAdmTimeout(QpAdmError):  # noqa: N818 - "Timeout" reads better than "TimeoutError"
    """The R process exceeded its time budget."""


class QpAdmRunError(QpAdmError):
    """R ran but reported a structured error."""

    def __init__(
        self,
        message: str,
        *,
        kind: str | None = None,
        r_call: str | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.r_call = r_call
        self.stderr = stderr


class QpAdmProtocolError(QpAdmError):
    """R produced output that does not match the contract."""


def r_script_dir() -> Path:
    """Directory holding the ADMIXTOOLS wrapper scripts.

    ``STRATA_R_DIR`` overrides the default, which is ``services/worker/r``
    resolved relative to this file inside the monorepo.
    """
    override = os.environ.get("STRATA_R_DIR")
    if override:
        return Path(override).expanduser().resolve()
    # strata/qpadm/runner.py -> strata -> api -> services -> <repo>
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "services" / "worker" / "r"


def rscript_path() -> str | None:
    """Locate ``Rscript``: ``STRATA_RSCRIPT``, then ``PATH``, then known prefixes."""
    override = os.environ.get("STRATA_RSCRIPT")
    if override:
        candidate = Path(override).expanduser()
        return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    found = shutil.which("Rscript")
    if found:
        return found
    for fallback in _FALLBACK_RSCRIPTS:
        if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
            return fallback
    return None


def default_f2_dir() -> Path | None:
    """The f2 cache callers should use when a request does not name one.

    Resolution order:

    1. ``STRATA_F2_DIR`` — an explicit path, honoured even if it does not exist
       yet (so a misconfiguration surfaces as a clear ADMIXTOOLS error rather
       than silently falling back to a different panel).
    2. ``data/derived/f2/<STRATA_REFERENCE_VERSION or "strata-ref-v1">``
       inside the monorepo, if that directory exists.

    Returns None when neither is available, which means no reference f2 cache
    has been built yet; callers should surface that rather than guess.
    """
    override = os.environ.get("STRATA_F2_DIR")
    if override:
        return Path(override).expanduser()
    version = os.environ.get("STRATA_REFERENCE_VERSION", "strata-ref-v1")
    repo_root = Path(__file__).resolve().parents[4]
    candidate = repo_root / "data" / "derived" / "f2" / version
    return candidate if candidate.is_dir() else None


def _timeout_default() -> float:
    raw = os.environ.get("STRATA_QPADM_TIMEOUT")
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        log.warning("qpadm.bad_timeout_env", value=raw)
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT


def qpadm_available() -> bool:
    """True when Rscript, the wrapper scripts and ADMIXTOOLS 2 are all present.

    Cheap enough for a health endpoint: it runs one short R process.
    """
    exe = rscript_path()
    if exe is None:
        return False
    scripts = r_script_dir()
    if not (scripts / "common.R").is_file() or not (scripts / "qpadm.R").is_file():
        return False
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                exe,
                "--vanilla",
                "-e",
                'q(status = if (requireNamespace("admixtools", quietly = TRUE) &&'
                ' requireNamespace("jsonlite", quietly = TRUE)) 0L else 1L)',
            ],
            capture_output=True,
            timeout=120,
            check=False,
            env=_child_env(1),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def admixtools_version() -> str | None:
    """Installed ADMIXTOOLS 2 version, or None when it cannot be determined."""
    exe = rscript_path()
    if exe is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                exe,
                "--vanilla",
                "-e",
                'cat(tryCatch(as.character(utils::packageVersion("admixtools")),'
                ' error = function(e) ""))',
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=_child_env(1),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    version = proc.stdout.strip()
    return version or None


def _child_env(threads: int) -> dict[str, str]:
    """Environment for the R child: thread caps, no user profile interference."""
    env = dict(os.environ)
    env.update(
        {
            "OMP_NUM_THREADS": str(threads),
            "OPENBLAS_NUM_THREADS": str(threads),
            "MKL_NUM_THREADS": str(threads),
            "R_LIBS_USER": env.get("R_LIBS_USER", ""),
            # Stop ADMIXTOOLS/cli from emitting ANSI escapes into stderr.
            "NO_COLOR": "1",
            "R_CLI_NUM_COLORS": "1",
        }
    )
    return env


def _tail(text: str | None, limit: int = 4000) -> str:
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= limit else "...(truncated)...\n" + text[-limit:]


def _invoke(
    script: str,
    spec_payload: Mapping[str, Any],
    result_model: type[_ResultT],
    *,
    timeout: float | None,
    threads: int,
) -> _ResultT:
    """Run one wrapper script and parse its JSON output."""
    exe = rscript_path()
    if exe is None:
        raise QpAdmUnavailable(
            "Rscript was not found. Set STRATA_RSCRIPT to the Rscript built by "
            "services/worker/r/install_env.sh."
        )
    script_path = r_script_dir() / script
    if not script_path.is_file():
        raise QpAdmUnavailable(
            f"R wrapper script not found: {script_path}. Set STRATA_R_DIR to the "
            "directory containing the ADMIXTOOLS wrapper scripts."
        )

    budget = _timeout_default() if timeout is None else timeout

    with tempfile.TemporaryDirectory(prefix="strata-qpadm-") as tmp:
        tmpdir = Path(tmp)
        spec_file = tmpdir / "spec.json"
        out_file = tmpdir / "out.json"
        spec_file.write_text(json.dumps(spec_payload, allow_nan=False), encoding="utf-8")

        argv = [exe, "--vanilla", str(script_path), str(spec_file), str(out_file)]
        log.info(
            "qpadm.run.start",
            script=script,
            timeout=budget,
            threads=threads,
        )
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                argv,
                capture_output=True,
                text=True,
                timeout=budget,
                check=False,
                cwd=tmpdir,
                env=_child_env(threads),
            )
        except subprocess.TimeoutExpired as exc:
            raise QpAdmTimeout(
                f"{script} exceeded its {budget:g}s budget. Precompute f2 blocks with "
                "extract_f2, reduce the number of populations, or raise "
                "STRATA_QPADM_TIMEOUT."
            ) from exc
        except OSError as exc:
            raise QpAdmUnavailable(f"could not execute {exe}: {exc}") from exc

        stderr = _tail(proc.stderr)
        if not out_file.is_file():
            raise QpAdmProtocolError(
                f"{script} wrote no result file (exit code {proc.returncode}).\n"
                f"R stderr:\n{stderr or '<empty>'}"
            )
        try:
            payload = json.loads(out_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise QpAdmProtocolError(
                f"{script} wrote malformed JSON: {exc}.\nR stderr:\n{stderr or '<empty>'}"
            ) from exc

    if not isinstance(payload, dict):
        raise QpAdmProtocolError(
            f"{script} returned a {type(payload).__name__}, expected an object"
        )

    if not payload.get("ok", False):
        err = payload.get("error") or {}
        message = err.get("message") or "the R script reported an unspecified failure"
        kind = err.get("kind")
        if kind == "dependency_missing":
            raise QpAdmUnavailable(message)
        log.warning("qpadm.run.failed", script=script, error_kind=kind)
        raise QpAdmRunError(message, kind=kind, r_call=err.get("r_call"), stderr=stderr)

    payload.pop("ok", None)
    payload.pop("kind", None)  # R names the analysis; the model fixes it
    try:
        result = result_model.model_validate(payload)
    except ValidationError as exc:
        raise QpAdmProtocolError(
            f"{script} output did not match {result_model.__name__}: {exc}"
        ) from exc

    log.info(
        "qpadm.run.ok",
        script=script,
        elapsed=getattr(result, "elapsed_seconds", None),
    )
    return result


def _spec_payload(spec: BaseModel) -> dict[str, Any]:
    """Serialise a spec for R, dropping unset optionals."""
    return spec.model_dump(mode="json", exclude_none=True)


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def run_qpadm(
    spec: QpAdmSpec,
    *,
    timeout: float | None = None,
    assess: bool = True,
) -> QpAdmResult:
    """Fit one qpAdm model.

    Args:
        spec: Target, sources, outgroups and the f2 cache or genotype prefix.
        timeout: Seconds before the R process is killed; defaults to
            ``STRATA_QPADM_TIMEOUT`` or 1800.
        assess: Attach the heuristic :class:`~strata.qpadm.types.Feasibility`.

    Raises:
        QpAdmUnavailable: R or ADMIXTOOLS 2 is missing.
        QpAdmRunError: ADMIXTOOLS rejected the model or the data.
        QpAdmTimeout: The fit exceeded its budget.
    """
    result = _invoke(
        "qpadm.R", _spec_payload(spec), QpAdmResult, timeout=timeout, threads=spec.threads
    )
    return annotate_qpadm(result) if assess else result


def run_qpadm_rotate(
    spec: QpAdmRotateSpec,
    *,
    timeout: float | None = None,
    assess: bool = True,
) -> QpAdmRotateResult:
    """Fit every left/right split of a candidate pool and rank the models."""
    result = _invoke(
        "qpadm_rotate.R",
        _spec_payload(spec),
        QpAdmRotateResult,
        timeout=timeout,
        threads=spec.threads,
    )
    if assess:
        for model in result.models:
            annotate_rotate_model(model)
    return result


def run_qpwave(spec: QpWaveSpec, *, timeout: float | None = None) -> QpWaveResult:
    """Estimate a lower bound on the number of admixture waves between two sets."""
    return _invoke(
        "qpwave.R", _spec_payload(spec), QpWaveResult, timeout=timeout, threads=spec.threads
    )


def run_f4(spec: F4Spec, *, timeout: float | None = None) -> F4Result:
    """Compute f4- (or D-) statistics over the given population quadruples."""
    return _invoke("f4.R", _spec_payload(spec), F4Result, timeout=timeout, threads=spec.threads)


def extract_f2(spec: ExtractF2Spec, *, timeout: float | None = None) -> ExtractF2Result:
    """Precompute a reusable f2 block cache from genotype files.

    This is the expensive step: build it once per panel, then run any number of
    models against ``result.f2_dir``.
    """
    return _invoke(
        "extract_f2.R",
        _spec_payload(spec),
        ExtractF2Result,
        timeout=timeout,
        threads=max(spec.threads, spec.n_cores),
    )
