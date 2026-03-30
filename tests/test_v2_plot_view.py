"""Tests for snet_tester2 PlotView: leading edge, hold+ramp, wrap, throttle, grid style."""

import time
from unittest.mock import patch

import numpy as np
import pyqtgraph as pg
import pytest
from PySide6 import QtCore
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton
from PySide6.QtGui import QFont, QPen

from snet_tester2.protocol.codec import build_io_payload_model
from snet_tester2.protocol.constants import MAX_CHANNELS, SAMPLE_PERIOD_S
from snet_tester2.protocol.convert import ratio_percent_to_raw
from snet_tester2.protocol.types import SnetChannelMonitor, SnetMonitorSnapshot
from snet_tester2.views.plot_view import GRAPH_REFRESH_S, RAMP_FRAC_RX, PlotView


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


# -- Test 2: TX step / RX+Valve ramp separation in setData --

def test_tx_step_rx_ramp_in_set_data(qapp):
    """TX curves use stepMode='left'; RX/Valve curves do not (hold+ramp)."""
    pv = _make_plot_view(qapp)
    payload = build_io_payload_model(1, [30.0])
    monitor = _make_monitor([30.0])
    pv.add_point(payload, monitor)

    tx_calls, rx_calls, valve_calls = [], [], []

    def make_capture(target_list):
        def capture(*args, **kwargs):
            target_list.append(kwargs)
        return capture

    for ch_curves, target in ((pv._curve_tx, tx_calls), (pv._curve_rx, rx_calls), (pv._curve_valve, valve_calls)):
        for curve in ch_curves:
            if curve.isVisible():
                curve.setData = make_capture(target)

    pv.refresh(force=True)

    # TX: stepMode='left' must be present
    assert len(tx_calls) > 0, "TX curves should have been updated"
    for kw in tx_calls:
        assert kw.get('stepMode') == 'left', f"TX should have stepMode='left': {kw}"
        assert kw.get('connect') == 'finite', f"TX connect='finite' missing: {kw}"

    # RX: no stepMode
    assert len(rx_calls) > 0, "RX curves should have been updated"
    for kw in rx_calls:
        assert 'stepMode' not in kw, f"RX should not have stepMode: {kw}"
        assert kw.get('connect') == 'finite', f"RX connect='finite' missing: {kw}"

    # Valve: no stepMode
    assert len(valve_calls) > 0, "Valve curves should have been updated"
    for kw in valve_calls:
        assert 'stepMode' not in kw, f"Valve should not have stepMode: {kw}"
        assert kw.get('connect') == 'finite', f"Valve connect='finite' missing: {kw}"


# -- Test 2b: Ramp points inserted between differing values --

def test_ramp_points_inserted(qapp):
    pv = _make_plot_view(qapp)
    payload1 = build_io_payload_model(1, [50.0])
    monitor1 = _make_monitor([50.0])
    payload2 = build_io_payload_model(1, [70.0])
    monitor2 = _make_monitor([70.0])

    t0 = 1000.0
    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t0):
        pv.add_point(payload1, monitor1)
    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t0 + 0.05):
        pv.add_point(payload2, monitor2)

    # _write_index == 2, so 2 original points -> 3 expanded + 1 leading edge = 4
    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t0 + 0.06):
        x, y = pv._build_display_data(pv._y_rx, 0)

    # Expected: (x0, 50), (x1 - ramp_d, 50), (x1, 70), (leading_x, 70)
    assert len(x) == 4, f"expected 4 points (2 orig + 1 hold + 1 lead), got {len(x)}"
    # Point 0: first sample
    assert y[0] == pytest.approx(50.0, abs=0.1)
    # Point 1: hold end-point (previous value held)
    assert y[1] == pytest.approx(50.0, abs=0.1)
    ramp_duration = SAMPLE_PERIOD_S * RAMP_FRAC_RX
    assert x[1] == pytest.approx(x[2] - ramp_duration, abs=1e-4)
    # Point 2: ramp end = new value
    assert y[2] == pytest.approx(70.0, abs=0.1)
    # Point 3: leading edge (extends last value)
    assert y[3] == pytest.approx(70.0, abs=0.1)
    assert x[3] > x[2], "leading edge should extend beyond last sample"


