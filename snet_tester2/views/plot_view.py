"""Real-time graph and compact metric view.

PySide6 port: import change only (PyQt5 -> PySide6).
pyqtgraph auto-detects PySide6 when it is already imported.
"""

import time
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..protocol.codec import monitor_channel_ratio_percents
from ..protocol.convert import valve_raw_to_display
from ..protocol.constants import MAX_CHANNELS, SAMPLE_PERIOD_S
from ..protocol.types import IoPayload, SnetMonitorSnapshot
from .helpers import find_optional_child, set_badge

GRAPH_X_WINDOW_S = 10.0
GRAPH_PANEL_VALVE_HEIGHT = 120
RAMP_FRAC_RX = 0.0  # interpolation disabled: render raw received samples only
DEFAULT_MINOR_GRID_ENABLED = False
LEFT_AXIS_WIDTH_PX = 46
LEFT_TICK_TEXT_WIDTH_PX = 36
PLOT_WIDGET_SIDE_MARGIN_PX = 0
LOAD_SHED_HEADROOM_MS = 1.0
TX_RENDER_INTERVAL = 1
TX_SEGMENTED_LINE_MODE = 'on'
VALVE_SEGMENTED_LINE_MODE = 'on'


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


def _add_grid_lines(
    plot: pg.PlotItem,
    y_ticks: list[float],
    x_ticks: list[float],
    color: QtGui.QColor,
    dash_pattern: list[float],
) -> list[pg.InfiniteLine]:
    """Add grid lines as InfiniteLine items directly on the plot.

    Bypasses pyqtgraph's built-in showGrid (which renders solid lines via
    QPicture cache) and draws grid lines with explicit pen control.
    Returns the list of created lines for future reference or removal.
    """
    # ui-dynamic: InfiniteLine 격자 -- pyqtgraph showGrid 대체
    grid_pen = pg.mkPen(color=color, width=1.0, style=QtCore.Qt.PenStyle.CustomDashLine)
    grid_pen.setDashPattern(dash_pattern)
    lines: list[pg.InfiniteLine] = []
    for y_val in y_ticks:
        line = pg.InfiniteLine(pos=y_val, angle=0, pen=grid_pen)
        line.setZValue(-100)  # behind data curves
        plot.addItem(line)
        lines.append(line)
    for x_val in x_ticks:
        line = pg.InfiniteLine(pos=x_val, angle=90, pen=grid_pen)
        line.setZValue(-100)
        plot.addItem(line)
        lines.append(line)
    return lines


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


