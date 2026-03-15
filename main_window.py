import pathlib
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets, uic

from backend import (
    FRAME_FIXED_FIELDS,
    FRAME_PANEL_PLACEHOLDER,
    HEX_DUMP_BYTES_PER_LINE,
    IoPayload,
    MAX_CHANNELS,
    REQUEST_CMD,
    RESPONSE_CMD,
    RUN_FOREVER,
    SAMPLE_PERIOD_S,
    SEQ_START,
    SerialWorker,
    SnetChannelMonitor,
    SnetMonitorSnapshot,
    RunningStats,
    SampleEvent,
    build_mock_snet_monitor_payload,
    build_frame,
    build_io_payload_bytes,
    build_io_payload_model,
    build_write_var_frame,
    clamp_channel_count,
    decode_frame_view,
    decode_io_payload,
    decode_snet_monitor_payload,
    default_io_payload,
    first_monitor_ratio_percent,
    flow_raw_to_display,
    format_channel_summary,
    format_data_hexdump,
    format_sample_log,
    frame_view_fixed_rows,
    monitor_channel_ratio_percents,
    pressure_raw_to_psi,
    ratio_raw_to_percent,
    temperature_raw_to_celsius,
    valve_raw_to_display,
    WRITE_VAR_READ_AD_FLAG_INDEX,
)


GRAPH_REFRESH_S = 0.05
GRAPH_X_WINDOW_S = 10.0
UI_TIMER_MS = 20
MOCK_LATENCY_MS = 5.0
PLOT_STALE_THRESHOLD_S = max(0.25, SAMPLE_PERIOD_S * 5.0)
UI_DIR = pathlib.Path(__file__).resolve().parent / 'ui'
CHANNEL_COLORS = (
    (33, 150, 243),
    (231, 76, 60),
    (46, 204, 113),
    (243, 156, 18),
    (26, 188, 156),
    (155, 89, 182),
)


MAIN_WINDOW_OBJECTS = {
    'txPanel': QtWidgets.QWidget,
    'rxPanel': QtWidgets.QWidget,
    'plotPanel': QtWidgets.QGroupBox,
}

TX_PANEL_OBJECTS = {
    'channelCountCombo': QtWidgets.QComboBox,
    'runButton': QtWidgets.QPushButton,
    'stopButton': QtWidgets.QPushButton,
    'setButton': QtWidgets.QPushButton,
    'txFrameTable': QtWidgets.QTableWidget,
    'txDataDump': QtWidgets.QPlainTextEdit,
    'ratioInput1': QtWidgets.QLineEdit,
    'ratioInput2': QtWidgets.QLineEdit,
    'ratioInput3': QtWidgets.QLineEdit,
    'ratioInput4': QtWidgets.QLineEdit,
    'ratioInput5': QtWidgets.QLineEdit,
    'ratioInput6': QtWidgets.QLineEdit,
    'ratioRaw1': QtWidgets.QLabel,
    'ratioRaw2': QtWidgets.QLabel,
    'ratioRaw3': QtWidgets.QLabel,
    'ratioRaw4': QtWidgets.QLabel,
    'ratioRaw5': QtWidgets.QLabel,
    'ratioRaw6': QtWidgets.QLabel,
}

RX_PANEL_OBJECTS = {
    'rxMonitorTable': QtWidgets.QTableWidget,
    'rxFrameTable': QtWidgets.QTableWidget,
    'rxDataDump': QtWidgets.QPlainTextEdit,
}

PLOT_PANEL_OBJECTS = {
    'plotHost': QtWidgets.QFrame,
    'graphSettingsGroup': QtWidgets.QGroupBox,
    'legendTx1Button': QtWidgets.QPushButton,
    'legendTx2Button': QtWidgets.QPushButton,
    'legendTx3Button': QtWidgets.QPushButton,
    'legendTx4Button': QtWidgets.QPushButton,
    'legendTx5Button': QtWidgets.QPushButton,
    'legendTx6Button': QtWidgets.QPushButton,
    'legendRx1Button': QtWidgets.QPushButton,
    'legendRx2Button': QtWidgets.QPushButton,
    'legendRx3Button': QtWidgets.QPushButton,
    'legendRx4Button': QtWidgets.QPushButton,
    'legendRx5Button': QtWidgets.QPushButton,
    'legendRx6Button': QtWidgets.QPushButton,
}


def ui_path(filename: str) -> pathlib.Path:
    return UI_DIR / filename


def require_child(parent, child_type, name: str):
    child = parent.findChild(child_type, name)
    if child is None:
        parent_name = parent.objectName() or type(parent).__name__
        raise RuntimeError(f"Missing required widget '{name}' in '{parent_name}'")
    return child


def find_optional_child(parent, child_type, name: str):
    return parent.findChild(child_type, name)


def load_ui(widget, filename: str):
    path = ui_path(filename)
    if not path.exists():
        raise FileNotFoundError(f'UI file not found: {path}')
    uic.loadUi(str(path), widget)


def attach_widget(host: QtWidgets.QWidget, child: QtWidgets.QWidget):
    layout = host.layout()
    if layout is None:
        layout = QtWidgets.QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
    clear_layout(layout)
    layout.addWidget(child)


