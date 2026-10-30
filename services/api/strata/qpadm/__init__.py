"""Python bridge to ADMIXTOOLS 2 for formal f-statistic inference.

qpAdm, qpWave and f4 are *formal* tests: they compare allele-frequency
correlations between populations and report a fit statistic with a p-value.
Results carry ``kind="formal"`` and must be kept distinct from the exploratory
G25/PCA fits in :mod:`strata.analysis`, which carry ``kind="exploratory"``.

The heavy lifting happens in R (``services/worker/r/*.R``) because ADMIXTOOLS 2
is an R package. This package writes a JSON spec, runs ``Rscript``, and parses
the JSON result back into pydantic models.

Typical use::

    from strata.qpadm import QpAdmSpec, qpadm_available, run_qpadm

    if qpadm_available():
        result = run_qpadm(QpAdmSpec(
            target="Denisova.DG",
            left=["Altai_Neanderthal.DG", "Vindija.DG"],
            right=["Chimp.REF", "Mbuti.DG", "Russia_Ust_Ishim.DG",
                   "Switzerland_Bichon.SG"],
            f2_dir="/path/to/f2",
        ))
        print(result.p, result.feasibility.verdict)

Environment:

* ``STRATA_RSCRIPT`` — path to the ``Rscript`` built by
  ``services/worker/r/install_env.sh``. Falls back to ``PATH``, then
  ``/opt/strata-r/bin/Rscript``, then ``~/strata-r/bin/Rscript``.
* ``STRATA_R_DIR`` — directory holding the wrapper scripts; defaults to
  ``services/worker/r`` inside the monorepo.
* ``STRATA_QPADM_TIMEOUT`` — per-call budget in seconds (default 1800).
* ``STRATA_F2_DIR`` / ``STRATA_REFERENCE_VERSION`` — the reference f2 cache
  used when a request does not name one; see :func:`default_f2_dir`.
"""

from __future__ import annotations

from .interpret import (
    P_MARGINAL,
    P_PLAUSIBLE,
    RCOND_CONCERN,
    annotate_qpadm,
    annotate_rotate_model,
    assess_fit,
    summarize_rotation,
)
from .runner import (
    QpAdmError,
    QpAdmProtocolError,
    QpAdmRunError,
    QpAdmTimeout,
    QpAdmUnavailable,
    admixtools_version,
    default_f2_dir,
    extract_f2,
    qpadm_available,
    r_script_dir,
    rscript_path,
    run_f4,
    run_qpadm,
    run_qpadm_rotate,
    run_qpwave,
)
from .types import (
    FORMAL_CAVEAT,
    ROTATION_CAVEAT,
    ExtractF2Result,
    ExtractF2Spec,
    F4Result,
    F4Row,
    F4Spec,
    Feasibility,
    PopDropRow,
    QpAdmResult,
    QpAdmRotateResult,
    QpAdmRotateSpec,
    QpAdmSpec,
    QpWaveResult,
    QpWaveSpec,
    RankDropRow,
    RotateModelResult,
    RProvenance,
    WeightRow,
)

__all__ = [
    "FORMAL_CAVEAT",
    "P_MARGINAL",
    "P_PLAUSIBLE",
    "RCOND_CONCERN",
    "ROTATION_CAVEAT",
    "ExtractF2Result",
    "ExtractF2Spec",
    "F4Result",
    "F4Row",
    "F4Spec",
    "Feasibility",
    "PopDropRow",
    "QpAdmError",
    "QpAdmProtocolError",
    "QpAdmResult",
    "QpAdmRotateResult",
    "QpAdmRotateSpec",
    "QpAdmRunError",
    "QpAdmSpec",
    "QpAdmTimeout",
    "QpAdmUnavailable",
    "QpWaveResult",
    "QpWaveSpec",
    "RProvenance",
    "RankDropRow",
    "RotateModelResult",
    "WeightRow",
    "admixtools_version",
    "annotate_qpadm",
    "annotate_rotate_model",
    "assess_fit",
    "default_f2_dir",
    "extract_f2",
    "qpadm_available",
    "r_script_dir",
    "rscript_path",
    "run_f4",
    "run_qpadm",
    "run_qpadm_rotate",
    "run_qpwave",
    "summarize_rotation",
]
