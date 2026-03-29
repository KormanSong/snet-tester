"""Real-time graph and compact metric view.

PySide6 port: import change only (PyQt5 -> PySide6).
pyqtgraph auto-detects PySide6 when it is already imported.
"""

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..protocol.codec import monitor_channel_ratio_percents
from ..protocol.convert import valve_raw_to_display
from ..protocol.constants import MAX_CHANNELS, PLACEHOLDER, SAMPLE_PERIOD_S
from ..protocol.types import IoPayload, SnetMonitorSnapshot
from .helpers import clear_layout, configure_value_label, find_optional_child, set_badge

GRAPH_REFRESH_S = 0.05
GRAPH_X_WINDOW_S = 10.0
GRAPH_PANEL_VALVE_HEIGHT = 120
PLOT_STALE_THRESHOLD_S = max(0.25, SAMPLE_PERIOD_S * 5.0)
LEFT_AXIS_WIDTH_PX = 46
LEFT_TICK_TEXT_WIDTH_PX = 36
PLOT_WIDGET_SIDE_MARGIN_PX = 0


def _patch_axis_bounding_rect(axis: pg.AxisItem) -> None:
    """Work around a pyqtgraph bug where ``boundingRect()`` ignores the
    ``hideOverlappingLabels`` margin when grid lines are enabled.

    When ``self.grid is not False`` and a linked view exists, the stock
    ``boundingRect()`` returns the union of the axis geometry and the
    linked-view rect **without** adding the label-overflow margin ``m``.
    This causes tick labels at the exact edges of the range (e.g. y=0 and
    y=5 for a range of 0-5) to be dropped by the ``br & rect != rect``
    check in ``generateDrawSpecs``.

    This patch wraps the original method so the margin adjustment is always
    applied to the returned rect.
    """
    original_boundingRect = axis.boundingRect

    def _patched_boundingRect():
        rect = original_boundingRect()
        hol = axis.style.get('hideOverlappingLabels', False)
        if hol is True or hol is False:
            return rect
        try:
            m = int(hol)
        except (TypeError, ValueError):
            return rect
        # Apply the same margin adjustments that the stock code applies on
        # the non-grid path (AxisItem.py lines 966-973), but only if the
        # grid early-return was taken (i.e. the margin is missing).
        if axis.linkedView() is not None and axis.grid is not False:
            tl = axis.style['tickLength']
            if axis.orientation == 'left':
                rect = rect.adjusted(0, -m, -min(0, tl), m)
            elif axis.orientation == 'right':
                rect = rect.adjusted(min(0, tl), -m, 0, m)
            elif axis.orientation == 'top':
                rect = rect.adjusted(-m, 0, m, -min(0, tl))
            elif axis.orientation == 'bottom':
                rect = rect.adjusted(-m, min(0, tl), m, 0)
        return rect

    axis.boundingRect = _patched_boundingRect


CHANNEL_COLORS = (
    (0, 114, 178),       # CH1: Ocean Blue     #0072B2  (Okabe-Ito)
    (193, 59, 42),       # CH2: Crimson Red    #C13B2A
    (14, 140, 89),       # CH3: Emerald Green  #0E8C59
    (213, 94, 0),        # CH4: Burnt Orange   #D55E00  (Okabe-Ito)
    (123, 45, 142),      # CH5: Royal Purple   #7B2D8E
    (166, 124, 0),       # CH6: Dark Gold      #A67C00
)


def _payload_channel_ratios(io_payload: Optional[IoPayload]) -> list[Optional[float]]:
    ratios: list[Optional[float]] = [None] * MAX_CHANNELS
    if io_payload is None:
        return ratios
    for i, ch in enumerate(io_payload.channels[:io_payload.channel_count]):
        ratios[i] = ch.ratio_percent
    return ratios


def _payload_channel_valves(snet_monitor: Optional[SnetMonitorSnapshot]) -> list[Optional[float]]:
    valves: list[Optional[float]] = [None] * MAX_CHANNELS
    if snet_monitor is None:
        return valves
    for i, ch in enumerate(snet_monitor.channels[:snet_monitor.channel_count]):
        valves[i] = valve_raw_to_display(ch.valve_raw)
    return valves


