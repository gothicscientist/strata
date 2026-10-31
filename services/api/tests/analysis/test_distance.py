from __future__ import annotations

import numpy as np
import pytest

from strata.analysis.distance import distances, nearest
from strata.analysis.types import CoordinateTable


def _table():
    return CoordinateTable(
        space="g25", names=["a", "b", "c"], matrix=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 3.0]])
    )


def test_nearest_euclidean_ranked():
    res = nearest(np.array([0.9, 0.0]), _table(), k=2)
    assert [n.name for n in res.neighbors] == ["b", "a"]
    assert res.neighbors[0].distance == pytest.approx(0.1)
    assert res.space == "g25" and res.neighbors[0].rank == 1


def test_weighted_metric_changes_order():
    t = np.array([0.9, 2.0])
    assert nearest(t, _table(), k=1).neighbors[0].name == "c"
    w = nearest(t, _table(), k=1, metric="weighted", weights=np.array([10.0, 0.01]))
    assert w.neighbors[0].name == "b"


def test_other_metrics_and_exclude():
    t = np.array([1.0, 0.0])
    d = distances(t, _table().matrix, metric="manhattan")
    np.testing.assert_allclose(d, [1, 0, 4])
    res = nearest(t, _table(), k=3, exclude=["b"], metric="cosine")
    assert [n.name for n in res.neighbors] == ["a", "c"]  # a: cos 0 -> 1, c: orthogonal -> 1
    with pytest.raises(ValueError):
        distances(t, _table().matrix, metric="weighted")
