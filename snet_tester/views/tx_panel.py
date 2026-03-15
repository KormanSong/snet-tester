"""TX panel view — channel settings, run/stop/set, frame display, preset table."""

import json
import pathlib
from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from ..protocol.codec import (
    build_io_payload_model,
    clamp_channel_count,
    format_channel_summary,
    format_data_hexdump,
    frame_view_fixed_rows,
)
from ..protocol.constants import FRAME_FIXED_FIELDS, HEX_DUMP_BYTES_PER_LINE, MAX_CHANNELS, PLACEHOLDER
from ..protocol.types import FrameView, IoPayload
class _InstantTooltipFilter(QtCore.QObject):
    """Show tooltip instantly on mouse enter, no delay."""
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Enter:
            tip = obj.toolTip()
            if tip:
                pos = obj.mapToGlobal(QtCore.QPoint(obj.width() // 2, -20))
                QtWidgets.QToolTip.showText(pos, tip, obj)
        elif event.type() == QtCore.QEvent.Leave:
            QtWidgets.QToolTip.hideText()
        return False


class _SingleRowScrollTable(QtWidgets.QTableWidget):
    """QTableWidget that scrolls exactly 1 row per wheel tick."""
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - 1)
        elif delta < 0:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + 1)
        event.accept()


from .helpers import (
    configure_plain_text_edit,
    ensure_table_shape,
    find_optional_child,
    require_child,
)

TX_PANEL_OBJECTS = {
    'channelCountCombo': QtWidgets.QComboBox,
    'runButton': QtWidgets.QPushButton,
    'stopButton': QtWidgets.QPushButton,
    'setButton': QtWidgets.QPushButton,
    'ratioInput1': QtWidgets.QLineEdit,
    'ratioInput2': QtWidgets.QLineEdit,
    'ratioInput3': QtWidgets.QLineEdit,
    'ratioInput4': QtWidgets.QLineEdit,
    'ratioInput5': QtWidgets.QLineEdit,
    'ratioInput6': QtWidgets.QLineEdit,
}

TX_DEBUG_OBJECTS = {
    'txFrameTable': QtWidgets.QTableWidget,
    'txDataDump': QtWidgets.QPlainTextEdit,
}

PRESETS_FILE = pathlib.Path(__file__).resolve().parent.parent / 'presets.json'

DEFAULT_PRESETS = [
    [100, 0, 0, 0, 0, 0],
    [0, 100, 0, 0, 0, 0],
    [0, 0, 100, 0, 0, 0],
    [0, 0, 0, 100, 0, 0],
    [20, 20, 20, 20, 20, 0],
]

APPLY_COL = 6  # 7th column for APPLY button

_RATIO_BASE_STYLE = (
    'QLineEdit { color: #000; border: 1px solid #aaa; padding: 1px 2px; }'
    'QLineEdit:disabled { color: #999; background-color: #f0f0f0; border: 1px solid #ccc; }'
    'QLineEdit::placeholder { color: #888; font-weight: bold; }'
)
_RATIO_APPLIED_STYLE = (
    'QLineEdit { color: #000; border: 1px solid #aaa; border-bottom: 3px solid #4CAF50; padding: 1px 2px; }'
    'QLineEdit:disabled { color: #999; background-color: #f0f0f0; border: 1px solid #ccc; }'
    'QLineEdit::placeholder { color: #888; font-weight: bold; }'
)