@dataclass(frozen=True)
class ChannelSummaryRow:
    channel: int
    set_percent: Optional[float]
    actual_percent: Optional[float]
    valve_volts: Optional[float]
    state_text: str


def build_channel_console_rows(
    tx_payload: Optional[IoPayload],
    rx_monitor: Optional[SnetMonitorSnapshot],
    rx_stale: bool = False,
) -> list[ChannelSummaryRow]:
    tx_count = 0 if tx_payload is None else int(tx_payload.channel_count)
    rx_count = 0 if rx_monitor is None else int(rx_monitor.channel_count)
    set_rows = _payload_channel_ratios(tx_payload)
    actual_rows = monitor_channel_ratio_percents(rx_monitor)
    valve_rows = _payload_channel_valves(rx_monitor)

    rows: list[ChannelSummaryRow] = []
    for ch in range(MAX_CHANNELS):
        if ch < tx_count:
            set_value = set_rows[ch]
            actual_value = actual_rows[ch] if ch < rx_count else None
            valve_value = valve_rows[ch] if ch < rx_count else None
            if rx_count == 0:
                state = 'SET'
            elif rx_stale:
                state = 'STALE'
            else:
                state = 'LIVE'
        else:
            set_value = None
            actual_value = None
            valve_value = None
            state = 'IDLE'

        rows.append(
            ChannelSummaryRow(
                channel=ch + 1,
                set_percent=set_value,
                actual_percent=actual_value,
                valve_volts=valve_value,
                state_text=state,
            )
        )
    return rows


class PlotTheme:
    """White Paper theme -- high contrast on white background."""

    def __init__(self):
        self.background = (242, 243, 245)         # #F2F3F5 ivory gray (ASM-inspired)
        self.valve_background = (237, 238, 241)   # #EDEEF1 slightly darker
        self.axis = (28, 31, 35)                  # #1C1F23 dark axis
        self.axis_text = (17, 17, 17)             # #111111 near-black
        self.valve_axis = (58, 63, 69)            # #3A3F45 dark gray
        self.valve_axis_text = (34, 38, 44)       # #22262C
        self.grid = (196, 202, 208)               # #C4CAD0 subtle on white
        self.valve_grid = (211, 216, 222)          # #D3D8DE lighter
        self.panel = (201, 206, 212)              # #C9CED4 gray surround

    def qcolor(self, rgb, alpha: int = 255) -> QtGui.QColor:
        return QtGui.QColor(rgb[0], rgb[1], rgb[2], alpha)

    def tx_pen(self, ch: int):
        """Setpoint: solid step-line -- reference, rendered above RX.
        2px width avoids sub-pixel aliasing that makes thin lines inconsistent."""
        return pg.mkPen(color=self.qcolor(CHANNEL_COLORS[ch], 160), width=2.0, style=QtCore.Qt.SolidLine)

    def rx_live_pen(self, ch: int):
        """Actual: solid, bold -- operator tracks this."""
        return pg.mkPen(color=self.qcolor(CHANNEL_COLORS[ch], 255), width=2.5, style=QtCore.Qt.SolidLine)

    def rx_stale_pen(self, ch: int):
        """Stale: channel color kept but faded + dashed."""
        return pg.mkPen(color=self.qcolor(CHANNEL_COLORS[ch], 70), width=2.0, style=QtCore.Qt.DashLine)

    def valve_pen(self, ch: int):
        """Valve: same color, slightly thinner and muted."""
        neutral = (100, 110, 120)
        c = CHANNEL_COLORS[ch]
        muted = (
            int(c[0] * 0.55 + neutral[0] * 0.45),
            int(c[1] * 0.55 + neutral[1] * 0.45),
            int(c[2] * 0.55 + neutral[2] * 0.45),
        )
        return pg.mkPen(color=self.qcolor(muted, 200), width=1.5, style=QtCore.Qt.SolidLine)


