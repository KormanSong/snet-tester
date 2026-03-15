"""TX panel view — channel settings, run/stop/set, frame display."""

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
    build_line_edit_style,
    configure_plain_text_edit,
    configure_value_label,
    ensure_table_shape,
    find_optional_child,
    require_child,
    set_badge,
)

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


class TxPanelView:
    INPUT_STYLE_DEFAULT = build_line_edit_style('#FFFFFF')
    INPUT_STYLE_APPLIED = build_line_edit_style('#E8F5E9', '#81C784')
    INPUT_STYLE_DISABLED = build_line_edit_style('#F1F1F1', '#D0D0D0')

    def __init__(self, root: QtWidgets.QWidget, font: QtGui.QFont):
        self._root = root
        self._font = font
        self._running = False
        self._applied_payload: Optional[IoPayload] = None
        self._highlight_applied_inputs = False
        self._frame_items: dict[str, QtWidgets.QTableWidgetItem] = {}

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

        self._ratio_inputs: list[QtWidgets.QLineEdit] = [
            getattr(self, f'ratioInput{i}') for i in range(1, MAX_CHANNELS + 1)
        ]
        self._ratio_raw_labels: list[QtWidgets.QLabel] = [
            getattr(self, f'ratioRaw{i}') for i in range(1, MAX_CHANNELS + 1)
        ]

        self.channelCountCombo.clear()
        self.channelCountCombo.addItems([str(i) for i in range(1, MAX_CHANNELS + 1)])
        self.channelCountCombo.currentIndexChanged.connect(self._on_channel_count_changed)

        for inp in self._ratio_inputs:
            validator = QtGui.QDoubleValidator(0.0, 100.0, 3, inp)
            validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
            inp.setValidator(validator)
            inp.setFont(font)
            inp.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            inp.textChanged.connect(self.refresh_pending_previews)

        for lbl in self._ratio_raw_labels:
            lbl.setFont(font)
            lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        for attr in (
            'txStateValueLabel', 'txChannelsValueLabel', 'txLastResultValueLabel',
            'txFrameSeqValueLabel', 'txFrameCmdValueLabel', 'txFrameLenValueLabel',
            'txFrameTotalValueLabel',
        ):
            label = getattr(self, attr)
            if label is not None:
                configure_value_label(label, font)

        for attr in ('txStatusLabel', 'appliedLabel', 'txFrameMetaLabel'):
            label = getattr(self, attr)
            if label is not None:
                label.setFont(font)

        configure_plain_text_edit(self.txDataDump, font)
        self._configure_frame_table()
        self._update_channel_input_state()
        self.refresh_pending_previews()

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

        for row, field in enumerate(FRAME_FIXED_FIELDS):
            item = table.item(row, 0)
            if item is None:
                item = QtWidgets.QTableWidgetItem(PLACEHOLDER)
                table.setItem(row, 0, item)
            item.setTextAlignment(int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter))
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
                inp.setStyleSheet(self.INPUT_STYLE_DISABLED)
        self._refresh_input_highlights()

    def _input_matches_applied(self, ch_idx: int) -> bool:
        if self._applied_payload is None or ch_idx >= self._applied_payload.channel_count:
            return False
        text = self._ratio_inputs[ch_idx].text().strip()
        if not text:
            return False
        try:
            pending = build_io_payload_model(channel_count=1, ratio_percents=[float(text)]).channels[0]
        except ValueError:
            return False
        return pending.ratio_raw == self._applied_payload.channels[ch_idx].ratio_raw

    def _refresh_input_highlights(self):
        active = self._selected_channel_count()
        for i, inp in enumerate(self._ratio_inputs):
            if i >= active:
                inp.setStyleSheet(self.INPUT_STYLE_DISABLED)
            elif self._highlight_applied_inputs and self._input_matches_applied(i):
                inp.setStyleSheet(self.INPUT_STYLE_APPLIED)
            else:
                inp.setStyleSheet(self.INPUT_STYLE_DEFAULT)

    def refresh_pending_previews(self, *_args):
        active = self._selected_channel_count()
        for i, inp in enumerate(self._ratio_inputs):
            if i >= active:
                self._ratio_raw_labels[i].setText(PLACEHOLDER)
                continue
            text = inp.text().strip()
            if not text:
                self._ratio_raw_labels[i].setText(PLACEHOLDER)
                continue
            try:
                payload = build_io_payload_model(channel_count=1, ratio_percents=[float(text)])
            except ValueError:
                self._ratio_raw_labels[i].setText(PLACEHOLDER)
                continue
            self._ratio_raw_labels[i].setText(f'0x{payload.channels[0].ratio_raw:04X}')
        self._refresh_input_highlights()

    def build_pending_payload(self) -> IoPayload:
        active = self._selected_channel_count()
        ratios = []
        for i in range(active):
            text = self._ratio_inputs[i].text().strip()
            if not text:
                raise ValueError(f'CH{i + 1} ratio is empty')
            ratios.append(float(text))
        return build_io_payload_model(channel_count=active, ratio_percents=ratios)

    def show_validation_error(self, message: str):
        if self.txLastResultValueLabel is not None:
            set_badge(self.txLastResultValueLabel, 'INPUT ERROR', 'warn')
        if self.txStatusLabel is not None:
            self.txStatusLabel.setText(f"State: {'RUN' if self._running else 'STOP'} | {message}")

    def update_run_state(self, running: bool):
        self._running = running
        if self.txStateValueLabel is not None:
            set_badge(self.txStateValueLabel, 'RUN' if running else 'STOP', 'run' if running else 'stop')
        if self.txChannelsValueLabel is not None and self._applied_payload is not None:
            self.txChannelsValueLabel.setText(str(self._applied_payload.channel_count))
        if self.txStatusLabel is not None and self._applied_payload is not None:
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

    def update_frame(self, frame_view: Optional[FrameView], status: Optional[str] = None):
        if frame_view is None:
            for item in self._frame_items.values():
                item.setText(PLACEHOLDER)
            self.txDataDump.setPlainText(PLACEHOLDER)
            if self.txFrameSeqValueLabel is not None:
                self.txFrameSeqValueLabel.setText(PLACEHOLDER)
            if self.txFrameCmdValueLabel is not None:
                self.txFrameCmdValueLabel.setText(PLACEHOLDER)
            if self.txFrameLenValueLabel is not None:
                self.txFrameLenValueLabel.setText(PLACEHOLDER)
            if self.txFrameTotalValueLabel is not None:
                self.txFrameTotalValueLabel.setText(PLACEHOLDER)
            if self.txFrameMetaLabel is not None:
                self.txFrameMetaLabel.setText('Frame: LEN: -- | Total: --')
            if self.txLastResultValueLabel is not None:
                set_badge(self.txLastResultValueLabel, (status or 'WAIT').upper(), 'neutral')
            return

        for field, hex_text in frame_view_fixed_rows(frame_view).items():
            self._frame_items[field].setText(hex_text)
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