def _format_ratio(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f'{value:g}'


def _parse_ratio(text: str) -> Optional[float]:
    text = text.strip()
    if not text:
        return None
    try:
        v = float(text)
        return max(0.0, min(100.0, v))
    except ValueError:
        return None


class TxPanelView:
    def __init__(self, root: QtWidgets.QWidget, debug_root: QtWidgets.QWidget, font: QtGui.QFont):
        self._root = root
        self._font = font
        self._running = False
        self._applied_payload: Optional[IoPayload] = None
        self._frame_items: dict[str, QtWidgets.QTableWidgetItem] = {}
        self._set_callback = None

        for name, child_type in TX_PANEL_OBJECTS.items():
            setattr(self, name, require_child(self._root, child_type, name))

        for name, child_type in TX_DEBUG_OBJECTS.items():
            setattr(self, name, require_child(debug_root, child_type, name))

        self.appliedLabel = find_optional_child(self._root, QtWidgets.QLabel, 'appliedLabel')
        self.txFrameMetaLabel = find_optional_child(debug_root, QtWidgets.QLabel, 'txFrameMetaLabel')

        self._ratio_inputs: list[QtWidgets.QLineEdit] = [
            getattr(self, f'ratioInput{i}') for i in range(1, MAX_CHANNELS + 1)
        ]

        self.channelCountCombo.clear()
        self.channelCountCombo.addItems([str(i) for i in range(1, MAX_CHANNELS + 1)])
        self.channelCountCombo.currentIndexChanged.connect(self._on_channel_count_changed)

        # Fix tab order: CH1 → CH2 → CH3 → CH4 → CH5 → CH6
        for i in range(len(self._ratio_inputs) - 1):
            QtWidgets.QWidget.setTabOrder(self._ratio_inputs[i], self._ratio_inputs[i + 1])

        validator = QtGui.QDoubleValidator(0.0, 100.0, 2)
        validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
        for inp in self._ratio_inputs:
            inp.setValidator(validator)
            inp.setFont(font)
            inp.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            inp.setStyleSheet(_RATIO_BASE_STYLE)
            inp.textChanged.connect(self._on_ratio_text_changed)
            inp.installEventFilter(self._root)

        # Instant tooltip on hover
        self._tooltip_filter = _InstantTooltipFilter()
        for inp in self._ratio_inputs:
            inp.installEventFilter(self._tooltip_filter)

        if self.appliedLabel is not None:
            self.appliedLabel.setFont(font)
        if self.txFrameMetaLabel is not None:
            self.txFrameMetaLabel.setFont(font)

        # Preset table
        self.presetTable = find_optional_child(self._root, QtWidgets.QTableWidget, 'presetTable')
        self.addPresetButton = find_optional_child(self._root, QtWidgets.QPushButton, 'addPresetButton')
        self.delPresetButton = find_optional_child(self._root, QtWidgets.QPushButton, 'delPresetButton')

        if self.addPresetButton is not None:
            self.addPresetButton.clicked.connect(self._on_add_preset)
        if self.delPresetButton is not None:
            self.delPresetButton.clicked.connect(self._on_del_preset)

        configure_plain_text_edit(self.txDataDump, font)
        self._configure_frame_table()
        self._update_channel_input_state()
        self.refresh_pending_previews()
        self._init_preset_table()

    def _configure_frame_table(self):
        table = self.txFrameTable
        ensure_table_shape(table, 1, len(FRAME_FIXED_FIELDS), 'txFrameTable')
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setFocusPolicy(QtCore.Qt.NoFocus)
        table.setWordWrap(False)
        table.setFont(self._font)
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)

        for col, field in enumerate(FRAME_FIXED_FIELDS):
            item = table.item(0, col)
            if item is None:
                item = QtWidgets.QTableWidgetItem(PLACEHOLDER)
                table.setItem(0, col, item)
            item.setTextAlignment(int(QtCore.Qt.AlignCenter))
            self._frame_items[field] = item

    def connect_actions(self, run_cb, stop_cb, set_cb):
        self.runButton.clicked.connect(run_cb)
        self.stopButton.clicked.connect(stop_cb)
        self.setButton.clicked.connect(set_cb)
        self._set_callback = set_cb

    # --- Preset table ---

    def _init_preset_table(self):
        if self.presetTable is None:
            return
        table = self.presetTable
        self._last_applied_row = -1

        # Compact font
        preset_font = QtGui.QFont(self._font)
        preset_font.setPointSize(8)
        table.setFont(preset_font)

        # Hide headers, tight row height
        table.horizontalHeader().hide()
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(18)
        table.verticalHeader().setMinimumSectionSize(18)

        # Minimal cell padding via stylesheet
        table.setStyleSheet('QTableWidget::item { padding: 0px 2px; }')

        # Stretch CH columns, fix APPLY column width
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(APPLY_COL, QtWidgets.QHeaderView.Fixed)
        table.setColumnWidth(APPLY_COL, 30)

        # Scroll: 1 row per wheel tick
        table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerItem)
        table.wheelEvent = lambda event: _SingleRowScrollTable.wheelEvent(table, event)

        presets = self._load_presets()
        for values in presets:
            self._add_preset_row(values)

        table.itemChanged.connect(self._on_preset_cell_changed)

    def _add_preset_row(self, values: list[float]):
        if self.presetTable is None:
            return
        table = self.presetTable
        table.blockSignals(True)
        row = table.rowCount()
        table.insertRow(row)

        preset_font = table.font()
        for col in range(MAX_CHANNELS):
            v = values[col] if col < len(values) else 0.0
            item = QtWidgets.QTableWidgetItem(_format_ratio(v))
            item.setTextAlignment(int(QtCore.Qt.AlignCenter))
            item.setFont(preset_font)
            table.setItem(row, col, item)
        table.blockSignals(False)

        btn = QtWidgets.QPushButton('>')
        btn.setFont(preset_font)
        btn.setMaximumWidth(28)
        btn.setMaximumHeight(18)
        btn.setStyleSheet('QPushButton { padding: 0px 2px; margin: 0px; }')
        btn.clicked.connect(lambda _checked: self._on_preset_apply_by_button(btn))
        table.setCellWidget(row, APPLY_COL, btn)

    def _on_preset_apply_by_button(self, btn: QtWidgets.QPushButton):
        """Find the row of the button and apply that preset."""
        if self.presetTable is None:
            return
        for row in range(self.presetTable.rowCount()):
            if self.presetTable.cellWidget(row, APPLY_COL) is btn:
                self._on_preset_apply(row)
                return

    def _on_preset_apply(self, row: int):
        if self.presetTable is None:
            return
        table = self.presetTable
        if row < 0 or row >= table.rowCount():
            return
        active = self._selected_channel_count()

        for col in range(active):
            item = table.item(row, col)
            if item is not None:
                parsed = _parse_ratio(item.text())
                if parsed is not None:
                    self._ratio_inputs[col].setText(_format_ratio(parsed))

        # Highlight applied row
        self._highlight_preset_row(row)

        # Auto SET
        if self._set_callback is not None:
            self._set_callback()

    def _highlight_preset_row(self, active_row: int):
        if self.presetTable is None:
            return
        table = self.presetTable
        table.blockSignals(True)
        applied_bg = QtGui.QBrush(QtGui.QColor(200, 230, 200))  # light green
        default_bg = QtGui.QBrush(QtGui.QColor(255, 255, 255))
        for row in range(table.rowCount()):
            bg = applied_bg if row == active_row else default_bg
            for col in range(MAX_CHANNELS):
                item = table.item(row, col)
                if item is not None:
                    item.setBackground(bg)
        table.clearSelection()
        table.blockSignals(False)
        self._last_applied_row = active_row

    def _on_preset_cell_changed(self, item: QtWidgets.QTableWidgetItem):
        if item.column() < MAX_CHANNELS:
            self._save_presets()

    def _on_add_preset(self):
        self._add_preset_row([0.0] * MAX_CHANNELS)
        self._save_presets()

    def _on_del_preset(self):
        if self.presetTable is None:
            return
        rows = set(idx.row() for idx in self.presetTable.selectedIndexes())
        for row in sorted(rows, reverse=True):
            self.presetTable.removeRow(row)
        self._save_presets()

    def _save_presets(self):
        if self.presetTable is None:
            return
        table = self.presetTable
        presets = []
        for row in range(table.rowCount()):
            values = []
            for col in range(MAX_CHANNELS):
                item = table.item(row, col)
                parsed = _parse_ratio(item.text()) if item is not None else 0.0
                values.append(parsed if parsed is not None else 0.0)
            presets.append(values)
        try:
            PRESETS_FILE.write_text(json.dumps(presets, indent=2), encoding='utf-8')
        except OSError:
            pass

    def _load_presets(self) -> list[list[float]]:
        try:
            data = json.loads(PRESETS_FILE.read_text(encoding='utf-8'))
            if isinstance(data, list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return [row[:] for row in DEFAULT_PRESETS]

    # --- Channel count ---

    def _selected_channel_count(self) -> int:
        return clamp_channel_count(int(self.channelCountCombo.currentText()))

    def _on_channel_count_changed(self, *_args):
        self._update_channel_input_state()
        self.refresh_pending_previews()
        # Reset highlight — not applied yet until SET is clicked
        self.channelCountCombo.setStyleSheet('')
        self._clear_ratio_highlights()

    def _update_channel_input_state(self):
        active = self._selected_channel_count()
        for i, inp in enumerate(self._ratio_inputs):
            enabled = i < active
            inp.setEnabled(enabled)
            if not enabled:
                inp.setToolTip('')
                inp.setStyleSheet(_RATIO_BASE_STYLE)

    def _on_ratio_text_changed(self, *_args):
        self._clear_ratio_highlights()
        self.refresh_pending_previews()

    # --- Ratio preview ---

    def refresh_pending_previews(self, *_args):
        active = self._selected_channel_count()
        for i, inp in enumerate(self._ratio_inputs):
            if i >= active:
                inp.setToolTip('')
                continue
            parsed = _parse_ratio(inp.text())
            if parsed is None:
                inp.setToolTip('')
                continue
            payload = build_io_payload_model(channel_count=1, ratio_percents=[parsed])
            inp.setToolTip(f'0x{payload.channels[0].ratio_raw:04X}')

    def build_pending_payload(self) -> IoPayload:
        active = self._selected_channel_count()
        ratios = []
        for i in range(active):
            parsed = _parse_ratio(self._ratio_inputs[i].text())
            if parsed is None:
                raise ValueError(f'CH{i + 1} ratio is empty or invalid')
            ratios.append(parsed)
        return build_io_payload_model(channel_count=active, ratio_percents=ratios)

    # --- State display ---

    def show_validation_error(self, message: str):
        pass

    def update_run_state(self, running: bool):
        self._running = running
        self.runButton.setEnabled(not running)
        self.stopButton.setEnabled(running)

    def set_applied_payload(self, io_payload: IoPayload, highlight_inputs: bool = True):
        self._applied_payload = io_payload
        if self.appliedLabel is not None:
            self.appliedLabel.setText(f'Applied: {format_channel_summary(io_payload)}')
        if highlight_inputs:
            self._highlight_ratio_inputs(io_payload.channel_count)
            self.channelCountCombo.setStyleSheet(
                'QComboBox { border: 1px solid #aaa; border-bottom: 3px solid #4CAF50; padding: 1px 2px; }'
            )
        self.update_run_state(self._running)

    def _highlight_ratio_inputs(self, active_count: int):
        for i, inp in enumerate(self._ratio_inputs):
            inp.setStyleSheet(_RATIO_APPLIED_STYLE if i < active_count else _RATIO_BASE_STYLE)

    def _clear_ratio_highlights(self):
        for inp in self._ratio_inputs:
            inp.setStyleSheet(_RATIO_BASE_STYLE)

    # --- Frame display ---

    def update_frame(self, frame_view: Optional[FrameView], status: Optional[str] = None):
        if frame_view is None:
            for item in self._frame_items.values():
                item.setText(PLACEHOLDER)
            self.txDataDump.setPlainText(PLACEHOLDER)
            if self.txFrameMetaLabel is not None:
                self.txFrameMetaLabel.setText('Frame: LEN: -- | Total: --')
            return

        for field, hex_text in frame_view_fixed_rows(frame_view).items():
            self._frame_items[field].setText(hex_text)
        self.txDataDump.setPlainText(format_data_hexdump(frame_view.data, HEX_DUMP_BYTES_PER_LINE))
        if self.txFrameMetaLabel is not None:
            length_text = f'0x{frame_view.length:02X} ({frame_view.length} bytes)'
            total_text = f'{len(frame_view.raw)} bytes'
            self.txFrameMetaLabel.setText(f'Frame: LEN: {length_text} | Total: {total_text}')
