"""Tests for snet_tester2 PlotView: raw rolling samples and batched redraw."""

from unittest.mock import patch

import numpy as np
import pyqtgraph as pg
import pytest
from PySide6 import QtCore
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from snet_tester2.protocol.codec import build_io_payload_model
from snet_tester2.protocol.constants import MAX_CHANNELS
from snet_tester2.protocol.convert import ratio_percent_to_raw, valve_raw_to_display
from snet_tester2.protocol.types import SnetChannelMonitor, SnetMonitorSnapshot
from snet_tester2.views.plot_view import PlotView, TX_RENDER_INTERVAL


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_monitor(ratios: list[float], valve_raws: list[int] | None = None) -> SnetMonitorSnapshot:
    if valve_raws is None:
        valve_raws = [0] * len(ratios)
    channels = tuple(
        SnetChannelMonitor(
            ad_raw=0,
            flow_raw=0,
            ratio_raw=ratio_percent_to_raw(ratio),
            valve_raw=valve_raw,
        )
        for ratio, valve_raw in zip(ratios, valve_raws)
    )
    return SnetMonitorSnapshot(
        status=0,
        mode=0,
        pressure_raw=0,
        temperature_raw=0,
        channel_count=len(channels),
        channels=channels,
    )


def _make_plot_view(qapp) -> PlotView:
    root = QWidget()
    host = QWidget()
    host.setLayout(QVBoxLayout())
    toggle_buttons = {}
    for ch in range(MAX_CHANNELS):
        for kind in ("tx", "rx"):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setChecked(True)
            toggle_buttons[(ch, kind)] = btn
    return PlotView(root, host, toggle_buttons, QFont())


def test_first_sample_is_visible_immediately(qapp):
    pv = _make_plot_view(qapp)

    pv.add_point(build_io_payload_model(1, [42.0]), _make_monitor([42.0]))

    x, y = pv._build_display_data(pv._y_rx, 0)
    assert len(x) == 1
    assert y[0] == pytest.approx(42.0, abs=0.1)


def test_progressive_fill_uses_raw_arrival_order(qapp):
    pv = _make_plot_view(qapp)
    values = [10.0, 20.0, 35.0]

    for value in values:
        pv.add_point(build_io_payload_model(1, [value]), _make_monitor([value]))

    x, y = pv._build_display_data(pv._y_rx, 0)
    assert len(x) == len(values)
    assert list(y) == pytest.approx(values, abs=0.1)


def test_wrap_clears_window_and_restarts_from_new_cycle(qapp):
    pv = _make_plot_view(qapp)
    for value in range(pv._point_count):
        ratio = value * 0.25
        pv.add_point(build_io_payload_model(1, [ratio]), _make_monitor([ratio]))

    x_full, y_full = pv._build_display_data(pv._y_rx, 0)
    assert len(x_full) == pv._point_count
    assert y_full[0] == pytest.approx(0.0, abs=0.1)
    assert y_full[-1] == pytest.approx((pv._point_count - 1) * 0.25, abs=0.1)

    pv.add_point(build_io_payload_model(1, [99.0]), _make_monitor([99.0]))

    x, y = pv._build_display_data(pv._y_rx, 0)
    assert len(x) == 1
    assert y[0] == pytest.approx(99.0, abs=0.1)


def test_tx_step_rx_and_valve_refresh_use_expected_curve_modes(qapp):
    pv = _make_plot_view(qapp)
    payload = build_io_payload_model(1, [30.0])
    monitor = _make_monitor([30.0], [1000])
    pv.note_rx_monitor(monitor)
    pv.add_point(payload, monitor)
    pv.set_valve_plot_visible(True)

    tx_calls, rx_calls, valve_calls = [], [], []

    def capture(target):
        def inner(*args, **kwargs):
            target.append(kwargs)
        return inner

    for curve in pv._curve_tx:
        if curve.isVisible():
            curve.setData = capture(tx_calls)
    for curve in pv._curve_rx:
        if curve.isVisible():
            curve.setData = capture(rx_calls)
    for curve in pv._curve_valve:
        if curve.isVisible():
            curve.setData = capture(valve_calls)

    pv.refresh(force=True)

    assert tx_calls
    for kwargs in tx_calls:
        assert kwargs.get("stepMode") == "left"
        assert kwargs.get("connect") == "finite"

    assert rx_calls
    for kwargs in rx_calls:
        assert kwargs.get("connect") == "finite"
        assert "stepMode" not in kwargs

    assert valve_calls
    for kwargs in valve_calls:
        assert kwargs.get("connect") == "finite"
        assert "stepMode" not in kwargs