def clear_layout(layout: QtWidgets.QLayout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().setParent(None)
        elif item.layout() is not None:
            clear_layout(item.layout())


def configure_plain_text_edit(text_edit: QtWidgets.QPlainTextEdit, font: QtGui.QFont):
    text_edit.setReadOnly(True)
    text_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
    text_edit.setFont(font)
    text_edit.setPlainText(FRAME_PANEL_PLACEHOLDER)


def build_fixed_font() -> QtGui.QFont:
    font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
    font.setPointSize(10)
    return font


def configure_value_label(label: QtWidgets.QLabel, font: QtGui.QFont, align: QtCore.Qt.AlignmentFlag = QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter):
    label.setFont(font)
    label.setAlignment(align)
    label.setText(FRAME_PANEL_PLACEHOLDER)


def set_badge(label: QtWidgets.QLabel, text: str, tone: str):
    styles = {
        'neutral': '#616161',
        'run': '#2E7D32',
        'stop': '#757575',
        'ok': '#1565C0',
        'warn': '#EF6C00',
        'error': '#C62828',
    }
    color = styles.get(tone, styles['neutral'])
    label.setText(text)
    label.setStyleSheet(
        'QLabel {'
        f' background-color: {color};'
        ' color: white;'
        ' border-radius: 4px;'
        ' padding: 3px 8px;'
        ' font-weight: 600;'
        '}'
    )


def ensure_table_shape(table: QtWidgets.QTableWidget, rows: int, cols: int, table_name: str):
    if table.rowCount() != rows or table.columnCount() != cols:
        raise RuntimeError(
            f"Table '{table_name}' shape mismatch: expected {rows}x{cols}, got {table.rowCount()}x{table.columnCount()}"
        )


def payload_channel_ratios(io_payload: Optional[IoPayload]) -> list[Optional[float]]:
    ratios = [None] * MAX_CHANNELS
    if io_payload is None:
        return ratios

    for index, channel in enumerate(io_payload.channels[:io_payload.channel_count]):
        ratios[index] = channel.ratio_percent
    return ratios


def build_line_edit_style(background: str, border: str = '#B0B0B0') -> str:
    return (
        'QLineEdit {'
        f' background-color: {background};'
        f' border: 1px solid {border};'
        ' border-radius: 4px;'
        ' padding: 2px 6px;'
        '}'
    )


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
        return tuple(int((src * (1.0 - ratio)) + (dst * ratio)) for src, dst in zip(rgb, target))

    def tx_pen(self, channel_index: int):
        color = self.qcolor(CHANNEL_COLORS[channel_index], 235)
        return pg.mkPen(color=color, width=1.4, style=QtCore.Qt.SolidLine)

    def rx_live_pen(self, channel_index: int):
        color = self.qcolor(CHANNEL_COLORS[channel_index], 255)
        return pg.mkPen(color=color, width=1.3, style=QtCore.Qt.DashLine)

    def rx_stale_pen(self, channel_index: int):
        rgb = self.blend(CHANNEL_COLORS[channel_index], self.stale_badge, 0.55)
        color = self.qcolor(rgb, 130)
        return pg.mkPen(color=color, width=1.2, style=QtCore.Qt.DashLine)


class TxPanelView:
    INPUT_STYLE_DEFAULT = build_line_edit_style('#FFFFFF')
    INPUT_STYLE_APPLIED = build_line_edit_style('#E8F5E9', '#81C784')
    INPUT_STYLE_DISABLED = build_line_edit_style('#F1F1F1', '#D0D0D0')

    def __init__(self, root: QtWidgets.QWidget, font: QtGui.QFont):
        self._root = root
        self._font = font
        self._running = False
        self._applied_payload = default_io_payload(channel_count=1)
        self._highlight_applied_inputs = False
        self._last_result = FRAME_PANEL_PLACEHOLDER
        self._frame_items = {}

        for name, child_type in TX_PANEL_OBJECTS.items():
            setattr(self, name, require_child(self._root, child_type, name))

        self.txStateValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'txStateValueLabel')
        self.txChannelsValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'txChannelsValueLabel')
        self.txLastResultValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'txLastResultValueLabel')
        self.txFrameSeqValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'txFrameSeqValueLabel')
        self.txFrameCmdValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'txFrameCmdValueLabel')
        self.txFrameLenValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'txFrameLenValueLabel')
        self.txFrameTotalValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'txFrameTotalValueLabel')
        self.txStatusLabel = find_optional_child(self._root, QtWidgets.QLabel, 'txStatusLabel')
        self.appliedLabel = find_optional_child(self._root, QtWidgets.QLabel, 'appliedLabel')
        self.txFrameMetaLabel = find_optional_child(self._root, QtWidgets.QLabel, 'txFrameMetaLabel')

        self._ratio_inputs = [getattr(self, f'ratioInput{index}') for index in range(1, MAX_CHANNELS + 1)]
        self._ratio_raw_labels = [getattr(self, f'ratioRaw{index}') for index in range(1, MAX_CHANNELS + 1)]

        self.channelCountCombo.clear()
        self.channelCountCombo.addItems([str(index) for index in range(1, MAX_CHANNELS + 1)])
        self.channelCountCombo.currentIndexChanged.connect(self._on_channel_count_changed)

        for ratio_input in self._ratio_inputs:
            validator = QtGui.QDoubleValidator(0.0, 100.0, 3, ratio_input)
            validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
            ratio_input.setValidator(validator)
            ratio_input.setFont(font)
            ratio_input.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            ratio_input.textChanged.connect(self.refresh_pending_previews)

        for raw_label in self._ratio_raw_labels:
            raw_label.setFont(font)
            raw_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        for label_name in (
            'txStateValueLabel',
            'txChannelsValueLabel',
            'txLastResultValueLabel',
            'txFrameSeqValueLabel',
            'txFrameCmdValueLabel',
            'txFrameLenValueLabel',
            'txFrameTotalValueLabel',
        ):
            label = getattr(self, label_name)
            if label is not None:
                configure_value_label(label, font)

        for label_name in ('txStatusLabel', 'appliedLabel', 'txFrameMetaLabel'):
            label = getattr(self, label_name)
            if label is not None:
                label.setFont(font)

        configure_plain_text_edit(self.txDataDump, font)
        self._configure_frame_table()
        self._update_channel_input_state()
        self.refresh_pending_previews()
        self.set_applied_payload(self._applied_payload)
        self.update_run_state(False)
        self.update_frame(None, status='waiting')

    def _configure_frame_table(self):
        table = self.txFrameTable
        ensure_table_shape(table, len(FRAME_FIXED_FIELDS), 1, 'txFrameTable')
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setFocusPolicy(QtCore.Qt.NoFocus)
        table.setWordWrap(False)
        table.setFont(self._font)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)

        for row_index, field_name in enumerate(FRAME_FIXED_FIELDS):
            item = table.item(row_index, 0)
            if item is None:
                item = QtWidgets.QTableWidgetItem(FRAME_PANEL_PLACEHOLDER)
                table.setItem(row_index, 0, item)
            item.setTextAlignment(int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter))
            self._frame_items[field_name] = item

    def connect_actions(self, run_callback, stop_callback, set_callback):
        self.runButton.clicked.connect(run_callback)
        self.stopButton.clicked.connect(stop_callback)
        self.setButton.clicked.connect(set_callback)

    def _selected_channel_count(self) -> int:
        return clamp_channel_count(int(self.channelCountCombo.currentText()))

    def _on_channel_count_changed(self, *_args):
        self._update_channel_input_state()
        self.refresh_pending_previews()

    def _update_channel_input_state(self):
        active_count = self._selected_channel_count()
        for index, ratio_input in enumerate(self._ratio_inputs):
            enabled = index < active_count
            ratio_input.setEnabled(enabled)
            self._ratio_raw_labels[index].setEnabled(enabled)
            if not enabled:
                self._ratio_raw_labels[index].setText(FRAME_PANEL_PLACEHOLDER)
                ratio_input.setStyleSheet(self.INPUT_STYLE_DISABLED)
        self._refresh_input_highlights()

    def _input_matches_applied(self, channel_index: int) -> bool:
        if channel_index >= self._applied_payload.channel_count:
            return False

        text = self._ratio_inputs[channel_index].text().strip()
        if not text:
            return False

        try:
            pending_channel = build_io_payload_model(channel_count=1, ratio_percents=[float(text)]).channels[0]
        except ValueError:
            return False

        return pending_channel.ratio_raw == self._applied_payload.channels[channel_index].ratio_raw

    def _refresh_input_highlights(self):
        active_count = self._selected_channel_count()
        for index, ratio_input in enumerate(self._ratio_inputs):
            if index >= active_count:
                ratio_input.setStyleSheet(self.INPUT_STYLE_DISABLED)
            elif self._highlight_applied_inputs and self._input_matches_applied(index):
                ratio_input.setStyleSheet(self.INPUT_STYLE_APPLIED)
            else:
                ratio_input.setStyleSheet(self.INPUT_STYLE_DEFAULT)

    def refresh_pending_previews(self, *_args):
        active_count = self._selected_channel_count()
        for index, ratio_input in enumerate(self._ratio_inputs):
            if index >= active_count:
                self._ratio_raw_labels[index].setText(FRAME_PANEL_PLACEHOLDER)
                continue

            text = ratio_input.text().strip()
            if not text:
                self._ratio_raw_labels[index].setText(FRAME_PANEL_PLACEHOLDER)
                continue

            try:
                payload = build_io_payload_model(channel_count=1, ratio_percents=[float(text)])
            except ValueError:
                self._ratio_raw_labels[index].setText(FRAME_PANEL_PLACEHOLDER)
                continue

            self._ratio_raw_labels[index].setText(f'0x{payload.channels[0].ratio_raw:04X}')
        self._refresh_input_highlights()

    def build_pending_payload(self) -> IoPayload:
        active_count = self._selected_channel_count()
        ratio_percents = []
        for index in range(active_count):
            text = self._ratio_inputs[index].text().strip()
            if not text:
                raise ValueError(f'CH{index + 1} ratio is empty')
            ratio_percents.append(float(text))
        return build_io_payload_model(channel_count=active_count, ratio_percents=ratio_percents)

    def show_validation_error(self, message: str):
        self._last_result = message
        if self.txLastResultValueLabel is not None:
            set_badge(self.txLastResultValueLabel, 'INPUT ERROR', 'warn')
        if self.txStatusLabel is not None:
            self.txStatusLabel.setText(f"State: {'RUN' if self._running else 'STOP'} | {message}")

    def update_run_state(self, running: bool):
        self._running = running
        if self.txStateValueLabel is not None:
            set_badge(self.txStateValueLabel, 'RUN' if running else 'STOP', 'run' if running else 'stop')
        if self.txChannelsValueLabel is not None:
            self.txChannelsValueLabel.setText(str(self._applied_payload.channel_count))
        if self.txStatusLabel is not None:
            self.txStatusLabel.setText(
                f"State: {'RUN' if running else 'STOP'} | Applied Ch.: {self._applied_payload.channel_count}"
            )
        self.runButton.setEnabled(not running)
        self.stopButton.setEnabled(running)

    def set_applied_payload(self, io_payload: IoPayload, highlight_inputs: bool = True):
        self._applied_payload = io_payload
        self._highlight_applied_inputs = highlight_inputs
        if self.txChannelsValueLabel is not None:
            self.txChannelsValueLabel.setText(str(io_payload.channel_count))
        if self.appliedLabel is not None:
            self.appliedLabel.setText(f'Applied: {format_channel_summary(io_payload)}')
        if highlight_inputs and self.txLastResultValueLabel is not None:
            set_badge(self.txLastResultValueLabel, 'APPLIED', 'ok')
        self._refresh_input_highlights()
        self.update_run_state(self._running)

    def update_frame(self, frame_view, status: Optional[str] = None):
        if frame_view is None:
            for item in self._frame_items.values():
                item.setText(FRAME_PANEL_PLACEHOLDER)
            self.txDataDump.setPlainText(FRAME_PANEL_PLACEHOLDER)
            if self.txFrameSeqValueLabel is not None:
                self.txFrameSeqValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.txFrameCmdValueLabel is not None:
                self.txFrameCmdValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.txFrameLenValueLabel is not None:
                self.txFrameLenValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.txFrameTotalValueLabel is not None:
                self.txFrameTotalValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.txFrameMetaLabel is not None:
                self.txFrameMetaLabel.setText('Frame: LEN: -- | Total: --')
            if self.txLastResultValueLabel is not None:
                set_badge(self.txLastResultValueLabel, (status or 'WAIT').upper(), 'neutral')
            return

        for field_name, hex_text in frame_view_fixed_rows(frame_view).items():
            self._frame_items[field_name].setText(hex_text)
        self.txDataDump.setPlainText(format_data_hexdump(frame_view.data, HEX_DUMP_BYTES_PER_LINE))
        if self.txFrameSeqValueLabel is not None:
            self.txFrameSeqValueLabel.setText(f'0x{frame_view.seq:02X}')
        if self.txFrameCmdValueLabel is not None:
            self.txFrameCmdValueLabel.setText(f'0x{frame_view.cmd:04X}')
        if self.txFrameLenValueLabel is not None:
            self.txFrameLenValueLabel.setText(f'0x{frame_view.length:02X}')
        if self.txFrameTotalValueLabel is not None:
            self.txFrameTotalValueLabel.setText(str(len(frame_view.raw)))
        if self.txFrameMetaLabel is not None:
            length_text = f'0x{frame_view.length:02X} ({frame_view.length} bytes)'
            total_text = f'{len(frame_view.raw)} bytes'
            self.txFrameMetaLabel.setText(f'Frame: LEN: {length_text} | Total: {total_text}')
        if self.txLastResultValueLabel is not None:
            set_badge(self.txLastResultValueLabel, (status or 'SENT').upper(), 'ok')


