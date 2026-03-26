"""Real-time graph and compact metric view."""

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

from ..protocol.codec import monitor_channel_ratio_percents
from ..protocol.convert import valve_raw_to_display
from ..protocol.constants import MAX_CHANNELS, PLACEHOLDER, SAMPLE_PERIOD_S
from ..protocol.types import IoPayload, SnetMonitorSnapshot
from .helpers import clear_layout, configure_value_label, find_optional_child, set_badge

GRAPH_REFRESH_S = 0.05
GRAPH_X_WINDOW_S = 10.0
GRAPH_PANEL_VALVE_HEIGHT = 120
PLOT_STALE_THRESHOLD_S = max(0.25, SAMPLE_PERIOD_S * 5.0)
LEFT_AXIS_WIDTH_PX = 76
LEFT_TICK_TEXT_WIDTH_PX = 44
PLOT_WIDGET_SIDE_MARGIN_PX = 4


CHANNEL_COLORS = (
    (0, 229, 255),
    (255, 234, 0),
    (57, 255, 20),
    (255, 140, 0),
    (255, 51, 204),
    (255, 255, 255),
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
    def __init__(self):
        self.background = (243, 248, 252)
        self.valve_background = (247, 250, 253)
        self.axis = (133, 145, 160)
        self.axis_text = (71, 85, 105)
        self.valve_axis = (163, 173, 184)
        self.valve_axis_text = (115, 128, 142)
        self.grid = (206, 214, 224)
        self.valve_grid = (220, 228, 236)
        self.panel = (244, 247, 251)

    def qcolor(self, rgb, alpha: int = 255) -> QtGui.QColor:
        return QtGui.QColor(rgb[0], rgb[1], rgb[2], alpha)

    def tx_pen(self, ch: int):
        return pg.mkPen(color=self.qcolor(CHANNEL_COLORS[ch], 90), width=1.0, style=QtCore.Qt.SolidLine)

    def rx_live_pen(self, ch: int):
        return pg.mkPen(color=self.qcolor(CHANNEL_COLORS[ch], 255), width=2.0, style=QtCore.Qt.SolidLine)

    def rx_stale_pen(self, ch: int):
        return pg.mkPen(color=self.qcolor((230, 170, 60), 180), width=1.5, style=QtCore.Qt.DashLine)

    def _subordinate_channel_rgb(self, rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        neutral = (132, 145, 160)
        return (
            int((rgb[0] * 0.35) + (neutral[0] * 0.65)),
            int((rgb[1] * 0.35) + (neutral[1] * 0.65)),
            int((rgb[2] * 0.35) + (neutral[2] * 0.65)),
        )

    def valve_pen(self, ch: int):
        muted = self._subordinate_channel_rgb(CHANNEL_COLORS[ch])
        return pg.mkPen(color=self.qcolor(muted, 160), width=1.0, style=QtCore.Qt.SolidLine)


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
        self._summary_rows: list[dict[str, QtWidgets.QLabel]] = []

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
        self._plot_root.setStyleSheet(
            'QGroupBox#plotPanel {'
            ' background-color: rgb(244, 247, 251);'
            ' border: 1px solid rgb(205, 214, 222);'
            ' border-radius: 0px;'
            ' margin-top: 10px;'
            ' color: rgb(30, 41, 59);'
            ' font-weight: 600;'
            '}'
            'QGroupBox#plotPanel::title {'
            ' subcontrol-origin: margin;'
            ' left: 10px;'
            ' padding: 0 4px;'
            '}'
            'QGroupBox#graphSettingsGroup {'
            ' background-color: rgb(246, 249, 252);'
            ' border: 1px solid rgb(214, 223, 232);'
            ' border-radius: 0px;'
            ' color: rgb(71, 85, 105);'
            ' font-weight: 600;'
            '}'
            'QGroupBox#graphSettingsGroup::title {'
            ' subcontrol-origin: margin;'
            ' left: 8px;'
            ' padding: 0 4px;'
            '}'
        )
        settings_group = find_optional_child(self._plot_root, QtWidgets.QGroupBox, 'graphSettingsGroup')
        if settings_group is not None:
            settings_group.setTitle('Channels')

    def _configure_status_bar(self):
        caption_font = QtGui.QFont(self._font)
        caption_font.setBold(True)
        caption_texts = {
            'plotRunCaptionLabel': 'RUN',
            'plotRxStateCaptionLabel': 'LINK',
            'plotSampleCaptionLabel': 'SAMPLE',
            'plotWindowCaptionLabel': 'WINDOW',
            'plotLastUpdateCaptionLabel': 'RESP',
            'plotTimeoutCaptionLabel': 'TIMEOUT',
        }
        for name, caption in caption_texts.items():
            label = find_optional_child(self._plot_root, QtWidgets.QLabel, name)
            if label is not None:
                label.setText(caption)
                label.setFont(caption_font)
                label.setStyleSheet('color: #526173;')

        for label in (
            self.plotSampleValueLabel,
            self.plotWindowValueLabel,
            self.plotLastUpdateValueLabel,
            self.plotTimeoutValueLabel,
        ):
            if label is not None:
                configure_value_label(label, self._font, QtCore.Qt.AlignCenter)
                label.setStyleSheet('color: #0F172A; padding: 2px 6px;')

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

        frame = find_optional_child(self._plot_root, QtWidgets.QFrame, 'graphStatusFrame')
        if frame is not None:
            frame.setStyleSheet(
                'QFrame#graphStatusFrame {'
                ' background-color: rgb(233, 240, 247);'
                ' border: 1px solid rgb(205, 214, 222);'
                ' border-radius: 0px;'
                '}'
            )

    def _build_plots(self):
        layout = self._plot_host.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(self._plot_host)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)
        clear_layout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

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
            tx_curve = self._ratio_plot.plot(self._x, self._y_tx[ch], pen=self._theme.tx_pen(ch), connect='finite')
            rx_curve = self._ratio_plot.plot(self._x, self._y_rx[ch], pen=self._theme.rx_live_pen(ch), connect='finite')
            self._curve_tx.append(tx_curve)
            self._curve_rx.append(rx_curve)

        self._valve_plot_widget = pg.PlotWidget()
        self._valve_plot_widget.setMinimumHeight(GRAPH_PANEL_VALVE_HEIGHT)
        self._valve_plot_widget.setMaximumHeight(GRAPH_PANEL_VALVE_HEIGHT)
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

        self._plot_divider = QtWidgets.QFrame(self._plot_host)
        self._plot_divider.setObjectName('plotDividerLine')
        self._plot_divider.setFrameShape(QtWidgets.QFrame.HLine)
        self._plot_divider.setFrameShadow(QtWidgets.QFrame.Plain)
        self._plot_divider.setStyleSheet(
            'QFrame#plotDividerLine {'
            ' background-color: rgb(215, 223, 232);'
            ' border: none;'
            ' min-height: 1px;'
            ' max-height: 1px;'
            '}'
        )

        self._summary_strip = QtWidgets.QFrame(self._plot_host)
        self._summary_strip.setObjectName('plotSummaryStrip')
        self._summary_strip.setStyleSheet(
            'QFrame#plotSummaryStrip {'
            ' background-color: rgb(241, 246, 251);'
            ' border: 1px solid rgb(209, 217, 226);'
            ' border-radius: 0px;'
            '}'
        )
        self._summary_layout = QtWidgets.QGridLayout(self._summary_strip)
        self._summary_layout.setContentsMargins(6, 3, 6, 3)
        self._summary_layout.setHorizontalSpacing(6)
        self._summary_layout.setVerticalSpacing(2)
        header_font = QtGui.QFont(self._font)
        header_font.setBold(True)
        for col, title in enumerate(('CH', 'SET', 'ACT', 'VALVE', 'STATE')):
            hdr = QtWidgets.QLabel(title)
            hdr.setFont(header_font)
            hdr.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            hdr.setStyleSheet('color: #5F6E80;')
            self._summary_layout.addWidget(hdr, 0, col)

        for ch in range(MAX_CHANNELS):
            ch_label = QtWidgets.QLabel(f'CH{ch + 1}')
            set_label = QtWidgets.QLabel(PLACEHOLDER)
            actual_label = QtWidgets.QLabel(PLACEHOLDER)
            valve_label = QtWidgets.QLabel(PLACEHOLDER)
            state_label = QtWidgets.QLabel('IDLE')
            configure_value_label(ch_label, self._font, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            configure_value_label(set_label, self._font, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            configure_value_label(actual_label, self._font, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            configure_value_label(valve_label, self._font, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            state_label.setFont(self._font)
            for label in (ch_label, set_label, actual_label, valve_label):
                label.setStyleSheet('color: #334155;')
            state_label.setStyleSheet('color: #334155;')
            self._summary_rows.append(
                {
                    'channel': ch_label,
                    'set': set_label,
                    'actual': actual_label,
                    'valve': valve_label,
                    'state': state_label,
                }
            )
            row = ch + 1
            self._summary_layout.addWidget(ch_label, row, 0)
            self._summary_layout.addWidget(set_label, row, 1)
            self._summary_layout.addWidget(actual_label, row, 2)
            self._summary_layout.addWidget(valve_label, row, 3)
            self._summary_layout.addWidget(state_label, row, 4)

        self._summary_strip.setMinimumHeight(112)
        self._summary_strip.setMaximumHeight(120)

        layout.addWidget(self._ratio_plot_widget, 8)
        layout.addWidget(self._plot_divider, 0)
        layout.addWidget(self._valve_plot_widget, 1)
        layout.addWidget(self._summary_strip, 0)
        self._ratio_plot_widget.setObjectName('ratioPlot')
        self._valve_plot_widget.setObjectName('valvePlot')
        self._refresh_summary_rows()

    def _synchronize_axis_geometry(self):
        for plot in (self._ratio_plot, self._valve_plot):
            left_axis = plot.getAxis('left')
            left_axis.setWidth(LEFT_AXIS_WIDTH_PX)
            left_axis.setStyle(
                autoExpandTextSpace=False,
                tickTextOffset=8,
                tickTextWidth=LEFT_TICK_TEXT_WIDTH_PX,
            )

    def _configure_ratio_plot(self, plot):
        plot.layout.setContentsMargins(0, 0, 0, 0)
        plot.showGrid(x=True, y=True, alpha=0.24)
        plot.setXRange(0.0, GRAPH_X_WINDOW_S, padding=0.0)
        plot.setYRange(0.0, 100.0, padding=0.0)
        plot.disableAutoRange()
        plot.setMouseEnabled(x=False, y=False)
        plot.hideButtons()
        plot.setLabel('bottom', '', color='#475569', size='8pt')
        plot.setLabel('left', 'RATIO %', color='#435366', size='8pt')
        for name in ('left', 'bottom'):
            axis = plot.getAxis(name)
            axis.setPen(pg.mkPen(color=self._theme.qcolor(self._theme.axis), width=1.0))
            axis.setTextPen(pg.mkPen(color=self._theme.qcolor(self._theme.axis_text), width=1.0))
            axis.setTickFont(self._font)
        plot.getAxis('bottom').setStyle(showValues=False)

    def _configure_valve_plot(self, plot):
        plot.layout.setContentsMargins(0, 0, 0, 0)
        plot.showGrid(x=True, y=True, alpha=0.1)
        plot.setXRange(0.0, GRAPH_X_WINDOW_S, padding=0.0)
        plot.setYRange(0.0, 5.0, padding=0.0)
        plot.disableAutoRange()
        plot.setMouseEnabled(x=False, y=False)
        plot.hideButtons()
        plot.setLabel('bottom', 'TIME (S)', color='#6B7D90', size='7pt')
        plot.setLabel('left', 'VALVE', color='#6B7D90', size='7pt')
        valve_tick_font = QtGui.QFont(self._font)
        valve_tick_font.setPointSize(max(8, self._font.pointSize() - 1))
        for name in ('left', 'bottom'):
            axis = plot.getAxis(name)
            axis.setPen(pg.mkPen(color=self._theme.qcolor(self._theme.valve_axis), width=1.0))
            axis.setTextPen(pg.mkPen(color=self._theme.qcolor(self._theme.valve_axis_text), width=1.0))
            axis.setTickFont(valve_tick_font)

    def _configure_toggle_buttons(self):
        btn_font = QtGui.QFont(self._font)
        btn_font.setPointSize(max(8, btn_font.pointSize() - 1))
        for i, color in enumerate(CHANNEL_COLORS, start=1):
            tx_btn = self._toggle_buttons[(i - 1, 'tx')]
            rx_btn = self._toggle_buttons[(i - 1, 'rx')]
            self._configure_toggle_button(tx_btn, color, btn_font)
            self._configure_toggle_button(rx_btn, color, btn_font)
            tx_btn.toggled.connect(lambda _checked: self._apply_curve_visibility())
            rx_btn.toggled.connect(lambda _checked: self._apply_curve_visibility())

    def _configure_toggle_button(self, button: QtWidgets.QPushButton, color, font: QtGui.QFont):
        dim = (
            max(145, min(230, int((color[0] * 0.45) + 125))),
            max(145, min(230, int((color[1] * 0.45) + 125))),
            max(145, min(230, int((color[2] * 0.45) + 125))),
        )
        button.setCheckable(True)
        button.setChecked(True)
        button.setMinimumHeight(24)
        button.setFont(font)
        button.setStyleSheet(
            'QPushButton {'
            f' background-color: rgb(244, 248, 252);'
            ' color: rgb(71, 85, 105);'
            ' border-top: 1px solid rgb(224, 231, 239);'
            ' border-right: 1px solid rgb(213, 221, 230);'
            ' border-bottom: 1px solid rgb(205, 214, 224);'
            f' border-left: 3px solid rgb({dim[0]}, {dim[1]}, {dim[2]});'
            ' border-radius: 0px;'
            ' padding: 3px 7px 3px 6px;'
            ' text-align: left;'
            '}'
            'QPushButton:checked {'
            ' background-color: rgb(235, 242, 250);'
            ' color: rgb(15, 23, 42);'
            f' border-top: 1px solid rgb(206, 217, 234);'
            f' border-right: 1px solid rgb(206, 217, 234);'
            ' border-bottom: 1px solid rgb(171, 183, 198);'
            f' border-left: 3px solid rgb({color[0]}, {color[1]}, {color[2]});'
            '}'
            'QPushButton:pressed {'
            ' background-color: rgb(224, 235, 247);'
            ' color: rgb(15, 23, 42);'
            '}'
        )

    def _set_summary_state_badge(self, label: QtWidgets.QLabel, state: str):
        tones = {
            'LIVE': ('rgb(216, 240, 226)', 'rgb(120, 170, 139)', 'rgb(33, 84, 53)'),
            'STALE': ('rgb(251, 236, 209)', 'rgb(214, 174, 120)', 'rgb(124, 78, 18)'),
            'SET': ('rgb(233, 240, 247)', 'rgb(182, 195, 210)', 'rgb(71, 85, 105)'),
            'IDLE': ('rgb(239, 243, 247)', 'rgb(199, 208, 219)', 'rgb(98, 109, 122)'),
            'WAIT': ('rgb(233, 240, 247)', 'rgb(182, 195, 210)', 'rgb(71, 85, 105)'),
        }
        fill, border, text = tones.get(state, tones['IDLE'])
        label.setText(state)
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setStyleSheet(
            'QLabel {'
            f' background-color: {fill};'
            f' border: 1px solid {border};'
            f' color: {text};'
            ' border-radius: 0px;'
            ' padding: 1px 6px;'
            ' font-weight: 600;'
            '}'
        )

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
        for row, widget_set in zip(rows, self._summary_rows):
            row_visibility = row.channel <= max(self._active_tx_count, self._active_rx_count, 1)
            widget_set['channel'].setVisible(row_visibility)
            widget_set['set'].setVisible(row_visibility)
            widget_set['actual'].setVisible(row_visibility)
            widget_set['valve'].setVisible(row_visibility)
            widget_set['state'].setVisible(row_visibility)

            widget_set['channel'].setText(f'CH{row.channel}')
            widget_set['set'].setText(self._format_numeric(row.set_percent, '{:.1f}%'))
            widget_set['actual'].setText(self._format_numeric(row.actual_percent, '{:.1f}%'))
            widget_set['valve'].setText(self._format_numeric(row.valve_volts, '{:.2f}'))
            widget_set['state'].setText(row.state_text)

            self._set_summary_state_badge(widget_set['state'], row.state_text)

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
                self._curve_tx[ch].setData(self._x, self._y_tx[ch], connect='finite')
            if self._curve_rx[ch].isVisible():
                self._curve_rx[ch].setData(self._x, self._y_rx[ch], connect='finite')
            if self._curve_valve[ch].isVisible():
                self._curve_valve[ch].setData(self._x, self._y_valve[ch], connect='finite')
        self._last_refresh = now