def test_rx_and_valve_use_raw_samples_without_interpolation(qapp):
    pv = _make_plot_view(qapp)
    ratios = [50.0, 70.0]
    valve_raws = [1000, 2000]

    for ratio, valve_raw in zip(ratios, valve_raws):
        pv.add_point(build_io_payload_model(1, [ratio]), _make_monitor([ratio], [valve_raw]))

    x_rx, y_rx = pv._build_display_data(pv._y_rx, 0)
    x_valve, y_valve = pv._build_display_data(pv._y_valve, 0)

    assert len(x_rx) == 2
    assert len(x_valve) == 2
    assert list(y_rx) == pytest.approx(ratios, abs=0.1)
    assert list(y_valve) == pytest.approx(
        [valve_raw_to_display(value) for value in valve_raws],
        abs=0.001,
    )


def test_inactive_channel_stays_nan_without_hiding_graph(qapp):
    pv = _make_plot_view(qapp)
    pv.add_point(build_io_payload_model(1, [25.0]), _make_monitor([25.0]))

    x0, y0 = pv._build_display_data(pv._y_rx, 0)
    x1, y1 = pv._build_display_data(pv._y_rx, 1)

    assert len(x0) == 1
    assert y0[0] == pytest.approx(25.0, abs=0.1)
    assert len(x1) == 1
    assert np.isnan(y1[0])


def test_timeout_sample_does_not_hide_existing_rx_curves(qapp):
    pv = _make_plot_view(qapp)
    pv.note_rx_monitor(_make_monitor([25.0]))

    pv.add_point(build_io_payload_model(1, [25.0]), None)

    assert pv._active_rx_count == 1
    assert pv._curve_rx[0].isVisible() is True