class RxPanelView:
    def __init__(self, root: QtWidgets.QWidget, font: QtGui.QFont):
        self._root = root
        self._font = font
        self._frame_items = {}
        self._monitor_items = {}
        self._table_enabled_brush = None
        self._table_disabled_brush = None
        self._last_monitor_snapshot = None
        self._last_monitor_status = 'waiting'

        for name, child_type in RX_PANEL_OBJECTS.items():
            setattr(self, name, require_child(self._root, child_type, name))

        self.rxStatusValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxStatusValueLabel')
        self.rxModeValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxModeValueLabel')
        self.rxChannelsValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxChannelsValueLabel')
        self.rxPressureValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxPressureValueLabel')
        self.rxTemperatureValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxTemperatureValueLabel')
        self.rxFrameStatusValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxFrameStatusValueLabel')
        self.rxFrameSeqValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxFrameSeqValueLabel')
        self.rxFrameCmdValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxFrameCmdValueLabel')
        self.rxFrameLenValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxFrameLenValueLabel')
        self.rxFrameTotalValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxFrameTotalValueLabel')
        self.rxStatusLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxStatusLabel')
        self.rxControlModeLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxControlModeLabel')
        self.rxFrameMetaLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxFrameMetaLabel')
        self.valveNoCheckBox = find_optional_child(self._root, QtWidgets.QCheckBox, 'valveNoCheckBox')
        self.adCommandCheckBox = find_optional_child(self._root, QtWidgets.QCheckBox, 'adCommandCheckBox')

        for label_name in (
            'rxStatusValueLabel',
            'rxModeValueLabel',
            'rxChannelsValueLabel',
            'rxPressureValueLabel',
            'rxTemperatureValueLabel',
            'rxFrameStatusValueLabel',
            'rxFrameSeqValueLabel',
            'rxFrameCmdValueLabel',
            'rxFrameLenValueLabel',
            'rxFrameTotalValueLabel',
        ):
            label = getattr(self, label_name)
            if label is not None:
                configure_value_label(label, font)

        for label_name in ('rxStatusLabel', 'rxControlModeLabel', 'rxFrameMetaLabel'):
            label = getattr(self, label_name)
            if label is not None:
                label.setFont(font)

        if self.valveNoCheckBox is not None:
            self.valveNoCheckBox.toggled.connect(self._on_valve_display_toggled)

        configure_plain_text_edit(self.rxDataDump, font)
        self._configure_monitor_table()
        self._configure_frame_table()
        self.update_monitor(None, status='waiting')
        self.update_frame(None, status='waiting')

    def _configure_monitor_table(self):
        table = self.rxMonitorTable
        ensure_table_shape(table, 4, MAX_CHANNELS, 'rxMonitorTable')
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setFocusPolicy(QtCore.Qt.NoFocus)
        table.setWordWrap(False)
        table.setFont(self._font)
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        palette = table.palette()
        self._table_enabled_brush = QtGui.QBrush(palette.color(QtGui.QPalette.Text))
        self._table_disabled_brush = QtGui.QBrush(palette.color(QtGui.QPalette.Disabled, QtGui.QPalette.Text))

        for row_index in range(4):
            for col_index in range(MAX_CHANNELS):
                item = table.item(row_index, col_index)
                if item is None:
                    item = QtWidgets.QTableWidgetItem(FRAME_PANEL_PLACEHOLDER)
                    table.setItem(row_index, col_index, item)
                item.setTextAlignment(int(QtCore.Qt.AlignCenter))
                self._monitor_items[(row_index, col_index)] = item

    def _configure_frame_table(self):
        table = self.rxFrameTable
        ensure_table_shape(table, len(FRAME_FIXED_FIELDS), 1, 'rxFrameTable')
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setFocusPolicy(QtCore.Qt.NoFocus)
        table.setWordWrap(False)
        table.setFont(self._font)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)

        for row_index, field_name in enumerate(FRAME_FIXED_FIELDS):
            item = table.item(row_index, 0)
            if item is None:
                item = QtWidgets.QTableWidgetItem(FRAME_PANEL_PLACEHOLDER)
                table.setItem(row_index, 0, item)
            item.setTextAlignment(int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter))
            self._frame_items[field_name] = item

    def _on_valve_display_toggled(self, _checked: bool):
        self._render_monitor(self._last_monitor_snapshot, self._last_monitor_status)

    def _valve_display_inverted(self) -> bool:
        return self.valveNoCheckBox.isChecked() if self.valveNoCheckBox is not None else False

    def update_monitor(self, snet_monitor: Optional[SnetMonitorSnapshot], status: str = FRAME_PANEL_PLACEHOLDER):
        self._last_monitor_snapshot = snet_monitor
        self._last_monitor_status = status
        self._render_monitor(snet_monitor, status)

    def _render_monitor(self, snet_monitor: Optional[SnetMonitorSnapshot], status: str):
        if snet_monitor is None:
            if self.rxFrameStatusValueLabel is not None:
                set_badge(self.rxFrameStatusValueLabel, (status or 'WAIT').upper(), 'neutral')
            if self.rxStatusValueLabel is not None:
                self.rxStatusValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.rxModeValueLabel is not None:
                self.rxModeValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.rxChannelsValueLabel is not None:
                self.rxChannelsValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.rxPressureValueLabel is not None:
                self.rxPressureValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.rxTemperatureValueLabel is not None:
                self.rxTemperatureValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.rxStatusLabel is not None:
                self.rxStatusLabel.setText(f'Status: {status} | Ch.: --')
            if self.rxControlModeLabel is not None:
                self.rxControlModeLabel.setText('PRESS: -- | TEMP: --')
            for channel_index in range(MAX_CHANNELS):
                self._set_monitor_column(channel_index, None, invert_no=self._valve_display_inverted())
            return

        tone = 'ok' if status == 'OK' else 'warn' if status == 'TIMEOUT' else 'neutral'
        pressure_text = f'{pressure_raw_to_psi(snet_monitor.pressure_raw):.2f} psi'
        temperature_text = f'{temperature_raw_to_celsius(snet_monitor.temperature_raw):.2f}도'

        if self.rxFrameStatusValueLabel is not None:
            set_badge(self.rxFrameStatusValueLabel, (status or 'OK').upper(), tone)
        if self.rxStatusValueLabel is not None:
            self.rxStatusValueLabel.setText(f'0x{snet_monitor.status:02X}')
        if self.rxModeValueLabel is not None:
            self.rxModeValueLabel.setText(f'0x{snet_monitor.mode:02X}')
        if self.rxChannelsValueLabel is not None:
            self.rxChannelsValueLabel.setText(str(snet_monitor.channel_count))
        if self.rxPressureValueLabel is not None:
            self.rxPressureValueLabel.setText(pressure_text)
        if self.rxTemperatureValueLabel is not None:
            self.rxTemperatureValueLabel.setText(temperature_text)
        if self.rxStatusLabel is not None:
            self.rxStatusLabel.setText(
                f'Status: 0x{snet_monitor.status:02X} ({status}) | Ch.: {snet_monitor.channel_count}'
            )
        if self.rxControlModeLabel is not None:
            self.rxControlModeLabel.setText(f'PRESS: {pressure_text} | TEMP: {temperature_text}')

        invert_no = self._valve_display_inverted()
        for channel_index in range(MAX_CHANNELS):
            channel = snet_monitor.channels[channel_index] if channel_index < snet_monitor.channel_count else None
            self._set_monitor_column(channel_index, channel, invert_no=invert_no)

    def _set_monitor_column(self, channel_index: int, channel: Optional[SnetChannelMonitor], invert_no: bool):
        if channel is None:
            values = (
                (FRAME_PANEL_PLACEHOLDER, ''),
                (FRAME_PANEL_PLACEHOLDER, ''),
                (FRAME_PANEL_PLACEHOLDER, ''),
                (FRAME_PANEL_PLACEHOLDER, ''),
            )
            brush = self._table_disabled_brush
        else:
            flow_display = flow_raw_to_display(channel.flow_raw)
            valve_display = valve_raw_to_display(channel.valve_raw)
            if invert_no:
                valve_display = 5.0 - valve_display
            values = (
                (f'{flow_display:.2f}', f'0x{channel.flow_raw:04X}'),
                (str(channel.ad_raw), f'0x{channel.ad_raw:04X}'),
                (f'{ratio_raw_to_percent(channel.ratio_raw):.2f}', f'0x{channel.ratio_raw:04X}'),
                (f'{valve_display:.2f}', f'0x{channel.valve_raw:04X}'),
            )
            brush = self._table_enabled_brush

        for row_index, (text, tooltip) in enumerate(values):
            item = self._monitor_items[(row_index, channel_index)]
            item.setText(text)
            item.setToolTip(tooltip)
            item.setForeground(brush)

    def update_frame(self, frame_view, status: Optional[str] = None):
        if frame_view is None:
            for item in self._frame_items.values():
                item.setText(FRAME_PANEL_PLACEHOLDER)
            self.rxDataDump.setPlainText(FRAME_PANEL_PLACEHOLDER)
            if self.rxFrameSeqValueLabel is not None:
                self.rxFrameSeqValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.rxFrameCmdValueLabel is not None:
                self.rxFrameCmdValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.rxFrameLenValueLabel is not None:
                self.rxFrameLenValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.rxFrameTotalValueLabel is not None:
                self.rxFrameTotalValueLabel.setText(FRAME_PANEL_PLACEHOLDER)
            if self.rxFrameMetaLabel is not None:
                self.rxFrameMetaLabel.setText(f'Frame: {status or FRAME_PANEL_PLACEHOLDER} | LEN: -- | Total: --')
            if self.rxFrameStatusValueLabel is not None:
                set_badge(self.rxFrameStatusValueLabel, (status or 'WAIT').upper(), 'neutral')
            return

        for field_name, hex_text in frame_view_fixed_rows(frame_view).items():
            self._frame_items[field_name].setText(hex_text)
        self.rxDataDump.setPlainText(format_data_hexdump(frame_view.data, HEX_DUMP_BYTES_PER_LINE))
        if self.rxFrameSeqValueLabel is not None:
            self.rxFrameSeqValueLabel.setText(f'0x{frame_view.seq:02X}')
        if self.rxFrameCmdValueLabel is not None:
            self.rxFrameCmdValueLabel.setText(f'0x{frame_view.cmd:04X}')
        if self.rxFrameLenValueLabel is not None:
            self.rxFrameLenValueLabel.setText(f'0x{frame_view.length:02X}')
        if self.rxFrameTotalValueLabel is not None:
            self.rxFrameTotalValueLabel.setText(str(len(frame_view.raw)))
        if self.rxFrameMetaLabel is not None:
            length_text = f'0x{frame_view.length:02X} ({frame_view.length} bytes)'
            total_text = f'{len(frame_view.raw)} bytes'
            self.rxFrameMetaLabel.setText(
                f'Frame: {status or FRAME_PANEL_PLACEHOLDER} | LEN: {length_text} | Total: {total_text}'
            )
        tone = 'ok' if status == 'OK' else 'warn' if status == 'TIMEOUT' else 'neutral'
        if self.rxFrameStatusValueLabel is not None:
            set_badge(self.rxFrameStatusValueLabel, (status or 'RX').upper(), tone)


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
        self._last_rx_monotonic = None
        self._rx_state = 'WAIT'
        self._rx_state_tone = 'neutral'
        self._rx_stale = False
        self._curve_tx = []
        self._curve_rx = []

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

        for channel_index in range(MAX_CHANNELS):
            tx_curve = self._plot.plot(
                self._x,
                self._y_tx[channel_index],
                pen=self._theme.tx_pen(channel_index),
                connect='finite',
            )
            rx_curve = self._plot.plot(
                self._x,
                self._y_rx[channel_index],
                pen=self._theme.rx_live_pen(channel_index),
                connect='finite',
            )
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
        for label_name in (
            'plotRunCaptionLabel',
            'plotRxStateCaptionLabel',
            'plotSampleCaptionLabel',
            'plotWindowCaptionLabel',
            'plotLastUpdateCaptionLabel',
            'plotTimeoutCaptionLabel',
        ):
            label = find_optional_child(self._plot_root, QtWidgets.QLabel, label_name)
            if label is not None:
                label.setFont(caption_font)
                label.setStyleSheet('color: #8FA3B8;')

        for label in (
            self.plotSampleValueLabel,
            self.plotWindowValueLabel,
            self.plotLastUpdateValueLabel,
            self.plotTimeoutValueLabel,
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

        graph_status_frame = find_optional_child(self._plot_root, QtWidgets.QFrame, 'graphStatusFrame')
        if graph_status_frame is not None:
            graph_status_frame.setStyleSheet(
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
        for axis_name in ('left', 'bottom'):
            axis = self._plot.getAxis(axis_name)
            axis.setPen(axis_pen)
            axis.setTextPen(axis_text_pen)
            axis.setTickFont(tick_font)
        self._plot.getAxis('left').setTickSpacing(20, 10)
        self._plot.getAxis('bottom').setTickSpacing(2.0, 1.0)

    def _configure_toggle_buttons(self):
        button_font = QtGui.QFont(self._font)
        button_font.setPointSize(max(8, button_font.pointSize() - 1))
        for index, color in enumerate(CHANNEL_COLORS, start=1):
            tx_button = self._toggle_buttons[(index - 1, 'tx')]
            rx_button = self._toggle_buttons[(index - 1, 'rx')]
            self._configure_toggle_button(tx_button, color, button_font)
            self._configure_toggle_button(rx_button, color, button_font)
            tx_button.toggled.connect(lambda checked, channel=index - 1: self._set_series_enabled(channel, 'tx', checked))
            rx_button.toggled.connect(lambda checked, channel=index - 1: self._set_series_enabled(channel, 'rx', checked))

    def _configure_toggle_button(self, button: QtWidgets.QPushButton, color, font: QtGui.QFont):
        dim_color = self._theme.blend(color, (120, 128, 136), 0.72)
        base_fill = 'rgb(37, 45, 54)'
        checked_fill = 'rgb(22, 29, 36)'
        pressed_fill = 'rgb(16, 22, 28)'
        base_border = 'rgb(78, 88, 100)'
        checked_border = 'rgb(96, 108, 120)'
        button.setCheckable(True)
        button.setChecked(True)
        button.setMinimumHeight(30)
        button.setFont(font)
        button.setStyleSheet(
            'QPushButton {'
            f' background-color: {base_fill};'
            ' color: rgb(113, 123, 133);'
            f' border-top: 1px solid {checked_border};'
            f' border-right: 1px solid {base_border};'
            f' border-bottom: 2px solid rgb(12, 17, 22);'
            f' border-left: 4px solid rgb({dim_color[0]}, {dim_color[1]}, {dim_color[2]});'
            ' border-radius: 0px;'
            ' padding: 4px 10px 4px 8px;'
            ' text-align: left;'
            '}'
            'QPushButton:checked {'
            f' background-color: {checked_fill};'
            ' color: rgb(244, 247, 250);'
            f' border-top: 1px solid rgb(42, 50, 58);'
            f' border-right: 1px solid {checked_border};'
            f' border-bottom: 1px solid rgb(112, 124, 136);'
            f' border-left: 4px solid rgb({color[0]}, {color[1]}, {color[2]});'
            ' padding: 5px 10px 3px 8px;'
            '}'
            'QPushButton:pressed {'
            f' background-color: {pressed_fill};'
            ' color: rgb(250, 252, 255);'
            '}'
        )

    def _set_series_enabled(self, channel_index: int, direction: str, checked: bool):
        _ = checked
        _ = direction
        self._apply_curve_visibility()

    def _apply_curve_visibility(self):
        for channel_index in range(MAX_CHANNELS):
            tx_visible = channel_index < self._active_tx_count and self._toggle_buttons[(channel_index, 'tx')].isChecked()
            rx_visible = channel_index < self._active_rx_count and self._toggle_buttons[(channel_index, 'rx')].isChecked()
            self._curve_tx[channel_index].setVisible(tx_visible)
            self._curve_rx[channel_index].setVisible(rx_visible)

    def _apply_rx_curve_style(self):
        for channel_index in range(MAX_CHANNELS):
            pen = self._theme.rx_stale_pen(channel_index) if self._rx_stale else self._theme.rx_live_pen(channel_index)
            self._curve_rx[channel_index].setPen(pen)

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

        tx_ratios = payload_channel_ratios(tx_payload)
        rx_ratios = monitor_channel_ratio_percents(rx_monitor)
        self.set_series_counts(tx_count=tx_payload.channel_count if tx_payload is not None else 0)
        if rx_monitor is not None:
            self.set_series_counts(rx_count=rx_monitor.channel_count)

        for channel_index in range(MAX_CHANNELS):
            tx_ratio = tx_ratios[channel_index]
            rx_ratio = rx_ratios[channel_index]
            self._y_tx[channel_index, self._write_index] = np.nan if tx_ratio is None else np.float32(tx_ratio)
            self._y_rx[channel_index, self._write_index] = np.nan if rx_ratio is None else np.float32(rx_ratio)

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

        for channel_index in range(MAX_CHANNELS):
            if self._curve_tx[channel_index].isVisible():
                self._curve_tx[channel_index].setData(self._x, self._y_tx[channel_index], connect='finite')
            if self._curve_rx[channel_index].isVisible():
                self._curve_rx[channel_index].setData(self._x, self._y_rx[channel_index], connect='finite')
        self._last_refresh = now


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, mock_mode: bool = False):
        super().__init__()
        load_ui(self, 'main_window.ui')
        for name, child_type in MAIN_WINDOW_OBJECTS.items():
            setattr(self, name, require_child(self, child_type, name))

        self._mock_mode = mock_mode
        self._shutdown_done = False
        self._summary_printed = False
        self._last_error_message = None
        self._applied_payload = default_io_payload(channel_count=1)
        self._awaiting_apply_feedback = False
        self._mock_running = False
        self._mock_seq = SEQ_START
        self._mock_index = 0
        self._mock_skip_cycles = 0

        self._event_queue = queue.SimpleQueue()
        self._command_queue = queue.SimpleQueue()
        self._stop_event = threading.Event()
        self._worker = None

        self._lat_stats = RunningStats()
        self._rx_ratio_stats = RunningStats()
        self._latencies = [] if not RUN_FOREVER else None
        self._rx_ratios = [] if not RUN_FOREVER else None
        self._total = 0
        self._success_count = 0
        self._fail_count = 0

        fixed_font = build_fixed_font()
        self.tx_panel = TxPanelView(root=self.txPanel, font=fixed_font)
        self.rx_panel = RxPanelView(root=self.rxPanel, font=fixed_font)
        for name, child_type in PLOT_PANEL_OBJECTS.items():
            setattr(self, name, require_child(self.plotPanel, child_type, name))

        self.graphHintLabel = self.plotPanel.findChild(QtWidgets.QLabel, 'graphHintLabel')
        if self.graphHintLabel is not None:
            self.graphHintLabel.setWordWrap(True)
        toggle_buttons = {}
        for channel_index in range(1, MAX_CHANNELS + 1):
            toggle_buttons[(channel_index - 1, 'tx')] = getattr(self, f'legendTx{channel_index}Button')
            toggle_buttons[(channel_index - 1, 'rx')] = getattr(self, f'legendRx{channel_index}Button')
        self.plot_view = PlotView(self.plotPanel, self.plotHost, toggle_buttons, fixed_font)

        self.tx_panel.connect_actions(self._on_run_clicked, self._on_stop_clicked, self._on_set_clicked)
        if self.rx_panel.adCommandCheckBox is not None:
            self.rx_panel.adCommandCheckBox.toggled.connect(self._on_ad_command_toggled)
        self._handle_event('applied_setpoint', self._applied_payload)
        self._handle_event('run_state', False)

        self._ui_timer = QtCore.QTimer(self)
        self._ui_timer.setInterval(UI_TIMER_MS)
        self._ui_timer.timeout.connect(self._on_ui_timer)
        self._ui_timer.start()

        self._mock_timer = None
        if self._mock_mode:
            self._mock_timer = QtCore.QTimer(self)
            self._mock_timer.setInterval(max(1, int(SAMPLE_PERIOD_S * 1000)))
            self._mock_timer.timeout.connect(self._emit_mock_sample)
            self.statusBar().showMessage('Mock mode enabled')
        else:
            self._worker = SerialWorker(
                event_queue=self._event_queue,
                command_queue=self._command_queue,
                stop_event=self._stop_event,
            )
            self._worker.start()

    def _on_ui_timer(self):
        while True:
            try:
                kind, payload = self._event_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event(kind, payload)
        self.plot_view.refresh()

    def _handle_event(self, kind: str, payload):
        if kind == 'run_state':
            self.tx_panel.update_run_state(payload)
            self.plot_view.set_run_state(payload)
            return

        if kind == 'applied_setpoint':
            self._applied_payload = payload
            self.tx_panel.set_applied_payload(payload, highlight_inputs=self._awaiting_apply_feedback)
            self._awaiting_apply_feedback = False
            self.plot_view.set_series_counts(tx_count=payload.channel_count)
            return

        if kind == 'tx_frame':
            self.tx_panel.update_frame(payload)
            return

        if kind == 'rx_frame':
            self.rx_panel.update_frame(payload, status='OK' if payload is not None else 'TIMEOUT')
            return

        if kind == 'rx_monitor':
            self.rx_panel.update_monitor(payload, status='OK' if payload is not None else 'TIMEOUT')
            self.plot_view.note_rx_monitor(payload)
            return

        if kind == 'sample':
            event = payload
            self._total += 1
            self.plot_view.add_point(event.tx_payload, event.rx_monitor)
            print(format_sample_log(event))

            if event.success:
                self._success_count += 1
                self._lat_stats.add(event.latency_ms)
                if self._latencies is not None:
                    self._latencies.append(event.latency_ms)
            else:
                self._fail_count += 1

            rx_ratio = first_monitor_ratio_percent(event.rx_monitor)
            if rx_ratio is not None:
                self._rx_ratio_stats.add(rx_ratio)
                if self._rx_ratios is not None:
                    self._rx_ratios.append(rx_ratio)
            return

        if kind == 'error':
            self._last_error_message = payload
            print(payload)
            self.statusBar().showMessage(payload)
            return

        if kind == 'done':
            self.tx_panel.update_run_state(False)
            self.plot_view.set_run_state(False)
            self.statusBar().showMessage('Worker stopped')

    def _on_run_clicked(self):
        if self._mock_mode:
            self._mock_running = True
            self.tx_panel.update_run_state(True)
            self.plot_view.set_run_state(True)
            if self._mock_timer is not None:
                self._mock_timer.start()
            return

        self._command_queue.put(('set_running', True))

    def _on_stop_clicked(self):
        if self._mock_mode:
            self._mock_running = False
            self.tx_panel.update_run_state(False)
            self.plot_view.set_run_state(False)
            if self._mock_timer is not None:
                self._mock_timer.stop()
            return

        self._command_queue.put(('set_running', False))

    def _on_set_clicked(self):
        try:
            pending_payload = self.tx_panel.build_pending_payload()
        except ValueError as exc:
            self._awaiting_apply_feedback = False
            self.tx_panel.show_validation_error(str(exc))
            return

        self._awaiting_apply_feedback = True
        if self._mock_mode:
            self._handle_event('applied_setpoint', pending_payload)
            return

        self._command_queue.put(('apply_setpoint', pending_payload))

    def _on_ad_command_toggled(self, checked: bool):
        value = 1 if checked else 0
        if self._mock_mode:
            self._emit_mock_write_var(value)
            return

        self._command_queue.put(('write_var', value))

    def _emit_mock_write_var(self, value: int):
        request = build_write_var_frame(self._mock_seq, WRITE_VAR_READ_AD_FLAG_INDEX, value)
        tx_frame = decode_frame_view(request)
        response = build_write_var_frame(self._mock_seq, WRITE_VAR_READ_AD_FLAG_INDEX, value)
        rx_frame = decode_frame_view(response)

        self._handle_event('tx_frame', tx_frame)
        self._handle_event('rx_frame', rx_frame)
        self._mock_seq = (self._mock_seq + 1) & 0xFF
        if self._mock_running:
            self._mock_skip_cycles = max(self._mock_skip_cycles, 1)

    def _emit_mock_sample(self):
        if self._mock_skip_cycles > 0:
            self._mock_skip_cycles -= 1
            return
        if not self._mock_running:
            return

        self._mock_index += 1
        request_payload = build_io_payload_bytes(self._applied_payload)
        request = build_frame(self._mock_seq, REQUEST_CMD, request_payload)
        tx_frame = decode_frame_view(request)
        tx_payload = decode_io_payload(tx_frame.data)

        response_payload = build_mock_snet_monitor_payload(self._applied_payload)
        response = build_frame(self._mock_seq, RESPONSE_CMD, response_payload)
        rx_frame = decode_frame_view(response)
        rx_monitor = decode_snet_monitor_payload(rx_frame.data)

        self._handle_event('tx_frame', tx_frame)
        self._handle_event('rx_frame', rx_frame)
        self._handle_event('rx_monitor', rx_monitor)
        self._handle_event(
            'sample',
            SampleEvent(
                index=self._mock_index,
                seq=self._mock_seq,
                request_raw=request,
                response_raw=response,
                tx_payload=tx_payload if tx_payload is not None else self._applied_payload,
                rx_monitor=rx_monitor,
                latency_ms=MOCK_LATENCY_MS,
                success=True,
            ),
        )

        self._mock_seq = (self._mock_seq + 1) & 0xFF

    def shutdown(self):
        if self._shutdown_done:
            return

        self._shutdown_done = True
        self._ui_timer.stop()
        if self._mock_timer is not None:
            self._mock_timer.stop()

        if self._worker is not None:
            self._command_queue.put(('set_running', False))
            self._stop_event.set()
            self._worker.join(timeout=2.0)
            self._on_ui_timer()

    def print_summary(self):
        if self._summary_printed:
            return
        self._summary_printed = True

        if self._last_error_message:
            print(self._last_error_message)

        if RUN_FOREVER and self._total == 0:
            return

        print(f'\n[TEST COMPLETE] Processed cycles: {self._total}')
        print()
        print('=' * 60)
        print('  Summary')
        print('=' * 60)
        print(f'  Total   : {self._total}')
        print(f'  Success : {self._success_count}  ({(self._success_count / self._total * 100) if self._total else 0:.1f}%)')
        print(f'  Fail    : {self._fail_count}  ({(self._fail_count / self._total * 100) if self._total else 0:.1f}%)')

        if self._lat_stats.count > 0:
            print('  ' + '-' * 40)
            print('  Latency stats (success only)')
            print(f'    Mean   : {self._lat_stats.mean:7.2f} ms')
            if self._latencies is not None:
                print(f'    Median : {np.median(self._latencies):7.2f} ms')
            else:
                print('    Median : N/A (RUN_FOREVER)')
            print(f'    Min    : {self._lat_stats.min:7.2f} ms')
            print(f'    Max    : {self._lat_stats.max:7.2f} ms')
            lat_stdev = self._lat_stats.stdev()
            if lat_stdev is not None:
                print(f'    StdDev : {lat_stdev:7.2f} ms')

        if self._rx_ratio_stats.count > 0:
            print('  ' + '-' * 40)
            print('  RX CH1 ratio stats (success only)')
            print(f'    Mean   : {self._rx_ratio_stats.mean:7.2f}%')
            if self._rx_ratios is not None:
                print(f'    Median : {np.median(self._rx_ratios):7.2f}%')
            else:
                print('    Median : N/A (RUN_FOREVER)')
            print(f'    Min    : {self._rx_ratio_stats.min:7.2f}%')
            print(f'    Max    : {self._rx_ratio_stats.max:7.2f}%')
            ratio_stdev = self._rx_ratio_stats.stdev()
            if ratio_stdev is not None:
                print(f'    StdDev : {ratio_stdev:7.2f}%')
        print('=' * 60)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