# -- Test 2c: TX step mode returns raw + leading edge, no hold points --

def test_tx_step_no_ramp_expansion(qapp):
    """TX step mode: _build_display_data(step=True) returns raw + leading edge, no hold points."""
    pv = _make_plot_view(qapp)
    payload1 = build_io_payload_model(1, [50.0])
    monitor1 = _make_monitor([50.0])
    payload2 = build_io_payload_model(1, [70.0])
    monitor2 = _make_monitor([70.0])

    t0 = 1000.0
    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t0):
        pv.add_point(payload1, monitor1)
    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t0 + 0.05):
        pv.add_point(payload2, monitor2)

    with patch('snet_tester2.views.plot_view.time.perf_counter', return_value=t0 + 0.06):
        x, y = pv._build_display_data(pv._y_tx, 0, step=True)

    # 2 raw points + 1 leading edge = 3 (no hold point inserted)
    assert len(x) == 3, f"expected 3 points (2 raw + 1 lead), got {len(x)}"
    assert y[0] == pytest.approx(50.0, abs=0.1)
    assert y[1] == pytest.approx(70.0, abs=0.1)
    assert y[2] == pytest.approx(70.0, abs=0.1)  # leading edge
    assert x[2] > x[1], "leading edge should extend beyond last sample"


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


# -- Test 6: Y-axis padding (ratio -5~105, valve -0.25~5.25) --

def test_ratio_y_range_has_padding(qapp):
    pv = _make_plot_view(qapp)
    y_range = pv._ratio_plot.viewRange()[1]
    assert y_range[0] == pytest.approx(-5.0), f"ratio Y min should be -5.0, got {y_range[0]}"
    assert y_range[1] == pytest.approx(105.0), f"ratio Y max should be 105.0, got {y_range[1]}"


def test_valve_y_range_has_padding(qapp):
    pv = _make_plot_view(qapp)
    y_range = pv._valve_plot.viewRange()[1]
    assert y_range[0] == pytest.approx(-0.25), f"valve Y min should be -0.25, got {y_range[0]}"
    assert y_range[1] == pytest.approx(5.25), f"valve Y max should be 5.25, got {y_range[1]}"


# -- Test 7: Two-tier dotted grid lines (InfiniteLine) --

def test_ratio_grid_major_and_minor_exist(qapp):
    """Verify ratio plot has both major (10%) and minor (2%) grid lines."""
    pv = _make_plot_view(qapp)
    grid_lines = [
        item for item in pv._ratio_plot.items
        if isinstance(item, pg.InfiniteLine) and item.zValue() == -100
    ]
    # Major Y: 0,10,20,...,100 = 11 lines + X: 0,2,4,6,8,10 = 6 lines = 17
    # Minor Y: 2,4,6,8,12,14,...,98 = 40 lines (every 2% excluding 10% multiples)
    # Total = 57
    assert len(grid_lines) == 57, f"expected 57 grid lines (17 major + 40 minor), got {len(grid_lines)}"


def test_valve_grid_exists(qapp):
    """Verify valve plot has grid lines."""
    pv = _make_plot_view(qapp)
    grid_lines = [
        item for item in pv._valve_plot.items
        if isinstance(item, pg.InfiniteLine) and item.zValue() == -100
    ]
    # Y: 0,1,2,3,4,5 = 6 + X: 0,2,4,6,8,10 = 6 = 12
    assert len(grid_lines) == 12, f"expected 12 grid lines, got {len(grid_lines)}"


def test_grid_pen_style_is_custom_dash(qapp):
    """Verify all grid lines use CustomDashLine pen style."""
    pv = _make_plot_view(qapp)
    grid_lines = [
        item for item in pv._ratio_plot.items
        if isinstance(item, pg.InfiniteLine) and item.zValue() == -100
    ]
    for line in grid_lines:
        pen = line.pen
        assert pen.style() == QtCore.Qt.PenStyle.CustomDashLine, (
            f"grid line pen should be CustomDashLine, got {pen.style()}"
        )
