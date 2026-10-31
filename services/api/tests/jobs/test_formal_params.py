"""qpAdm parameter handling that does not need R: data-source restrictions and group-id
mapping against the SYNTHETIC reference library."""

from __future__ import annotations

import pytest
from api.support import build_synthetic_reference, env_for, reset_platform_caches

from strata.jobs.handlers import _data_source, _to_group_ids
from strata.jobs.queue import PermanentJobError


class _Mod:
    def __init__(self, f2):
        self._f2 = f2

    def default_f2_dir(self):
        return self._f2


def test_data_source_requires_reference_cache():
    with pytest.raises(PermanentJobError, match="no reference f2 cache"):
        _data_source(_Mod(None), {})
    assert _data_source(_Mod("/srv/f2"), {}) == {"f2_dir": "/srv/f2"}
    with pytest.raises(PermanentJobError):
        _data_source(_Mod("/srv/f2"), {"f2_dir": "/etc"})
    with pytest.raises(PermanentJobError):
        _data_source(_Mod("/srv/f2"), {"geno_prefix": "/home/x"})


def test_group_id_mapping(monkeypatch, tmp_path):
    import pandas as pd

    root = build_synthetic_reference(tmp_path / "derived")
    df = pd.read_parquet(root / "populations.parquet")
    df["group_id"] = [f"{p}.SG" for p in df["id"]]
    df.to_parquet(root / "populations.parquet")
    for k, v in env_for(tmp_path, root).items():
        monkeypatch.setenv(k, v)
    reset_platform_caches()
    args = {"target": "PopA", "left": ["PopB", "Mbuti.DG"], "right": ["PopC"]}
    mapping = _to_group_ids(args)
    assert args == {"target": "PopA.SG", "left": ["PopB.SG", "Mbuti.DG"], "right": ["PopC.SG"]}
    assert mapping == {"PopA": "PopA.SG", "PopB": "PopB.SG", "PopC": "PopC.SG"}
    reset_platform_caches()
