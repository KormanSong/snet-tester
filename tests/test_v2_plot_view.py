"""Tests for snet_tester2 PlotView: leading edge, step mode, wrap, throttle."""

import time
from unittest.mock import patch

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton
from PySide6.QtGui import QFont

from snet_tester2.protocol.codec import build_io_payload_model
from snet_tester2.protocol.constants import MAX_CHANNELS, SAMPLE_PERIOD_S
from snet_tester2.protocol.convert import ratio_percent_to_raw
from snet_tester2.protocol.types import SnetChannelMonitor, SnetMonitorSnapshot
from snet_tester2.views.plot_view import GRAPH_REFRESH_S, PlotView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_monitor(ratios: list[float], valve_raws: list[int] | None = None) -> SnetMonitorSnapshot:
    if valve_raws is None:
        valve_raws = [0] * len(ratios)
    channels = tuple(
        SnetChannelMonitor(
            ad_raw=0, flow_raw=0,
            ratio_raw=ratio_percent_to_raw(r),
            valve_raw=v,
        )
        for r, v in zip(ratios, valve_raws)
    )
    return SnetMonitorSnapshot(
        status=0, mode=0, pressure_raw=0, temperature_raw=0,
        channel_count=len(channels), channels=channels,
    )


def _make_plot_view(qapp) -> PlotView:
    """Create a PlotView with minimal real Qt widgets."""
    root = QWidget()
    host = QWidget()
    host.setLayout(QVBoxLayout())
    toggle_buttons = {}
    for ch in range(MAX_CHANNELS):
        for kind in ('tx', 'rx'):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setChecked(True)
            toggle_buttons[(ch, kind)] = btn
    pv = PlotView(root, host, toggle_buttons, QFont())
    return pv


# -- Test 1: Leading edge advances between samples --

def test_leading_edge_advances(qapp):
    pv = _make_plot_view(qapp)
    payload = build_io_payload_model(1, [50.0])
    monitor = _make_monitor([50.0])

    t0 = 1000.0
    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t0):
        pv.add_point(payload, monitor)

    # First call: shortly after sample
    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t0 + 0.01):
        x1, y1 = pv._build_display_data(pv._y_rx, 0)

    # Second call: later
    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t0 + 0.03):
        x2, y2 = pv._build_display_data(pv._y_rx, 0)

    assert len(x1) == pv._write_index + 1, "should have data + 1 leading edge point"
    assert len(y1) == len(x1)
    assert x2[-1] > x1[-1], "leading edge x should advance with time"
    assert y1[-1] == pytest.approx(50.0, abs=0.1), "leading edge y extends last value"
    assert y2[-1] == pytest.approx(50.0, abs=0.1)


# -- Test 2: stepMode='left' passed to setData --

def test_step_mode_in_set_data(qapp):
    pv = _make_plot_view(qapp)
    payload = build_io_payload_model(1, [30.0])
    monitor = _make_monitor([30.0])
    pv.add_point(payload, monitor)

    calls = []

    def capture_set_data(*args, **kwargs):
        calls.append(kwargs)

    # Patch setData on all visible curves
    for curve_list in (pv._curve_tx, pv._curve_rx, pv._curve_valve):
        for curve in curve_list:
            if curve.isVisible():
                curve.setData = capture_set_data

    pv.refresh(force=True)

    assert len(calls) > 0, "at least one curve should have been updated"
    for kw in calls:
        assert kw.get('stepMode') == 'left', f"stepMode='left' missing: {kw}"
        assert kw.get('connect') == 'finite', f"connect='finite' missing: {kw}"


# -- Test 3: Wrap boundary isolation --

def test_wrap_boundary_no_cross_cycle(qapp):
    pv = _make_plot_view(qapp)
    payload = build_io_payload_model(1, [40.0])
    monitor = _make_monitor([40.0])

    # Fill buffer completely: last add_point writes at index _point_count-1,
    # then _write_index wraps to 0.  Buffer is NOT cleared until the NEXT add_point.
    for _ in range(pv._point_count):
        pv.add_point(payload, monitor)

    assert pv._write_index == 0
    assert pv._has_started is True

    # _write_index == 0 → no leading edge, return full arrays unchanged
    x, y = pv._build_display_data(pv._y_rx, 0)
    assert len(x) == pv._point_count
    assert len(x) == len(pv._x)

    # Now add one more point (triggers clear + write at index 0)
    pv.add_point(payload, monitor)
    assert pv._write_index == 1

    x2, y2 = pv._build_display_data(pv._y_rx, 0)
    assert len(x2) == 2, "1 data point + 1 leading edge after wrap"
    assert x2[0] == pytest.approx(0.0), "first point at x=0"


# -- Test 4: NaN channel skips leading edge --

def test_nan_channel_no_leading_edge(qapp):
    pv = _make_plot_view(qapp)
    # Add a point with 1 active channel (ch0 has data, ch1..5 are NaN)
    payload = build_io_payload_model(1, [25.0])
    monitor = _make_monitor([25.0])
    pv.add_point(payload, monitor)

    n = pv._write_index  # should be 1

    # Channel 0 has data -> leading edge appended
    x0, y0 = pv._build_display_data(pv._y_rx, 0)
    assert len(x0) == n + 1

    # Channel 1 has NaN -> no leading edge
    x1, y1 = pv._build_display_data(pv._y_rx, 1)
    assert len(x1) == n, "NaN channel should not get leading edge"


# -- Test 5: Refresh throttle respects GRAPH_REFRESH_S --

def test_refresh_throttle(qapp):
    pv = _make_plot_view(qapp)
    payload = build_io_payload_model(1, [10.0])
    monitor = _make_monitor([10.0])
    pv.add_point(payload, monitor)

    call_count = 0
    original_set_data = pv._curve_rx[0].setData

    def counting_set_data(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        original_set_data(*args, **kwargs)

    pv._curve_rx[0].setData = counting_set_data

    t = 2000.0
    # First refresh: should trigger
    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t):
        pv.refresh()
    assert call_count == 1

    # Second refresh within throttle window: should skip
    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t + 0.005):
        pv.refresh()
    assert call_count == 1, "should be throttled"

    # Third refresh after throttle window: should trigger
    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t + GRAPH_REFRESH_S + 0.001):
        pv.refresh()
    assert call_count == 2, "should refresh after throttle period"