class PlotTheme:
    """White Paper theme -- high contrast on white background."""

    def __init__(self):
        self.background = (242, 243, 245)         # #F2F3F5 ivory gray (ASM-inspired)
        self.valve_background = (237, 238, 241)   # #EDEEF1 slightly darker
        self.axis = (28, 31, 35)                  # #1C1F23 dark axis
        self.axis_text = (17, 17, 17)             # #111111 near-black
        self.valve_axis = (58, 63, 69)            # #3A3F45 dark gray
        self.valve_axis_text = (34, 38, 44)       # #22262C
        self.grid_major = (168, 176, 184)            # #A8B0B8 major grid (10%)
        self.grid_minor = (206, 211, 216)            # #CED3D8 minor grid (2%)
        self.grid = (196, 202, 208)                  # #C4CAD0 (legacy / valve major)
        self.valve_grid = (211, 216, 222)            # #D3D8DE lighter
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

        self._sample_period_s = SAMPLE_PERIOD_S
        self._minor_grid_enabled = DEFAULT_MINOR_GRID_ENABLED
        self._point_count = 0
        self._x = np.empty(0, dtype=np.float32)
        self._y_tx = np.empty((MAX_CHANNELS, 0), dtype=np.float32)
        self._y_rx = np.empty((MAX_CHANNELS, 0), dtype=np.float32)
        self._y_valve = np.empty((MAX_CHANNELS, 0), dtype=np.float32)
        self._write_index = 0
        self._has_started = False
        self._sample_serial = 0
        self._last_rendered_sample_serial = -1
        self._pending_render_sample_serial = -1
        self._last_tx_render_serial = -TX_RENDER_INTERVAL
        self._pending_valve_sample_serial = -1
        self._last_valve_rendered_sample_serial = -1
        self._render_budget_ms = 1000.0 / 60.0
        self._valve_render_cost_ema_ms = 2.0
        self._load_shed_stats = {
            'tx_deferred': 0,
            'tx_dropped': 0,
            'tx_rendered': 0,
            'tx_force_immediate': 0,
            'valve_deferred': 0,
            'valve_dropped': 0,
            'valve_rendered': 0,
        }
        self._setdata_counts = {
            'tx': [0] * MAX_CHANNELS,
            'rx': [0] * MAX_CHANNELS,
            'valve': [0] * MAX_CHANNELS,
        }
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
        self._ratio_minor_grid_lines: list[pg.InfiniteLine] = []
        self._valve_plot_visible = True

        self._curve_tx: list = []
        self._curve_rx: list = []
        self._curve_valve: list = []
        self._valve_container: Optional[QtWidgets.QWidget] = None
        # Summary strip removed -- channel data shown in rxMonitorTable only

        self.plotRunValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotRunValueLabel')
        self.plotRxStateValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotRxStateValueLabel')
        self.plotSampleValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotSampleValueLabel')
        self.plotWindowValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotWindowValueLabel')
        self.plotLastUpdateValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotLastUpdateValueLabel')
        self.plotTimeoutValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotTimeoutValueLabel')

        self._apply_panel_theme()
        self._configure_status_bar()
        self._reset_buffers()
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
            self.plotSampleValueLabel.setText(f'{self._sample_period_s * 1000:.0f} ms')
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

        _empty_x = np.empty(0, dtype=np.float32)
        _empty_y = np.empty(0, dtype=np.float32)
        # ui-override: PlotCurveItem 직접 사용 -- PlotDataItem 래퍼(ScatterPlotItem 포함) 오버헤드 제거
        for ch in range(MAX_CHANNELS):
            rx_curve = pg.PlotCurveItem(_empty_x, _empty_y, pen=self._theme.rx_live_pen(ch), connect='finite')
            self._ratio_plot.addItem(rx_curve)
            self._curve_rx.append(rx_curve)
        # TX (setpoint) drawn after RX so step-lines render on top
        for ch in range(MAX_CHANNELS):
            tx_curve = pg.PlotCurveItem(_empty_x, _empty_y, pen=self._theme.tx_pen(ch),
                                        connect='finite', stepMode='left')
            tx_curve.setSegmentedLineMode(TX_SEGMENTED_LINE_MODE)
            self._ratio_plot.addItem(tx_curve)
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
        # ui-override: PlotCurveItem 직접 사용 -- PlotDataItem 래퍼 오버헤드 제거
        for ch in range(MAX_CHANNELS):
            valve_curve = pg.PlotCurveItem(_empty_x, _empty_y, pen=self._theme.valve_pen(ch), connect='finite')
            valve_curve.setSegmentedLineMode(VALVE_SEGMENTED_LINE_MODE)
            self._valve_plot.addItem(valve_curve)
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
            self._valve_container = valve_frame
        else:
            layout.addWidget(self._valve_plot_widget, 2)
            self._valve_container = self._valve_plot_widget

        # ui-override: Designer 미지원 -- QVBoxLayout stretch는 .ui XML에 표현 불가
        layout.setStretch(0, 8)
        layout.setStretch(1, 2)
        self._ratio_plot_widget.setObjectName('ratioPlot')
        self._valve_plot_widget.setObjectName('valvePlot')
        if self._valve_container is not None:
            self._valve_container.setVisible(self._valve_plot_visible)

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
        # ui-dynamic: 2단 격자 -- major(10%), minor(2%)
        _add_grid_lines(
            plot,
            y_ticks=[float(v) for v in range(0, 101, 10)],
            x_ticks=[float(v) for v in range(0, 11, 2)],
            color=self._theme.qcolor(self._theme.grid_major),
            dash_pattern=[2, 4],
        )
        self._ratio_minor_grid_lines = []
        if self._minor_grid_enabled:
            self._ratio_minor_grid_lines = _add_grid_lines(
                plot,
                y_ticks=[float(v) for v in range(0, 101, 2) if v % 10 != 0],
                x_ticks=[],
                color=self._theme.qcolor(self._theme.grid_minor),
                dash_pattern=[1, 4],
            )
        plot.setXRange(0.0, GRAPH_X_WINDOW_S, padding=0.0)
        plot.setYRange(-5.0, 105.0, padding=0.0)
        plot.disableAutoRange()
        plot.setMouseEnabled(x=False, y=False)
        plot.hideButtons()
        # Tick labels at 20% intervals (major grid is denser than labels)
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
        # ui-dynamic: valve 격자 -- major(1V)
        _add_grid_lines(
            plot,
            y_ticks=[float(v) for v in range(0, 6)],
            x_ticks=[float(v) for v in range(0, 11, 2)],
            color=self._theme.qcolor(self._theme.grid_major),
            dash_pattern=[2, 4],
        )
        plot.setXRange(0.0, GRAPH_X_WINDOW_S, padding=0.0)
        plot.setYRange(-0.25, 5.25, padding=0.0)
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
            self._curve_valve[ch].setVisible(self._valve_plot_visible and rx_vis)

    def _apply_rx_curve_style(self):
        for ch in range(MAX_CHANNELS):
            pen = self._theme.rx_stale_pen(ch) if self._rx_stale else self._theme.rx_live_pen(ch)
            self._curve_rx[ch].setPen(pen)

    def _set_rx_state(self, text: str, tone: str):
        self._rx_state = text
        self._rx_state_tone = tone
        if self.plotRxStateValueLabel is not None:
            set_badge(self.plotRxStateValueLabel, text, tone)

    def note_applied_payload(self, payload: Optional[IoPayload]):
        self._applied_payload = payload
        tx_count = 0 if payload is None else int(payload.channel_count)
        self._active_tx_count = max(0, min(MAX_CHANNELS, tx_count))
        self._apply_curve_visibility()

    def note_rx_timeout(self):
        self._rx_timeouts += 1
        self._rx_stale = True
        self._last_rx_monotonic = None
        self._apply_rx_curve_style()
        self._set_rx_state('STALE', 'warn')
        if self.plotTimeoutValueLabel is not None:
            self.plotTimeoutValueLabel.setText(str(self._rx_timeouts))

    def note_rx_monitor(self, rx_monitor: Optional[SnetMonitorSnapshot]):
        if rx_monitor is None:
            self.note_rx_timeout()
            return

        new_count = max(0, min(MAX_CHANNELS, int(rx_monitor.channel_count)))
        count_changed = new_count != self._active_rx_count
        was_stale = self._rx_stale

        self._active_rx_count = new_count
        self._last_rx_monitor = rx_monitor
        self._last_rx_monotonic = time.perf_counter()
        self._rx_stale = False

        # ui-override: state transition guard -- 매 샘플 setPen/setVisible/setText 호출 제거
        if was_stale:
            self._apply_rx_curve_style()
        if self._rx_state != 'LIVE':
            self._set_rx_state('LIVE', 'ok')
        if count_changed:
            self._apply_curve_visibility()

    def set_series_counts(self, tx_count: Optional[int] = None, rx_count: Optional[int] = None):
        next_tx_count = self._active_tx_count
        next_rx_count = self._active_rx_count
        if tx_count is not None:
            next_tx_count = max(0, min(MAX_CHANNELS, int(tx_count)))
        if rx_count is not None:
            next_rx_count = max(0, min(MAX_CHANNELS, int(rx_count)))
        if next_tx_count == self._active_tx_count and next_rx_count == self._active_rx_count:
            return
        self._active_tx_count = next_tx_count
        self._active_rx_count = next_rx_count
        self._apply_curve_visibility()

    def _stale_threshold_s(self) -> float:
        return max(0.25, self._sample_period_s * 5.0)

    def _reset_buffers(self):
        self._point_count = max(1, int(GRAPH_X_WINDOW_S / self._sample_period_s))
        self._x = np.arange(self._point_count, dtype=np.float32) * self._sample_period_s
        self._clear_cycle_buffers()

    def _clear_cycle_buffers(self):
        self._y_tx = np.full((MAX_CHANNELS, self._point_count), np.nan, dtype=np.float32)
        self._y_rx = np.full((MAX_CHANNELS, self._point_count), np.nan, dtype=np.float32)
        self._y_valve = np.full((MAX_CHANNELS, self._point_count), np.nan, dtype=np.float32)
        self._write_index = 0
        self._has_started = False
        self._sample_serial = 0
        self._last_rendered_sample_serial = -1
        self._pending_render_sample_serial = -1
        self._last_tx_render_serial = -TX_RENDER_INTERVAL
        self._pending_valve_sample_serial = -1
        self._last_valve_rendered_sample_serial = -1

    def reset_setdata_counters(self):
        for key in ('tx', 'rx', 'valve'):
            for ch in range(MAX_CHANNELS):
                self._setdata_counts[key][ch] = 0

    def reset_load_shed_counters(self):
        for key in (
            'tx_deferred',
            'tx_dropped',
            'tx_rendered',
            'tx_force_immediate',
            'valve_deferred',
            'valve_dropped',
            'valve_rendered',
        ):
            self._load_shed_stats[key] = 0

    def snapshot_setdata_counters(self) -> dict[str, tuple[int, ...]]:
        return {
            'tx': tuple(self._setdata_counts['tx']),
            'rx': tuple(self._setdata_counts['rx']),
            'valve': tuple(self._setdata_counts['valve']),
        }

    def snapshot_load_shed_counters(self) -> dict[str, float]:
        return {
            'tx_deferred': float(self._load_shed_stats['tx_deferred']),
            'tx_dropped': float(self._load_shed_stats['tx_dropped']),
            'tx_rendered': float(self._load_shed_stats['tx_rendered']),
            'tx_force_immediate': float(self._load_shed_stats['tx_force_immediate']),
            'tx_render_cost_ema_ms': 0.0,
            'valve_deferred': float(self._load_shed_stats['valve_deferred']),
            'valve_dropped': float(self._load_shed_stats['valve_dropped']),
            'valve_rendered': float(self._load_shed_stats['valve_rendered']),
            'valve_render_cost_ema_ms': float(self._valve_render_cost_ema_ms),
        }

    def snapshot_channel_sync_skew(self) -> dict[str, int]:
        def _series_skew(curves: list, key: str) -> int:
            visible_counts = [self._setdata_counts[key][ch] for ch in range(MAX_CHANNELS) if curves[ch].isVisible()]
            if len(visible_counts) <= 1:
                return 0
            return max(visible_counts) - min(visible_counts)

        return {
            'tx': _series_skew(self._curve_tx, 'tx'),
            'rx': _series_skew(self._curve_rx, 'rx'),
            'valve': _series_skew(self._curve_valve, 'valve'),
        }

    def set_sample_period_s(self, sample_period_s: float):
        self._sample_period_s = max(0.001, float(sample_period_s))
        self._reset_buffers()
        if self.plotSampleValueLabel is not None:
            self.plotSampleValueLabel.setText(f'{self._sample_period_s * 1000:.0f} ms')

    def sample_period_s(self) -> float:
        return self._sample_period_s

    def set_minor_grid_enabled(self, enabled: bool):
        self._minor_grid_enabled = bool(enabled)
        for line in self._ratio_minor_grid_lines:
            line.setVisible(self._minor_grid_enabled)

    def minor_grid_enabled(self) -> bool:
        return self._minor_grid_enabled

    def set_valve_plot_visible(self, visible: bool):
        self._valve_plot_visible = bool(visible)
        if not self._valve_plot_visible:
            self._pending_valve_sample_serial = -1
        elif self._last_rendered_sample_serial > self._last_valve_rendered_sample_serial:
            self._pending_valve_sample_serial = self._last_rendered_sample_serial
        if self._valve_container is not None:
            self._valve_container.setVisible(self._valve_plot_visible)
        self._apply_curve_visibility()

    def valve_plot_visible(self) -> bool:
        return self._valve_plot_visible

    def set_run_state(self, running: bool):
        self._running = running
        if self.plotRunValueLabel is not None:
            set_badge(self.plotRunValueLabel, 'GO' if running else 'STOP', 'run' if running else 'stop')
        if not running and self._rx_state not in ('STALE', 'TIMEOUT'):
            self._set_rx_state('WAIT', 'neutral')

    def set_render_budget_ms(self, budget_ms: float):
        self._render_budget_ms = max(1.0, float(budget_ms))

    def add_point(
        self,
        tx_payload: Optional[IoPayload],
        rx_monitor: Optional[SnetMonitorSnapshot],
        *,
        arrival_monotonic_s: Optional[float] = None,
    ):
        if self._has_started and self._write_index == 0:
            # User-preferred static mode: each 10-second window is an independent batch.
            self._clear_cycle_buffers()

        tx_ratios = _payload_channel_ratios(tx_payload)
        rx_ratios = monitor_channel_ratio_percents(rx_monitor)
        valve_values = _payload_channel_valves(rx_monitor)

        for ch in range(MAX_CHANNELS):
            self._y_tx[ch, self._write_index] = np.nan if tx_ratios[ch] is None else np.float32(tx_ratios[ch])
            self._y_rx[ch, self._write_index] = np.nan if rx_ratios[ch] is None else np.float32(rx_ratios[ch])
            self._y_valve[ch, self._write_index] = np.nan if valve_values[ch] is None else np.float32(valve_values[ch])

        self._write_index = (self._write_index + 1) % self._point_count
        self._has_started = True
        self._sample_serial += 1
        # Phase B policy:
        # - Always store every raw sample into the ring buffers.
        # - If a newer sample arrives before a deferred Valve render is committed,
        #   drop only that deferred Valve render (stale visual work), not raw data.
        if (
            self._pending_valve_sample_serial > self._last_valve_rendered_sample_serial
            and self._pending_valve_sample_serial < self._sample_serial
        ):
            self._load_shed_stats['valve_dropped'] += 1
            self._pending_valve_sample_serial = -1
        self._pending_render_sample_serial = self._sample_serial

    def _update_status_age(self, now: float):
        if self._last_rx_monotonic is None:
            return
        age_s = max(0.0, now - self._last_rx_monotonic)
        if self._running and age_s >= self._stale_threshold_s() and self._rx_state == 'LIVE':
            self._rx_stale = True
            self._apply_rx_curve_style()
            self._set_rx_state('STALE', 'warn')

    def _display_sample_count(self) -> int:
        """Return the number of raw received samples currently visible."""
        if not self._has_started:
            return 0
        return min(self._sample_serial, self._point_count)

    def _ordered_channel_values(self, y_buf: np.ndarray, ch: int, count: int) -> np.ndarray:
        """Return channel values in display order for the current static cycle."""
        if count <= 0:
            return y_buf[ch, :0]
        # Static 10-second mode clears buffers at cycle boundary, so visible
        # samples are always contiguous from index 0.
        return y_buf[ch, :count]

    def _build_display_data(self, y_buf: np.ndarray, ch: int, *, step: bool = False):
        """Return raw received samples only, with no hiding or interpolation."""
        n = self._display_sample_count()
        if n <= 0:
            return self._x[:0], y_buf[ch, :0]
        return self._x[:n], self._ordered_channel_values(y_buf, ch, n)

    def refresh(self, force: bool = False):
        now = time.perf_counter()
        self._update_status_age(now)
        has_pending_core = self._pending_render_sample_serial > self._last_rendered_sample_serial
        has_pending_valve = (
            self._valve_plot_visible
            and self._pending_valve_sample_serial > self._last_valve_rendered_sample_serial
        )
        if not force and not has_pending_core and not has_pending_valve:
            return False
        if self._sample_serial <= 0:
            return False

        frame_start = time.perf_counter()
        target_serial = self._pending_render_sample_serial
        did_work = False
        core_updated = force or has_pending_core
        self._ratio_plot_widget.setUpdatesEnabled(False)
        self._valve_plot_widget.setUpdatesEnabled(False)
        try:
            if force or has_pending_core:
                tx_due = force or ((self._sample_serial - self._last_tx_render_serial) >= TX_RENDER_INTERVAL)
                if tx_due:
                    tx_rendered = False
                    for ch in range(MAX_CHANNELS):
                        if self._curve_tx[ch].isVisible():
                            x_d, y_d = self._build_display_data(self._y_tx, ch, step=True)
                            self._curve_tx[ch].setData(x_d, y_d, connect='finite', stepMode='left')
                            self._setdata_counts['tx'][ch] += 1
                            did_work = True
                            tx_rendered = True
                    if tx_rendered:
                        self._last_tx_render_serial = self._sample_serial
                for ch in range(MAX_CHANNELS):
                    if self._curve_rx[ch].isVisible():
                        x_d, y_d = self._build_display_data(self._y_rx, ch)
                        self._curve_rx[ch].setData(x_d, y_d, connect='finite')
                        self._setdata_counts['rx'][ch] += 1
                        did_work = True
                if core_updated and self._valve_plot_visible:
                    self._pending_valve_sample_serial = target_serial

            valve_pending = force or (
                self._valve_plot_visible
                and self._pending_valve_sample_serial > self._last_valve_rendered_sample_serial
            )
            if valve_pending:
                # Priority policy:
                # TX/RX updates always win on the same tick. Valve work is pushed
                # to the next render tick, then rendered only if budget allows.
                if core_updated and not force:
                    self._load_shed_stats['valve_deferred'] += 1
                else:
                    elapsed_ms = (time.perf_counter() - frame_start) * 1000.0
                    remaining_ms = self._render_budget_ms - elapsed_ms - LOAD_SHED_HEADROOM_MS
                    valve_budget_needed = max(0.5, self._valve_render_cost_ema_ms * 1.1)
                    should_render_valve = force or (remaining_ms >= valve_budget_needed)
                    if should_render_valve:
                        valve_start = time.perf_counter()
                        valve_did_work = False
                        valve_serial = self._pending_valve_sample_serial
                        for ch in range(MAX_CHANNELS):
                            if self._curve_valve[ch].isVisible():
                                x_d, y_d = self._build_display_data(self._y_valve, ch)
                                self._curve_valve[ch].setData(x_d, y_d, connect='finite')
                                self._setdata_counts['valve'][ch] += 1
                                did_work = True
                                valve_did_work = True
                        if valve_did_work:
                            valve_cost_ms = (time.perf_counter() - valve_start) * 1000.0
                            self._valve_render_cost_ema_ms = (
                                self._valve_render_cost_ema_ms * 0.8
                                + valve_cost_ms * 0.2
                            )
                            self._last_valve_rendered_sample_serial = max(
                                self._last_valve_rendered_sample_serial,
                                valve_serial,
                            )
                            self._pending_valve_sample_serial = -1
                            self._load_shed_stats['valve_rendered'] += 1
                    else:
                        self._load_shed_stats['valve_deferred'] += 1
        finally:
            self._ratio_plot_widget.setUpdatesEnabled(True)
            self._valve_plot_widget.setUpdatesEnabled(True)
            if did_work:
                self._ratio_plot_widget.viewport().update()
                self._valve_plot_widget.viewport().update()

        # latest-only gate: if a newer sample arrived before commit ends,
        # leave the newer serial pending for the next render tick.
        if core_updated and target_serial == self._pending_render_sample_serial:
            self._last_rendered_sample_serial = target_serial
        return core_updated
