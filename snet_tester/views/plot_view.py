"""Real-time plot view using pyqtgraph."""

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

from ..protocol.codec import monitor_channel_ratio_percents
from ..protocol.constants import MAX_CHANNELS, PLACEHOLDER, SAMPLE_PERIOD_S
from ..protocol.types import IoPayload, SnetMonitorSnapshot
from .helpers import (
    attach_widget,
    configure_value_label,
    find_optional_child,
    set_badge,
)

GRAPH_REFRESH_S = 0.05
GRAPH_X_WINDOW_S = 10.0
PLOT_STALE_THRESHOLD_S = max(0.25, SAMPLE_PERIOD_S * 5.0)

CHANNEL_COLORS = (
    (33, 150, 243),
    (231, 76, 60),
    (46, 204, 113),
    (243, 156, 18),
    (26, 188, 156),
    (155, 89, 182),
)


def _payload_channel_ratios(io_payload: Optional[IoPayload]) -> list[Optional[float]]:
    ratios: list[Optional[float]] = [None] * MAX_CHANNELS
    if io_payload is None:
        return ratios
    for i, ch in enumerate(io_payload.channels[:io_payload.channel_count]):
        ratios[i] = ch.ratio_percent
    return ratios


@dataclass(frozen=True)
class PlotTheme:
    background: tuple[int, int, int] = (5, 8, 10)
    axis: tuple[int, int, int] = (107, 122, 140)
    axis_text: tuple[int, int, int] = (148, 158, 170)
    grid: tuple[int, int, int] = (26, 36, 45)
    panel_border: tuple[int, int, int] = (62, 77, 94)
    panel_fill: tuple[int, int, int] = (23, 31, 40)
    stale_badge: tuple[int, int, int] = (176, 120, 28)
    live_badge: tuple[int, int, int] = (38, 166, 154)
    idle_badge: tuple[int, int, int] = (97, 107, 118)

    def qcolor(self, rgb: tuple[int, int, int], alpha: int = 255) -> QtGui.QColor:
        return QtGui.QColor(rgb[0], rgb[1], rgb[2], alpha)

    def blend(self, rgb: tuple[int, int, int], target: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
        return tuple(int((s * (1.0 - ratio)) + (d * ratio)) for s, d in zip(rgb, target))

    def tx_pen(self, ch: int):
        return pg.mkPen(color=self.qcolor(CHANNEL_COLORS[ch], 235), width=1.4, style=QtCore.Qt.SolidLine)

    def rx_live_pen(self, ch: int):
        return pg.mkPen(color=self.qcolor(CHANNEL_COLORS[ch], 255), width=1.3, style=QtCore.Qt.DashLine)

    def rx_stale_pen(self, ch: int):
        rgb = self.blend(CHANNEL_COLORS[ch], self.stale_badge, 0.55)
        return pg.mkPen(color=self.qcolor(rgb, 130), width=1.2, style=QtCore.Qt.DashLine)


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
        self._curve_tx: list = []
        self._curve_rx: list = []

        self.plotRunValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotRunValueLabel')
        self.plotRxStateValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotRxStateValueLabel')
        self.plotSampleValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotSampleValueLabel')
        self.plotWindowValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotWindowValueLabel')
        self.plotLastUpdateValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotLastUpdateValueLabel')
        self.plotTimeoutValueLabel = find_optional_child(self._plot_root, QtWidgets.QLabel, 'plotTimeoutValueLabel')

        self._apply_panel_theme()
        self._configure_status_bar()

        pg.setConfigOptions(antialias=False, background=self._theme.qcolor(self._theme.background))
        self._plot_widget = pg.PlotWidget()
        attach_widget(self._plot_host, self._plot_widget)

        self._plot = self._plot_widget.getPlotItem()
        self._configure_plot_surface()

        for ch in range(MAX_CHANNELS):
            tx_curve = self._plot.plot(self._x, self._y_tx[ch], pen=self._theme.tx_pen(ch), connect='finite')
            rx_curve = self._plot.plot(self._x, self._y_rx[ch], pen=self._theme.rx_live_pen(ch), connect='finite')
            self._curve_tx.append(tx_curve)
            self._curve_rx.append(rx_curve)

        self._configure_toggle_buttons()
        self._apply_curve_visibility()
        self._apply_rx_curve_style()

    def _apply_panel_theme(self):
        self._plot_root.setStyleSheet(
            'QGroupBox#plotPanel {'
            ' background-color: rgb(17, 24, 31);'
            ' border: 1px solid rgb(54, 68, 82);'
            ' border-radius: 0px;'
            ' margin-top: 10px;'
            ' color: rgb(225, 232, 240);'
            ' font-weight: 600;'
            '}'
            'QGroupBox#plotPanel::title {'
            ' subcontrol-origin: margin;'
            ' left: 10px;'
            ' padding: 0 4px;'
            '}'
            'QGroupBox#graphSettingsGroup {'
            ' background-color: rgb(21, 28, 36);'
            ' border: 1px solid rgb(68, 82, 96);'
            ' border-radius: 0px;'
            ' margin-top: 10px;'
            ' color: rgb(220, 228, 236);'
            ' font-weight: 600;'
            '}'
            'QGroupBox#graphSettingsGroup::title {'
            ' subcontrol-origin: margin;'
            ' left: 10px;'
            ' padding: 0 4px;'
            ' color: rgb(188, 199, 210);'
            '}'
        )

    def _configure_status_bar(self):
        caption_font = QtGui.QFont(self._font)
        caption_font.setBold(True)
        for name in (
            'plotRunCaptionLabel', 'plotRxStateCaptionLabel', 'plotSampleCaptionLabel',
            'plotWindowCaptionLabel', 'plotLastUpdateCaptionLabel', 'plotTimeoutCaptionLabel',
        ):
            label = find_optional_child(self._plot_root, QtWidgets.QLabel, name)
            if label is not None:
                label.setFont(caption_font)
                label.setStyleSheet('color: #8FA3B8;')

        for label in (
            self.plotSampleValueLabel, self.plotWindowValueLabel,
            self.plotLastUpdateValueLabel, self.plotTimeoutValueLabel,
        ):
            if label is not None:
                configure_value_label(label, self._font, QtCore.Qt.AlignCenter)
                label.setStyleSheet('color: #E6EEF8; padding: 2px 6px;')

        if self.plotSampleValueLabel is not None:
            self.plotSampleValueLabel.setText(f'{SAMPLE_PERIOD_S * 1000:.0f} ms')
        if self.plotWindowValueLabel is not None:
            self.plotWindowValueLabel.setText(f'{GRAPH_X_WINDOW_S:.1f} s')
        if self.plotLastUpdateValueLabel is not None:
            self.plotLastUpdateValueLabel.setText('--')
        if self.plotTimeoutValueLabel is not None:
            self.plotTimeoutValueLabel.setText('0')

        if self.plotRunValueLabel is not None:
            set_badge(self.plotRunValueLabel, 'STOP', 'stop')
        if self.plotRxStateValueLabel is not None:
            set_badge(self.plotRxStateValueLabel, 'WAIT', 'neutral')

        frame = find_optional_child(self._plot_root, QtWidgets.QFrame, 'graphStatusFrame')
        if frame is not None:
            frame.setStyleSheet(
                'QFrame#graphStatusFrame {'
                ' background-color: rgb(22, 29, 37);'
                ' border: 1px solid rgb(68, 82, 96);'
                ' border-radius: 0px;'
                '}'
            )

    def _configure_plot_surface(self):
        self._plot_widget.setBackground(self._theme.qcolor(self._theme.background))
        self._plot_widget.setContentsMargins(0, 0, 0, 0)
        self._plot_widget.setMenuEnabled(False)
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.hideButtons()
        self._plot.setClipToView(True)
        self._plot.setDownsampling(auto=True, mode='subsample')
        self._plot.layout.setContentsMargins(0, 0, 0, 0)
        self._plot.setLabel('bottom', 'TIME (S)', color='#9AA7B3', size='9pt')
        self._plot.setLabel('left', 'RATIO (%)', color='#9AA7B3', size='9pt')
        self._plot.showGrid(x=True, y=True, alpha=0.11)
        self._plot.setXRange(0.0, GRAPH_X_WINDOW_S, padding=0.0)
        self._plot.setYRange(0.0, 100.0, padding=0.0)
        self._plot.disableAutoRange()
        self._plot.setTitle(None)

        axis_pen = pg.mkPen(color=self._theme.qcolor(self._theme.axis), width=1.0)
        axis_text_pen = pg.mkPen(color=self._theme.qcolor(self._theme.axis_text), width=1.0)
        tick_font = QtGui.QFont(self._font)
        tick_font.setPointSize(max(8, tick_font.pointSize() - 1))
        for name in ('left', 'bottom'):
            axis = self._plot.getAxis(name)
            axis.setPen(axis_pen)
            axis.setTextPen(axis_text_pen)
            axis.setTickFont(tick_font)
        self._plot.getAxis('left').setTickSpacing(20, 10)
        self._plot.getAxis('bottom').setTickSpacing(2.0, 1.0)

    def _configure_toggle_buttons(self):
        btn_font = QtGui.QFont(self._font)
        btn_font.setPointSize(max(8, btn_font.pointSize() - 1))
        for i, color in enumerate(CHANNEL_COLORS, start=1):
            tx_btn = self._toggle_buttons[(i - 1, 'tx')]
            rx_btn = self._toggle_buttons[(i - 1, 'rx')]
            self._configure_toggle_button(tx_btn, color, btn_font)
            self._configure_toggle_button(rx_btn, color, btn_font)
            tx_btn.toggled.connect(lambda _c, ch=i - 1: self._apply_curve_visibility())
            rx_btn.toggled.connect(lambda _c, ch=i - 1: self._apply_curve_visibility())

    def _configure_toggle_button(self, button: QtWidgets.QPushButton, color, font: QtGui.QFont):
        dim = self._theme.blend(color, (120, 128, 136), 0.72)
        button.setCheckable(True)
        button.setChecked(True)
        button.setMinimumHeight(30)
        button.setFont(font)
        button.setStyleSheet(
            'QPushButton {'
            ' background-color: rgb(37, 45, 54);'
            ' color: rgb(113, 123, 133);'
            ' border-top: 1px solid rgb(96, 108, 120);'
            ' border-right: 1px solid rgb(78, 88, 100);'
            ' border-bottom: 2px solid rgb(12, 17, 22);'
            f' border-left: 4px solid rgb({dim[0]}, {dim[1]}, {dim[2]});'
            ' border-radius: 0px;'
            ' padding: 4px 10px 4px 8px;'
            ' text-align: left;'
            '}'
            'QPushButton:checked {'
            ' background-color: rgb(22, 29, 36);'
            ' color: rgb(244, 247, 250);'
            ' border-top: 1px solid rgb(42, 50, 58);'
            ' border-right: 1px solid rgb(96, 108, 120);'
            ' border-bottom: 1px solid rgb(112, 124, 136);'
            f' border-left: 4px solid rgb({color[0]}, {color[1]}, {color[2]});'
            ' padding: 5px 10px 3px 8px;'
            '}'
            'QPushButton:pressed {'
            ' background-color: rgb(16, 22, 28);'
            ' color: rgb(250, 252, 255);'
            '}'
        )

    def _apply_curve_visibility(self):
        for ch in range(MAX_CHANNELS):
            tx_vis = ch < self._active_tx_count and self._toggle_buttons[(ch, 'tx')].isChecked()
            rx_vis = ch < self._active_rx_count and self._toggle_buttons[(ch, 'rx')].isChecked()
            self._curve_tx[ch].setVisible(tx_vis)
            self._curve_rx[ch].setVisible(rx_vis)

    def _apply_rx_curve_style(self):
        for ch in range(MAX_CHANNELS):
            pen = self._theme.rx_stale_pen(ch) if self._rx_stale else self._theme.rx_live_pen(ch)
            self._curve_rx[ch].setPen(pen)

    def _set_rx_state(self, text: str, tone: str):
        self._rx_state = text
        self._rx_state_tone = tone
        if self.plotRxStateValueLabel is not None:
            set_badge(self.plotRxStateValueLabel, text, tone)

    def set_run_state(self, running: bool):
        self._running = running
        if self.plotRunValueLabel is not None:
            set_badge(self.plotRunValueLabel, 'RUN' if running else 'STOP', 'run' if running else 'stop')
        if not running and self._rx_state not in ('STALE', 'TIMEOUT'):
            self._set_rx_state('WAIT', 'neutral')

    def note_rx_timeout(self):
        self._rx_timeouts += 1
        self._rx_stale = True
        self._apply_rx_curve_style()
        self._set_rx_state('STALE', 'warn')
        if self.plotTimeoutValueLabel is not None:
            self.plotTimeoutValueLabel.setText(str(self._rx_timeouts))

    def note_rx_monitor(self, rx_monitor: Optional[SnetMonitorSnapshot]):
        if rx_monitor is None:
            self.note_rx_timeout()
            return
        self._active_rx_count = max(0, min(MAX_CHANNELS, int(rx_monitor.channel_count)))
        self._last_rx_monotonic = time.perf_counter()
        self._rx_stale = False
        self._apply_rx_curve_style()
        self._set_rx_state('LIVE', 'ok')
        self._apply_curve_visibility()

    def set_series_counts(self, tx_count: Optional[int] = None, rx_count: Optional[int] = None):
        if tx_count is not None:
            self._active_tx_count = max(0, min(MAX_CHANNELS, int(tx_count)))
        if rx_count is not None and int(rx_count) > 0:
            self._active_rx_count = max(0, min(MAX_CHANNELS, int(rx_count)))
        self._apply_curve_visibility()

    def add_point(self, tx_payload: Optional[IoPayload], rx_monitor: Optional[SnetMonitorSnapshot]):
        if self._has_started and self._write_index == 0:
            self._y_tx.fill(np.nan)
            self._y_rx.fill(np.nan)

        tx_ratios = _payload_channel_ratios(tx_payload)
        rx_ratios = monitor_channel_ratio_percents(rx_monitor)
        self.set_series_counts(tx_count=tx_payload.channel_count if tx_payload is not None else 0)
        if rx_monitor is not None:
            self.set_series_counts(rx_count=rx_monitor.channel_count)

        for ch in range(MAX_CHANNELS):
            self._y_tx[ch, self._write_index] = np.nan if tx_ratios[ch] is None else np.float32(tx_ratios[ch])
            self._y_rx[ch, self._write_index] = np.nan if rx_ratios[ch] is None else np.float32(rx_ratios[ch])

        self._write_index = (self._write_index + 1) % self._point_count
        self._has_started = True

    def _update_status_age(self, now: float):
        if self.plotLastUpdateValueLabel is None:
            return
        if self._last_rx_monotonic is None:
            self.plotLastUpdateValueLabel.setText('--')
            return
        age_s = max(0.0, now - self._last_rx_monotonic)
        self.plotLastUpdateValueLabel.setText(f'{age_s:0.2f} s')
        if self._running and age_s >= PLOT_STALE_THRESHOLD_S and self._rx_state == 'LIVE':
            self._rx_stale = True
            self._apply_rx_curve_style()
            self._set_rx_state('STALE', 'warn')

    def refresh(self, force: bool = False):
        now = time.perf_counter()
        self._update_status_age(now)
        if not force and (now - self._last_refresh) < GRAPH_REFRESH_S:
            return
        for ch in range(MAX_CHANNELS):
            if self._curve_tx[ch].isVisible():
                self._curve_tx[ch].setData(self._x, self._y_tx[ch], connect='finite')
            if self._curve_rx[ch].isVisible():
                self._curve_rx[ch].setData(self._x, self._y_rx[ch], connect='finite')
        self._last_refresh = now
