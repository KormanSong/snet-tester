"""Tests for v2 RunningStats (Welford online algorithm).

Validates incremental mean/stdev computation, edge cases
(empty, single value, constant values), and to_dict() output.
"""

import math

import pytest

from snet_tester2.state.statistics import RunningStats


def test_empty_stats():
    s = RunningStats()
    assert s.count == 0
    assert s.mean == 0.0
    assert s.stdev() is None
    assert s.min is None
    assert s.max is None


def test_single_value():
    s = RunningStats()
    s.add(5.0)
    assert s.count == 1
    assert s.mean == 5.0
    assert s.stdev() is None
    assert s.min == 5.0
    assert s.max == 5.0


def test_known_dataset():
    s = RunningStats()
    for v in [2, 4, 4, 4, 5, 5, 7, 9]:
        s.add(v)
    assert s.count == 8
    assert s.mean == pytest.approx(5.0)
    # Welford uses Bessel-corrected (sample) stdev: sqrt(m2 / (n-1))
    # Population stdev is 2.0, but sample stdev for n=8 is ~2.138
    assert s.stdev() == pytest.approx(2.138, abs=0.01)
    assert s.min == 2
    assert s.max == 9


def test_constant_values():
    s = RunningStats()
    for _ in range(100):
        s.add(5.0)
    assert s.mean == pytest.approx(5.0)
    assert s.stdev() == pytest.approx(0.0)


def test_to_dict():
    s = RunningStats()
    s.add(1.0)
    s.add(3.0)
    d = s.to_dict()
    assert set(d.keys()) == {"count", "mean", "stdev", "min", "max"}
    assert d["count"] == 2
    assert d["mean"] == pytest.approx(2.0)
