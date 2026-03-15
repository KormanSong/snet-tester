"""TX panel view — channel settings, run/stop/set, frame display, quick set."""

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
    'ratioRaw1': QtWidgets.QLabel,
    'ratioRaw2': QtWidgets.QLabel,
    'ratioRaw3': QtWidgets.QLabel,
    'ratioRaw4': QtWidgets.QLabel,
    'ratioRaw5': QtWidgets.QLabel,
    'ratioRaw6': QtWidgets.QLabel,
}

TX_DEBUG_OBJECTS = {
    'txFrameTable': QtWidgets.QTableWidget,
    'txDataDump': QtWidgets.QPlainTextEdit,
}


def _format_ratio(value: float) -> str:
    """Format ratio: 30 -> '30', 33.3 -> '33.3', 0 -> '0'."""
    if value == int(value):
        return str(int(value))
    return f'{value:g}'


def _parse_ratio(text: str) -> Optional[float]:
    """Parse ratio text, return None if invalid."""
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

        for name, child_type in TX_PANEL_OBJECTS.items():
            setattr(self, name, require_child(self._root, child_type, name))

        for name, child_type in TX_DEBUG_OBJECTS.items():
            setattr(self, name, require_child(debug_root, child_type, name))

        self.txStatusLabel = find_optional_child(self._root, QtWidgets.QLabel, 'txStatusLabel')
        self.appliedLabel = find_optional_child(self._root, QtWidgets.QLabel, 'appliedLabel')
        self.txFrameMetaLabel = find_optional_child(debug_root, QtWidgets.QLabel, 'txFrameMetaLabel')

        self._ratio_inputs: list[QtWidgets.QLineEdit] = [
            getattr(self, f'ratioInput{i}') for i in range(1, MAX_CHANNELS + 1)
        ]
        self._ratio_raw_labels: list[QtWidgets.QLabel] = [
            getattr(self, f'ratioRaw{i}') for i in range(1, MAX_CHANNELS + 1)
        ]

        self.channelCountCombo.clear()
        self.channelCountCombo.addItems([str(i) for i in range(1, MAX_CHANNELS + 1)])
        self.channelCountCombo.currentIndexChanged.connect(self._on_channel_count_changed)

        validator = QtGui.QDoubleValidator(0.0, 100.0, 2)
        validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
        for inp in self._ratio_inputs:
            inp.setValidator(validator)
            inp.setFont(font)
            inp.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            inp.textChanged.connect(self.refresh_pending_previews)

        for lbl in self._ratio_raw_labels:
            lbl.setFont(font)
            lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        if self.txStatusLabel is not None:
            self.txStatusLabel.setFont(font)
        if self.appliedLabel is not None:
            self.appliedLabel.setFont(font)
        if self.txFrameMetaLabel is not None:
            self.txFrameMetaLabel.setFont(font)

        # Quick Set widgets (optional — searched from txPanel root)
        self.allRatioInput = find_optional_child(self._root, QtWidgets.QLineEdit, 'allRatioInput')
        self.applyAllButton = find_optional_child(self._root, QtWidgets.QPushButton, 'applyAllButton')
        self.preset0Button = find_optional_child(self._root, QtWidgets.QPushButton, 'preset0Button')
        self.preset25Button = find_optional_child(self._root, QtWidgets.QPushButton, 'preset25Button')
        self.preset50Button = find_optional_child(self._root, QtWidgets.QPushButton, 'preset50Button')
        self.preset75Button = find_optional_child(self._root, QtWidgets.QPushButton, 'preset75Button')
        self.preset100Button = find_optional_child(self._root, QtWidgets.QPushButton, 'preset100Button')

        if self.allRatioInput is not None:
            self.allRatioInput.setValidator(validator)
            self.allRatioInput.setFont(font)
        if self.applyAllButton is not None:
            self.applyAllButton.clicked.connect(self._on_apply_all_clicked)
        for value, btn_name in [(0, 'preset0Button'), (25, 'preset25Button'), (50, 'preset50Button'),
                                 (75, 'preset75Button'), (100, 'preset100Button')]:
            btn = getattr(self, btn_name)
            if btn is not None:
                btn.clicked.connect(lambda _checked, v=value: self._on_preset_clicked(v))

        configure_plain_text_edit(self.txDataDump, font)
        self._configure_frame_table()
        self._update_channel_input_state()
        self.refresh_pending_previews()

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

    def _selected_channel_count(self) -> int:
        return clamp_channel_count(int(self.channelCountCombo.currentText()))

    def _on_channel_count_changed(self, *_args):
        self._update_channel_input_state()
        self.refresh_pending_previews()

    def _update_channel_input_state(self):
        active = self._selected_channel_count()
        for i, inp in enumerate(self._ratio_inputs):
            enabled = i < active
            inp.setEnabled(enabled)
            self._ratio_raw_labels[i].setEnabled(enabled)
            if not enabled:
                self._ratio_raw_labels[i].setText(PLACEHOLDER)

    # --- Quick Set ---

    def _on_preset_clicked(self, value: float):
        text = _format_ratio(value)
        active = self._selected_channel_count()
        for i in range(active):
            self._ratio_inputs[i].setText(text)

    def _on_apply_all_clicked(self):
        if self.allRatioInput is None:
            return
        parsed = _parse_ratio(self.allRatioInput.text())
        if parsed is None:
            return
        text = _format_ratio(parsed)
        active = self._selected_channel_count()
        for i in range(active):
            self._ratio_inputs[i].setText(text)

    # --- Ratio preview ---

    def refresh_pending_previews(self, *_args):
        active = self._selected_channel_count()
        for i, inp in enumerate(self._ratio_inputs):
            if i >= active:
                self._ratio_raw_labels[i].setText(PLACEHOLDER)
                continue
            parsed = _parse_ratio(inp.text())
            if parsed is None:
                self._ratio_raw_labels[i].setText(PLACEHOLDER)
                continue
            payload = build_io_payload_model(channel_count=1, ratio_percents=[parsed])
            self._ratio_raw_labels[i].setText(f'0x{payload.channels[0].ratio_raw:04X}')

    def build_pending_payload(self) -> IoPayload:
        active = self._selected_channel_count()
        ratios = []
        for i in range(active):
            parsed = _parse_ratio(self._ratio_inputs[i].text())
            if parsed is None:
                raise ValueError(f'CH{i + 1} ratio is empty or invalid')
            ratios.append(parsed)
        return build_io_payload_model(channel_count=active, ratio_percents=ratios)

    def show_validation_error(self, message: str):
        if self.txStatusLabel is not None:
            self.txStatusLabel.setText(f"State: {'RUN' if self._running else 'STOP'} | {message}")

    def update_run_state(self, running: bool):
        self._running = running
        if self.txStatusLabel is not None and self._applied_payload is not None:
            self.txStatusLabel.setText(
                f"State: {'RUN' if running else 'STOP'} | Applied Ch.: {self._applied_payload.channel_count}"
            )
        self.runButton.setEnabled(not running)
        self.stopButton.setEnabled(running)

    def set_applied_payload(self, io_payload: IoPayload, highlight_inputs: bool = True):
        self._applied_payload = io_payload
        if self.appliedLabel is not None:
            self.appliedLabel.setText(f'Applied: {format_channel_summary(io_payload)}')
        self.update_run_state(self._running)

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
