"""RX panel view — monitor table, frame display."""

from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from ..protocol.codec import (
    format_data_hexdump,
    frame_view_fixed_rows,
)
from ..protocol.constants import FRAME_FIXED_FIELDS, HEX_DUMP_BYTES_PER_LINE, MAX_CHANNELS, PLACEHOLDER
from ..protocol.convert import (
    flow_raw_to_display,
    pressure_raw_to_psi,
    ratio_raw_to_percent,
    temperature_raw_to_celsius,
    valve_raw_to_display,
)
from ..protocol.types import FrameView, SnetChannelMonitor, SnetMonitorSnapshot
from .helpers import (
    configure_plain_text_edit,
    ensure_table_shape,
    find_optional_child,
    require_child,
    set_badge,
)

# Widgets expected inside rxPanel (QGroupBox)
RX_PANEL_OBJECTS = {
    'rxMonitorTable': QtWidgets.QTableWidget,
}

# Widgets inside debugTabWidget (searched from window root)
RX_DEBUG_OBJECTS = {
    'rxFrameTable': QtWidgets.QTableWidget,
    'rxDataDump': QtWidgets.QPlainTextEdit,
}


class RxPanelView:
    def __init__(self, root: QtWidgets.QWidget, debug_root: QtWidgets.QWidget, font: QtGui.QFont):
        self._root = root
        self._font = font
        self._frame_items: dict[str, QtWidgets.QTableWidgetItem] = {}
        self._monitor_items: dict[tuple[int, int], QtWidgets.QTableWidgetItem] = {}
        self._table_enabled_brush: Optional[QtGui.QBrush] = None
        self._table_disabled_brush: Optional[QtGui.QBrush] = None
        self._last_monitor_snapshot: Optional[SnetMonitorSnapshot] = None
        self._last_monitor_status = 'waiting'

        for name, child_type in RX_PANEL_OBJECTS.items():
            setattr(self, name, require_child(self._root, child_type, name))

        # Debug widgets live inside the QTabWidget
        for name, child_type in RX_DEBUG_OBJECTS.items():
            setattr(self, name, require_child(debug_root, child_type, name))

        self.rxControlModeLabel = find_optional_child(self._root, QtWidgets.QLabel, 'rxControlModeLabel')
        self.rxFrameMetaLabel = find_optional_child(debug_root, QtWidgets.QLabel, 'rxFrameMetaLabel')
        self.valveNoCheckBox = find_optional_child(self._root, QtWidgets.QCheckBox, 'valveNoCheckBox')
        self.adCommandCheckBox = find_optional_child(self._root, QtWidgets.QCheckBox, 'adCommandCheckBox')

        if self.rxControlModeLabel is not None:
            self.rxControlModeLabel.setFont(font)

        if self.rxFrameMetaLabel is not None:
            self.rxFrameMetaLabel.setFont(font)

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

        for row in range(4):
            for col in range(MAX_CHANNELS):
                item = table.item(row, col)
                if item is None:
                    item = QtWidgets.QTableWidgetItem(PLACEHOLDER)
                    table.setItem(row, col, item)
                item.setTextAlignment(int(QtCore.Qt.AlignCenter))
                self._monitor_items[(row, col)] = item

    def _configure_frame_table(self):
        table = self.rxFrameTable
        # Now 1 row x 6 columns (horizontal)
        ensure_table_shape(table, 1, len(FRAME_FIXED_FIELDS), 'rxFrameTable')
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

    def _on_valve_display_toggled(self, _checked: bool):
        self._render_monitor(self._last_monitor_snapshot, self._last_monitor_status)

    def _valve_display_inverted(self) -> bool:
        return self.valveNoCheckBox.isChecked() if self.valveNoCheckBox is not None else False

    def update_monitor(self, snet_monitor: Optional[SnetMonitorSnapshot], status: str = PLACEHOLDER):
        self._last_monitor_snapshot = snet_monitor
        self._last_monitor_status = status
        self._render_monitor(snet_monitor, status)

    def _render_monitor(self, snet_monitor: Optional[SnetMonitorSnapshot], status: str):
        if snet_monitor is None:
            if self.rxControlModeLabel is not None:
                self.rxControlModeLabel.setText('PRESS: -- | TEMP: --')
            for col in range(MAX_CHANNELS):
                self._set_monitor_column(col, None, invert_no=self._valve_display_inverted())
            return

        pressure_text = f'{pressure_raw_to_psi(snet_monitor.pressure_raw):.2f} psi'
        temperature_text = f'{temperature_raw_to_celsius(snet_monitor.temperature_raw):.2f}\u00b0C'

        if self.rxControlModeLabel is not None:
            self.rxControlModeLabel.setText(f'PRESS: {pressure_text} | TEMP: {temperature_text}')

        invert_no = self._valve_display_inverted()
        for col in range(MAX_CHANNELS):
            ch = snet_monitor.channels[col] if col < snet_monitor.channel_count else None
            self._set_monitor_column(col, ch, invert_no=invert_no)

    def _set_monitor_column(self, col: int, channel: Optional[SnetChannelMonitor], invert_no: bool):
        if channel is None:
            values = [
                (PLACEHOLDER, ''), (PLACEHOLDER, ''),
                (PLACEHOLDER, ''), (PLACEHOLDER, ''),
            ]
            brush = self._table_disabled_brush
        else:
            flow_display = flow_raw_to_display(channel.flow_raw)
            valve_display = valve_raw_to_display(channel.valve_raw)
            if invert_no:
                valve_display = 5.0 - valve_display
            values = [
                (f'{flow_display:.2f}', f'0x{channel.flow_raw:04X}'),
                (str(channel.ad_raw), f'0x{channel.ad_raw:04X}'),
                (f'{ratio_raw_to_percent(channel.ratio_raw):.2f}', f'0x{channel.ratio_raw:04X}'),
                (f'{valve_display:.2f}', f'0x{channel.valve_raw:04X}'),
            ]
            brush = self._table_enabled_brush

        for row, (text, tooltip) in enumerate(values):
            item = self._monitor_items[(row, col)]
            item.setText(text)
            item.setToolTip(tooltip)
            item.setForeground(brush)

    def update_frame(self, frame_view: Optional[FrameView], status: Optional[str] = None):
        if frame_view is None:
            for item in self._frame_items.values():
                item.setText(PLACEHOLDER)
            self.rxDataDump.setPlainText(PLACEHOLDER)
            if self.rxFrameMetaLabel is not None:
                self.rxFrameMetaLabel.setText(f'Frame: {status or PLACEHOLDER} | LEN: -- | Total: --')
            return

        for field, hex_text in frame_view_fixed_rows(frame_view).items():
            self._frame_items[field].setText(hex_text)
        self.rxDataDump.setPlainText(format_data_hexdump(frame_view.data, HEX_DUMP_BYTES_PER_LINE))
        if self.rxFrameMetaLabel is not None:
            length_text = f'0x{frame_view.length:02X} ({frame_view.length} bytes)'
            total_text = f'{len(frame_view.raw)} bytes'
            self.rxFrameMetaLabel.setText(
                f'Frame: {status or PLACEHOLDER} | LEN: {length_text} | Total: {total_text}'
            )
