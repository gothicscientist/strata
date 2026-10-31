"""Shared constants for the ADMIXTOOLS 2 tests.

A plain module rather than `conftest.py` so the test modules can import it
directly; `tests/` has no `__init__.py`, so relative imports are unavailable.
"""

from __future__ import annotations

import pytest

from strata.qpadm import qpadm_available

# The seven populations in admixtools::example_f2_blocks. Real data: archaic
# hominins, Mbuti, Chimp and three Palaeolithic modern humans. These are the
# package's demonstration populations and say nothing about South Asia.
EXAMPLE_POPS = (
    "Altai_Neanderthal.DG",
    "Chimp.REF",
    "Denisova.DG",
    "Mbuti.DG",
    "Russia_Ust_Ishim.DG",
    "Switzerland_Bichon.SG",
    "Vindija.DG",
)

# The qpAdm model from ADMIXTOOLS 2's own documentation.
EXAMPLE_TARGET = "Denisova.DG"
EXAMPLE_LEFT = ["Altai_Neanderthal.DG", "Vindija.DG"]
EXAMPLE_RIGHT = [
    "Chimp.REF",
    "Mbuti.DG",
    "Russia_Ust_Ishim.DG",
    "Switzerland_Bichon.SG",
]

requires_r = pytest.mark.skipif(
    not qpadm_available(),
    reason="R with ADMIXTOOLS 2 is not available; run services/worker/r/install_env.sh",
)