def test_refresh_skips_when_no_new_sample(qapp):
    pv = _make_plot_view(qapp)
    pv.note_rx_monitor(_make_monitor([10.0]))
    pv.add_point(build_io_payload_model(1, [10.0]), _make_monitor([10.0]))

    call_count = 0
    original_set_data = pv._curve_rx[0].setData

    def counting_set_data(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        original_set_data(*args, **kwargs)

    pv._curve_rx[0].setData = counting_set_data

    t = 2000.0
    with patch("snet_tester2.views.plot_view.time.perf_counter", return_value=t):
        pv.refresh()
    assert call_count == 1

    with patch("snet_tester2.views.plot_view.time.perf_counter", return_value=t + 0.005):
        pv.refresh()
    assert call_count == 1

    with patch("snet_tester2.views.plot_view.time.perf_counter", return_value=t + 0.010):
        pv.refresh()
    assert call_count == 1

    pv.add_point(build_io_payload_model(1, [999.0]), _make_monitor([999.0]))
    # With timer-only pacing, new sample should render even on a very short delta.
    with patch("snet_tester2.views.plot_view.time.perf_counter", return_value=t + 0.011):
        pv.refresh()
    assert call_count == 2


def test_atomic_commit_updates_all_visible_channels_in_single_refresh(qapp):
    pv = _make_plot_view(qapp)
    ratios = [10.0, 20.0, 30.0, 40.0, 50.0]
    payload = build_io_payload_model(5, ratios)
    monitor = _make_monitor(ratios, [500, 900, 1300, 1700, 2100])
    pv.note_rx_monitor(monitor)
    pv.note_applied_payload(payload)
    pv.add_point(payload, monitor)
    pv.set_valve_plot_visible(True)

    tick_calls: list[tuple[str, int]] = []
    for ch in range(5):
        pv._curve_tx[ch].setData = (lambda c: (lambda *args, **kwargs: tick_calls.append(("tx", c))))(ch)
        pv._curve_rx[ch].setData = (lambda c: (lambda *args, **kwargs: tick_calls.append(("rx", c))))(ch)
        pv._curve_valve[ch].setData = (lambda c: (lambda *args, **kwargs: tick_calls.append(("valve", c))))(ch)

    did_work = pv.refresh()
    assert did_work is True

    channels_touched = sorted({ch for _kind, ch in tick_calls})
    assert channels_touched == [0, 1, 2, 3, 4]
    for ch in channels_touched:
        kinds = {kind for kind, idx in tick_calls if idx == ch}
        assert kinds == {"tx", "rx"}


def test_latest_only_commit_skips_older_unrendered_serial(qapp):
    pv = _make_plot_view(qapp)
    ratios_a = [10.0, 20.0, 30.0, 40.0, 50.0]
    ratios_b = [11.0, 21.0, 31.0, 41.0, 51.0]
    monitor_a = _make_monitor(ratios_a, [500, 900, 1300, 1700, 2100])
    monitor_b = _make_monitor(ratios_b, [550, 950, 1350, 1750, 2150])
    pv.note_rx_monitor(monitor_b)

    pv.add_point(build_io_payload_model(5, ratios_a), monitor_a)
    serial_a = pv._sample_serial
    pv.add_point(build_io_payload_model(5, ratios_b), monitor_b)
    serial_b = pv._sample_serial

    # Only one refresh occurs; it should commit the latest serial.
    assert serial_b == serial_a + 1
    assert pv.refresh() is True
    assert pv._last_rendered_sample_serial == serial_b

    x, y = pv._build_display_data(pv._y_rx, 0)
    assert len(x) == 2
    assert y[-1] == pytest.approx(ratios_b[0], abs=0.1)


def test_setdata_counters_track_per_channel_calls(qapp):
    pv = _make_plot_view(qapp)
    ratios = [10.0, 20.0, 30.0, 40.0, 50.0]
    payload = build_io_payload_model(5, ratios)
    monitor = _make_monitor(ratios, [500, 900, 1300, 1700, 2100])
    pv.note_rx_monitor(monitor)
    pv.note_applied_payload(payload)
    pv.add_point(payload, monitor)
    pv.set_valve_plot_visible(True)
    pv.reset_setdata_counters()

    assert pv.refresh(force=True) is True
    counts = pv.snapshot_setdata_counters()

    assert counts["tx"][:5] == (1, 1, 1, 1, 1)
    assert counts["rx"][:5] == (1, 1, 1, 1, 1)
    assert counts["valve"][:5] == (1, 1, 1, 1, 1)
    assert counts["tx"][5] == 0
    assert counts["rx"][5] == 0
    assert counts["valve"][5] == 0

    assert pv.refresh() is False
    assert pv.snapshot_setdata_counters() == counts


def test_phase_b_defers_valve_then_flushes_next_tick(qapp):
    pv = _make_plot_view(qapp)
    ratios = [10.0, 20.0, 30.0, 40.0, 50.0]
    payload = build_io_payload_model(5, ratios)
    monitor = _make_monitor(ratios, [500, 900, 1300, 1700, 2100])
    pv.note_rx_monitor(monitor)
    pv.note_applied_payload(payload)
    pv.add_point(payload, monitor)
    pv.set_valve_plot_visible(True)
    pv.set_render_budget_ms(1.0)  # force Valve defer on this tick
    pv.reset_load_shed_counters()

    tx_calls, rx_calls, valve_calls = [], [], []

    def capture(target):
        def inner(*args, **kwargs):
            target.append(kwargs)
        return inner

    for curve in pv._curve_tx:
        if curve.isVisible():
            curve.setData = capture(tx_calls)
    for curve in pv._curve_rx:
        if curve.isVisible():
            curve.setData = capture(rx_calls)
    for curve in pv._curve_valve:
        if curve.isVisible():
            curve.setData = capture(valve_calls)

    # Tick 1: core (TX/RX) only, Valve deferred.
    assert pv.refresh() is True
    assert tx_calls
    assert rx_calls
    assert valve_calls == []
    shed1 = pv.snapshot_load_shed_counters()
    assert shed1["valve_deferred"] == pytest.approx(1.0)
    assert shed1["valve_dropped"] == pytest.approx(0.0)

    # Tick 2: no new sample, deferred Valve flushes.
    pv.set_render_budget_ms(100.0)
    assert pv.refresh() is False  # data-frame unchanged; Valve-only work
    assert valve_calls
    shed2 = pv.snapshot_load_shed_counters()
    assert shed2["valve_rendered"] == pytest.approx(1.0)


def test_phase_b_drops_stale_deferred_valve_on_new_sample(qapp):
    pv = _make_plot_view(qapp)
    ratios_a = [10.0, 20.0, 30.0, 40.0, 50.0]
    ratios_b = [11.0, 21.0, 31.0, 41.0, 51.0]
    monitor_a = _make_monitor(ratios_a, [500, 900, 1300, 1700, 2100])
    monitor_b = _make_monitor(ratios_b, [550, 950, 1350, 1750, 2150])
    pv.note_rx_monitor(monitor_a)
    pv.set_valve_plot_visible(True)
    pv.reset_load_shed_counters()

    pv.add_point(build_io_payload_model(5, ratios_a), monitor_a)
    pv.set_render_budget_ms(1.0)
    assert pv.refresh() is True  # defer Valve for serial A

    pv.add_point(build_io_payload_model(5, ratios_b), monitor_b)
    shed = pv.snapshot_load_shed_counters()
    assert shed["valve_dropped"] == pytest.approx(1.0)


def test_tx_updates_only_every_render_interval_samples(qapp):
    pv = _make_plot_view(qapp)
    ratios = [10.0, 20.0, 30.0, 40.0, 50.0]
    payload = build_io_payload_model(5, ratios)
    monitor = _make_monitor(ratios, [500, 900, 1300, 1700, 2100])
    pv.note_rx_monitor(monitor)
    pv.set_valve_plot_visible(False)
    pv.add_point(payload, monitor)
    assert pv.refresh() is True

    tx_calls = []
    for curve in pv._curve_tx:
        if curve.isVisible():
            curve.setData = (lambda target: (lambda *args, **kwargs: target.append(kwargs)))(tx_calls)

    for _ in range(TX_RENDER_INTERVAL - 1):
        pv.add_point(payload, monitor)
        assert pv.refresh() is True
    assert tx_calls == []

    pv.add_point(payload, monitor)
    assert pv.refresh() is True
    assert tx_calls
    shed = pv.snapshot_load_shed_counters()
    assert shed["tx_deferred"] == pytest.approx(0.0)
    assert shed["tx_rendered"] == pytest.approx(0.0)


def test_tx_setdata_payload_uses_sample_history_not_two_point_line(qapp):
    pv = _make_plot_view(qapp)
    ratios = [20.0, 40.0, 60.0, 80.0, 100.0]
    payload = build_io_payload_model(5, ratios)
    monitor = _make_monitor(ratios, [500, 900, 1300, 1700, 2100])
    pv.note_rx_monitor(monitor)
    pv.set_valve_plot_visible(False)
    pv.add_point(payload, monitor)

    captured: list[tuple[tuple, dict]] = []
    original_set_data = pv._curve_tx[0].setData

    def capture_set_data(*args, **kwargs):
        captured.append((args, kwargs))
        return original_set_data(*args, **kwargs)

    pv._curve_tx[0].setData = capture_set_data
    assert pv.refresh() is True
    assert captured
    args, kwargs = captured[-1]
    x_d = args[0]
    y_d = args[1]
    assert kwargs.get("stepMode") == "left"
    assert len(x_d) >= 1
    assert len(y_d) >= 1


def test_tx_remains_sample_truth_without_applied_overlay_history(qapp):
    pv = _make_plot_view(qapp)
    payload_10 = build_io_payload_model(5, [10.0, 20.0, 30.0, 40.0, 50.0])
    payload_20 = build_io_payload_model(5, [20.0, 20.0, 30.0, 40.0, 50.0])
    payload_30 = build_io_payload_model(5, [30.0, 20.0, 30.0, 40.0, 50.0])
    monitor_10 = _make_monitor([10.0, 20.0, 30.0, 40.0, 50.0], [500, 900, 1300, 1700, 2100])
    monitor_30 = _make_monitor([30.0, 20.0, 30.0, 40.0, 50.0], [550, 950, 1350, 1750, 2150])
    pv.note_rx_monitor(monitor_10)
    pv.set_valve_plot_visible(False)
    pv.note_applied_payload(payload_10)
    pv.add_point(payload_10, monitor_10)
    assert pv.refresh() is True

    # Applied payload changes without an accompanying sample should not alter TX graph.
    pv.note_applied_payload(payload_20)
    pv.note_applied_payload(payload_30)
    assert pv.refresh() is False
    _x0, y0 = pv._build_display_data(pv._y_tx, 0, step=True)
    assert y0[-1] == pytest.approx(10.0, abs=0.01)

    # TX graph changes only when a sample carrying that TX value arrives.
    pv.add_point(payload_30, monitor_30)
    assert pv.refresh() is True
    _x1, y1 = pv._build_display_data(pv._y_tx, 0, step=True)
    assert y1[-1] == pytest.approx(30.0, abs=0.01)


def test_ratio_y_range_has_padding(qapp):
    pv = _make_plot_view(qapp)
    y_range = pv._ratio_plot.viewRange()[1]
    assert y_range[0] == pytest.approx(-5.0)
    assert y_range[1] == pytest.approx(105.0)


def test_valve_y_range_has_padding(qapp):
    pv = _make_plot_view(qapp)
    y_range = pv._valve_plot.viewRange()[1]
    assert y_range[0] == pytest.approx(-0.25)
    assert y_range[1] == pytest.approx(5.25)


def test_valve_plot_visible_by_default_and_toggleable(qapp):
    pv = _make_plot_view(qapp)

    assert pv.valve_plot_visible() is True
    assert pv._valve_container.isHidden() is False

    pv.set_valve_plot_visible(False)

    assert pv.valve_plot_visible() is False
    assert pv._valve_container.isHidden() is True


def test_ratio_grid_major_only_by_default(qapp):
    pv = _make_plot_view(qapp)
    grid_lines = [
        item for item in pv._ratio_plot.items
        if isinstance(item, pg.InfiniteLine) and item.zValue() == -100
    ]
    assert len(grid_lines) == 17


def test_valve_grid_exists(qapp):
    pv = _make_plot_view(qapp)
    grid_lines = [
        item for item in pv._valve_plot.items
        if isinstance(item, pg.InfiniteLine) and item.zValue() == -100
    ]
    assert len(grid_lines) == 12


def test_grid_pen_style_is_custom_dash(qapp):
    pv = _make_plot_view(qapp)
    grid_lines = [
        item for item in pv._ratio_plot.items
        if isinstance(item, pg.InfiniteLine) and item.zValue() == -100
    ]
    for line in grid_lines:
        pen = line.pen
        assert pen.style() == QtCore.Qt.PenStyle.CustomDashLine


def test_set_sample_period_resets_buffers(qapp):
    pv = _make_plot_view(qapp)
    pv.add_point(build_io_payload_model(1, [25.0]), _make_monitor([25.0]))

    pv.set_sample_period_s(0.1)

    assert pv.sample_period_s() == pytest.approx(0.1)
    assert pv._write_index == 0
    assert pv._has_started is False
    assert pv._sample_serial == 0
    assert pv._point_count == 100
    assert pv._x[1] == pytest.approx(0.1)