class PlotView:
    def __init__(
        self,
        plot_root: QtWidgets.QWidget,
        plot_host: QtWidgets.QWidget,
        toggle_buttons: dict[tuple[int, str], QtWidgets.QPushButton],
        font: QtGui.QFont,
    ):
        self._plot_root = plot_root
        self._plot_host = plot_host
        self._toggle_buttons = toggle_buttons
        self._font = QtGui.QFont(font)
        self._font.setPointSize(max(9, self._font.pointSize()))
        self._theme = PlotTheme()

        self._point_count = max(1, int(GRAPH_X_WINDOW_S / SAMPLE_PERIOD_S))
        self._x = np.arange(self._point_count, dtype=np.float32) * SAMPLE_PERIOD_S
        self._y_tx = np.full((MAX_CHANNELS, self._point_count), np.nan, dtype=np.float32)
        self._y_rx = np.full((MAX_CHANNELS, self._point_count), np.nan, dtype=np.float32)
        self._y_valve = np.full((MAX_CHANNELS, self._point_count), np.nan, dtype=np.float32)
        self._write_index = 0
        self._has_started = False
        self._last_refresh = 0.0
        self._active_tx_count = 1
        self._active_rx_count = 0
        self._running = False
        self._rx_timeouts = 0
        self._last_rx_monotonic: Optional[float] = None
        self._rx_state = 'WAIT'
        self._rx_state_tone = 'neutral'
        self._rx_stale = False

        self._applied_payload = None
        self._last_rx_monitor: Optional[SnetMonitorSnapshot] = None
        self._cached_set = [None] * MAX_CHANNELS
        self._cached_actual = [None] * MAX_CHANNELS
        self._cached_valve = [None] * MAX_CHANNELS

        self._curve_tx: list = []
        self._curve_rx: list = []
        self._curve_valve: list = []
        # Summary strip removed -- channel data shown in rxMonitorTable only

        self.plotRunValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotRunValueLabel')
        self.plotRxStateValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotRxStateValueLabel')
        self.plotSampleValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotSampleValueLabel')
        self.plotWindowValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotWindowValueLabel')
        self.plotLastUpdateValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotLastUpdateValueLabel')
        self.plotTimeoutValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotTimeoutValueLabel')

        self._apply_panel_theme()
        self._configure_status_bar()
        self._build_plots()
        self._configure_toggle_buttons()
        self._apply_curve_visibility()
        self._apply_rx_curve_style()

    def _apply_panel_theme(self):
        # plotPanel stylesheet, graphSettingsGroup stylesheet and title are set in .ui
        pass

    def _configure_status_bar(self):
        # Caption label text, font, styleSheet are set in .ui
        # Value label styleSheet and alignment are set in .ui
        # graphStatusFrame styleSheet is set in .ui

        # Dynamic initial values computed from constants
        if self.plotSampleValueLabel is not None:
            self.plotSampleValueLabel.setText(f'{SAMPLE_PERIOD_S * 1000:.0f} ms')
        if self.plotWindowValueLabel is not None:
            self.plotWindowValueLabel.setText(f'{GRAPH_X_WINDOW_S:.1f} s')
        if self.plotLastUpdateValueLabel is not None:
            self.plotLastUpdateValueLabel.setText('-- s')
        if self.plotTimeoutValueLabel is not None:
            self.plotTimeoutValueLabel.setText('0')

        if self.plotRunValueLabel is not None:
            set_badge(self.plotRunValueLabel, 'STOP', 'stop')
        if self.plotRxStateValueLabel is not None:
            set_badge(self.plotRxStateValueLabel, 'WAIT', 'neutral')

    def _build_plots(self):
        layout = self._plot_host.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(self._plot_host)
        # margins, spacing, frames, and labels are set in .ui

        # ui-override: Python 전용 위젯 (pyqtgraph PlotWidget)
        self._ratio_plot_widget = pg.PlotWidget()
        self._ratio_plot_widget.setMinimumHeight(320)
        self._ratio_plot = self._ratio_plot_widget.getPlotItem()
        self._ratio_plot_widget.setBackground(self._theme.qcolor(self._theme.background))
        self._ratio_plot_widget.setContentsMargins(PLOT_WIDGET_SIDE_MARGIN_PX, 0, PLOT_WIDGET_SIDE_MARGIN_PX, 0)
        self._ratio_plot.setMenuEnabled(False)
        self._ratio_plot_widget.setMouseEnabled(x=False, y=False)
        self._configure_ratio_plot(self._ratio_plot)
        pg.setConfigOptions(antialias=False, background=self._theme.qcolor(self._theme.background))

        for ch in range(MAX_CHANNELS):
            rx_curve = self._ratio_plot.plot(self._x, self._y_rx[ch], pen=self._theme.rx_live_pen(ch), connect='finite')
            self._curve_rx.append(rx_curve)
        # TX (setpoint) drawn after RX so step-lines render on top
        for ch in range(MAX_CHANNELS):
            tx_curve = self._ratio_plot.plot(self._x, self._y_tx[ch], pen=self._theme.tx_pen(ch),
                                             connect='finite', stepMode='left')
            self._curve_tx.append(tx_curve)

        # ui-override: Python 전용 위젯 (pyqtgraph PlotWidget)
        self._valve_plot_widget = pg.PlotWidget()
        self._valve_plot_widget.setMinimumHeight(GRAPH_PANEL_VALVE_HEIGHT)
        self._valve_plot_widget.setMouseEnabled(x=False, y=False)
        self._valve_plot_widget.setBackground(self._theme.qcolor(self._theme.valve_background))
        self._valve_plot_widget.setContentsMargins(PLOT_WIDGET_SIDE_MARGIN_PX, 0, PLOT_WIDGET_SIDE_MARGIN_PX, 0)
        self._valve_plot = self._valve_plot_widget.getPlotItem()
        self._valve_plot.setMenuEnabled(False)
        self._configure_valve_plot(self._valve_plot)
        self._valve_plot.setXLink(self._ratio_plot)
        self._synchronize_axis_geometry()
        for ch in range(MAX_CHANNELS):
            valve_curve = self._valve_plot.plot(self._x, self._y_valve[ch], pen=self._theme.valve_pen(ch), connect='finite')
            self._curve_valve.append(valve_curve)

        # Frames and labels are defined in .ui; just add plot widgets into them
        ratio_frame = find_optional_child(self._plot_host, QtWidgets.QFrame, 'ratioPlotFrame')
        valve_frame = find_optional_child(self._plot_host, QtWidgets.QFrame, 'valvePlotFrame')

        if ratio_frame is not None:
            ratio_frame.layout().addWidget(self._ratio_plot_widget, 1)
        else:
            layout.addWidget(self._ratio_plot_widget, 8)

        if valve_frame is not None:
            valve_frame.layout().addWidget(self._valve_plot_widget, 1)
        else:
            layout.addWidget(self._valve_plot_widget, 2)

        # ui-override: Designer 미지원 -- QVBoxLayout stretch는 .ui XML에 표현 불가
        layout.setStretch(0, 8)
        layout.setStretch(1, 2)
        self._ratio_plot_widget.setObjectName('ratioPlot')
        self._valve_plot_widget.setObjectName('valvePlot')
        self._refresh_summary_rows()

    def _synchronize_axis_geometry(self):
        for plot, margin in ((self._ratio_plot, 30), (self._valve_plot, 50)):
            for name in ('left', 'bottom'):
                axis = plot.getAxis(name)
                axis.setStyle(
                    autoExpandTextSpace=False,
                    tickTextOffset=8,
                    tickTextWidth=LEFT_TICK_TEXT_WIDTH_PX,
                    hideOverlappingLabels=margin,
                )
                _patch_axis_bounding_rect(axis)
            plot.getAxis('left').setWidth(LEFT_AXIS_WIDTH_PX)

    def _configure_ratio_plot(self, plot):
        # ui-override: pyqtgraph PlotItem 내부 마진
        plot.layout.setContentsMargins(0, 4, 0, 4)
        plot.showAxis('right')
        right_axis = plot.getAxis('right')
        right_axis.setWidth(LEFT_AXIS_WIDTH_PX)
        right_axis.setStyle(showValues=False)
        right_axis.setPen(pg.mkPen(color=self._theme.qcolor(self._theme.axis), width=1.0))
        plot.showGrid(x=True, y=True, alpha=0.25)
        plot.setXRange(0.0, GRAPH_X_WINDOW_S, padding=0.0)
        plot.setYRange(0.0, 100.0, padding=0.0)
        plot.disableAutoRange()
        plot.setMouseEnabled(x=False, y=False)
        plot.hideButtons()
        # Fixed ticks -- single level so all grid lines have uniform weight
        plot.getAxis('left').setTicks([
            [(v, str(int(v))) for v in range(0, 101, 20)],
        ])
        plot.getAxis('bottom').setTicks([
            [(v, str(int(v))) for v in range(0, 11, 2)],
        ])
        for name in ('left', 'bottom'):
            axis = plot.getAxis(name)
            axis.setPen(pg.mkPen(color=self._theme.qcolor(self._theme.axis), width=1.0))
            axis.setTextPen(pg.mkPen(color=self._theme.qcolor(self._theme.axis_text), width=1.0))
            axis.setTickFont(self._font)

    def _configure_valve_plot(self, plot):
        # ui-override: pyqtgraph PlotItem 내부 마진
        plot.layout.setContentsMargins(0, 4, 0, 4)
        plot.showAxis('right')
        right_axis = plot.getAxis('right')
        right_axis.setWidth(LEFT_AXIS_WIDTH_PX)
        right_axis.setStyle(showValues=False)
        right_axis.setPen(pg.mkPen(color=self._theme.qcolor(self._theme.valve_axis), width=1.0))
        plot.showGrid(x=True, y=True, alpha=0.15)
        plot.setXRange(0.0, GRAPH_X_WINDOW_S, padding=0.0)
        plot.setYRange(0.0, 5.0, padding=0.0)
        plot.disableAutoRange()
        plot.setMouseEnabled(x=False, y=False)
        plot.hideButtons()
        # Fixed ticks -- single level so all grid lines have uniform weight
        plot.getAxis('left').setTicks([
            [(v, str(v)) for v in range(0, 6)],
        ])
        plot.getAxis('bottom').setTicks([
            [(v, str(int(v))) for v in range(0, 11, 2)],
        ])
        valve_tick_font = QtGui.QFont(self._font)
        valve_tick_font.setPointSize(max(8, self._font.pointSize() - 1))
        for name in ('left', 'bottom'):
            axis = plot.getAxis(name)
            axis.setPen(pg.mkPen(color=self._theme.qcolor(self._theme.valve_axis), width=1.0))
            axis.setTextPen(pg.mkPen(color=self._theme.qcolor(self._theme.valve_axis_text), width=1.0))
            axis.setTickFont(valve_tick_font)

    def _configure_toggle_buttons(self):
        for i, color in enumerate(CHANNEL_COLORS, start=1):
            tx_btn = self._toggle_buttons[(i - 1, 'tx')]
            rx_btn = self._toggle_buttons[(i - 1, 'rx')]
            self._configure_toggle_button(tx_btn, color)
            self._configure_toggle_button(rx_btn, color)
            tx_btn.toggled.connect(lambda _checked: self._apply_curve_visibility())
            rx_btn.toggled.connect(lambda _checked: self._apply_curve_visibility())

    def _configure_toggle_button(self, button: QtWidgets.QPushButton, color):
        # ui-dynamic: 채널색(Okabe-Ito)은 런타임 계산 -- checkable/checked/height/font/base style은 .ui에서 설정
        # setStyleSheet() replaces (not merges), so read the .ui base stylesheet
        # and substitute the neutral gray placeholder with the actual channel color.
        dim = (
            max(145, min(230, int((color[0] * 0.45) + 125))),
            max(145, min(230, int((color[1] * 0.45) + 125))),
            max(145, min(230, int((color[2] * 0.45) + 125))),
        )
        base_ss = button.styleSheet()
        # Replace placeholder border-left in unchecked state (first occurrence)
        # and checked state (second occurrence)
        placeholder = 'border-left: 3px solid rgb(200, 200, 200)'
        dim_border = f'border-left: 3px solid rgb({dim[0]}, {dim[1]}, {dim[2]})'
        full_border = f'border-left: 3px solid rgb({color[0]}, {color[1]}, {color[2]})'
        # First occurrence = QPushButton (unchecked) -> dim color
        # Second occurrence = QPushButton:checked -> full color
        first_pos = base_ss.find(placeholder)
        if first_pos >= 0:
            second_pos = base_ss.find(placeholder, first_pos + len(placeholder))
            if second_pos >= 0:
                # Replace second (checked) first to preserve positions
                base_ss = base_ss[:second_pos] + full_border + base_ss[second_pos + len(placeholder):]
            # Replace first (unchecked)
            base_ss = base_ss[:first_pos] + dim_border + base_ss[first_pos + len(placeholder):]
        # ui-dynamic: .ui base stylesheet에서 채널색 플레이스홀더 치환
        button.setStyleSheet(base_ss)

    def _apply_curve_visibility(self):
        for ch in range(MAX_CHANNELS):
            tx_vis = ch < self._active_tx_count and self._toggle_buttons[(ch, 'tx')].isChecked()
            rx_vis = ch < self._active_rx_count and self._toggle_buttons[(ch, 'rx')].isChecked()
            self._curve_tx[ch].setVisible(tx_vis)
            self._curve_rx[ch].setVisible(rx_vis)
            self._curve_valve[ch].setVisible(rx_vis)

    def _apply_rx_curve_style(self):
        for ch in range(MAX_CHANNELS):
            pen = self._theme.rx_stale_pen(ch) if self._rx_stale else self._theme.rx_live_pen(ch)
            self._curve_rx[ch].setPen(pen)

    def _set_rx_state(self, text: str, tone: str):
        self._rx_state = text
        self._rx_state_tone = tone
        if self.plotRxStateValueLabel is not None:
            set_badge(self.plotRxStateValueLabel, text, tone)

    def _format_numeric(self, value: Optional[float], fmt: str) -> str:
        if value is None:
            return PLACEHOLDER
        return fmt.format(value)

    def _refresh_summary_rows(
        self,
        tx_payload: Optional[IoPayload] = None,
        rx_monitor: Optional[SnetMonitorSnapshot] = None,
        rx_stale: bool = False,
    ):
        payload = tx_payload if tx_payload is not None else self._applied_payload
        rows = build_channel_console_rows(payload, rx_monitor, rx_stale=rx_stale)
        for row in rows:
            self._cached_set[row.channel - 1] = row.set_percent
            self._cached_actual[row.channel - 1] = row.actual_percent
            self._cached_valve[row.channel - 1] = row.valve_volts

    def note_applied_payload(self, payload: Optional[IoPayload]):
        self._applied_payload = payload
        tx_count = 0 if payload is None else int(payload.channel_count)
        self._active_tx_count = max(0, min(MAX_CHANNELS, tx_count))
        self._update_summary_from_payload(self._applied_payload, self._last_rx_monitor, self._rx_stale)
        self._apply_curve_visibility()

    def note_rx_timeout(self):
        self._rx_timeouts += 1
        self._rx_stale = True
        self._last_rx_monotonic = None
        self._apply_rx_curve_style()
        self._set_rx_state('STALE', 'warn')
        self._update_summary_from_payload(self._applied_payload, self._last_rx_monitor, rx_stale=True)
        if self.plotTimeoutValueLabel is not None:
            self.plotTimeoutValueLabel.setText(str(self._rx_timeouts))

    def note_rx_monitor(self, rx_monitor: Optional[SnetMonitorSnapshot]):
        if rx_monitor is None:
            self.note_rx_timeout()
            return

        self._active_rx_count = max(0, min(MAX_CHANNELS, int(rx_monitor.channel_count)))
        self._last_rx_monitor = rx_monitor
        self._last_rx_monotonic = time.perf_counter()
        self._rx_stale = False
        self._apply_rx_curve_style()
        self._set_rx_state('LIVE', 'ok')
        self._update_summary_from_payload(self._applied_payload, rx_monitor, rx_stale=False)
        self._apply_curve_visibility()

    def _update_summary_from_payload(
        self,
        tx_payload: Optional[IoPayload],
        rx_monitor: Optional[SnetMonitorSnapshot],
        rx_stale: bool,
    ):
        self._refresh_summary_rows(tx_payload, rx_monitor, rx_stale=rx_stale)

    def set_series_counts(self, tx_count: Optional[int] = None, rx_count: Optional[int] = None):
        if tx_count is not None:
            self._active_tx_count = max(0, min(MAX_CHANNELS, int(tx_count)))
        if rx_count is not None:
            self._active_rx_count = max(0, min(MAX_CHANNELS, int(rx_count)))
        self._apply_curve_visibility()

    def set_run_state(self, running: bool):
        self._running = running
        if self.plotRunValueLabel is not None:
            set_badge(self.plotRunValueLabel, 'GO' if running else 'STOP', 'run' if running else 'stop')
        if not running and self._rx_state not in ('STALE', 'TIMEOUT'):
            self._set_rx_state('WAIT', 'neutral')

    def add_point(self, tx_payload: Optional[IoPayload], rx_monitor: Optional[SnetMonitorSnapshot]):
        if self._has_started and self._write_index == 0:
            self._y_tx.fill(np.nan)
            self._y_rx.fill(np.nan)
            self._y_valve.fill(np.nan)

        tx_ratios = _payload_channel_ratios(tx_payload)
        rx_ratios = monitor_channel_ratio_percents(rx_monitor)
        valve_values = _payload_channel_valves(rx_monitor)

        self.set_series_counts(
            tx_count=tx_payload.channel_count if tx_payload is not None else 0,
            rx_count=rx_monitor.channel_count if rx_monitor is not None else 0,
        )

        for ch in range(MAX_CHANNELS):
            self._y_tx[ch, self._write_index] = np.nan if tx_ratios[ch] is None else np.float32(tx_ratios[ch])
            self._y_rx[ch, self._write_index] = np.nan if rx_ratios[ch] is None else np.float32(rx_ratios[ch])
            self._y_valve[ch, self._write_index] = np.nan if valve_values[ch] is None else np.float32(valve_values[ch])

        self._write_index = (self._write_index + 1) % self._point_count
        self._has_started = True
        self._update_summary_from_payload(tx_payload, rx_monitor, self._rx_stale)

    def _update_status_age(self, now: float):
        if self._last_rx_monotonic is None:
            return
        age_s = max(0.0, now - self._last_rx_monotonic)
        if self._running and age_s >= PLOT_STALE_THRESHOLD_S and self._rx_state == 'LIVE':
            self._rx_stale = True
            self._apply_rx_curve_style()
            self._set_rx_state('STALE', 'warn')
            self._update_summary_from_payload(self._applied_payload, self._last_rx_monitor, rx_stale=True)

    def refresh(self, force: bool = False):
        now = time.perf_counter()
        self._update_status_age(now)
        if not force and (now - self._last_refresh) < GRAPH_REFRESH_S:
            return

        for ch in range(MAX_CHANNELS):
            if self._curve_tx[ch].isVisible():
                self._curve_tx[ch].setData(self._x, self._y_tx[ch], connect='finite', stepMode='left')
            if self._curve_rx[ch].isVisible():
                self._curve_rx[ch].setData(self._x, self._y_rx[ch], connect='finite')
            if self._curve_valve[ch].isVisible():
                self._curve_valve[ch].setData(self._x, self._y_valve[ch], connect='finite')
        self._last_refresh = now
