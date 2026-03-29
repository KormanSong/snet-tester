"""RX panel view -- monitor table, frame display.

PySide6 port: import change only (PyQt5 -> PySide6).
"""

from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..protocol.codec import (
    format_data_hexdump,
    frame_view_fixed_rows,
)
from ..protocol.constants import (
    FRAME_FIXED_FIELDS,
    FULL_OPEN_VALUE_SCALE,
    HEX_DUMP_BYTES_PER_LINE,
    MAX_CHANNELS,
    PLACEHOLDER,
)
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

        self.pressValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'pressValueLabel')
        self.tempValueLabel = find_optional_child(self._root, QtWidgets.QLabel, 'tempValueLabel')
        self.rxFrameMetaLabel = find_optional_child(debug_root, QtWidgets.QLabel, 'rxFrameMetaLabel')
        self.valveNoCheckBox = find_optional_child(self._root, QtWidgets.QCheckBox, 'valveNoCheckBox')
        self.adCommandCheckBox = find_optional_child(self._root, QtWidgets.QCheckBox, 'adCommandCheckBox')
        self.fullOpenControlCheckBox = find_optional_child(self._root, QtWidgets.QCheckBox, 'fullOpenControlCheckBox')
        self.fullOpenValueEdit = find_optional_child(self._root, QtWidgets.QLineEdit, 'fullOpenValueEdit')
        self.fullOpenApplyButton = find_optional_child(self._root, QtWidgets.QPushButton, 'fullOpenApplyButton')

        if self.valveNoCheckBox is not None:
            self.valveNoCheckBox.toggled.connect(self._on_valve_display_toggled)

        configure_plain_text_edit(self.rxDataDump, font)
        self._configure_full_open_controls()
        self._configure_monitor_table()
        self._configure_frame_table()
        self.update_monitor(None, status='waiting')
        self.update_frame(None, status='waiting')

    def _configure_full_open_controls(self):
        if self.fullOpenValueEdit is not None:
            validator = QtGui.QDoubleValidator(0.0, 9999.999, 3, self.fullOpenValueEdit)
            validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
            self.fullOpenValueEdit.setValidator(validator)
            # alignment, placeholderText, and toolTip are set in .ui

        # fullOpenApplyButton toolTip is set in .ui

    def _format_full_open_value(self, raw_value: int) -> str:
        text = f'{raw_value / FULL_OPEN_VALUE_SCALE:.3f}'.rstrip('0').rstrip('.')
        return text if '.' in text else f'{text}.0'

    def set_full_open_value_raw(self, raw_value: Optional[int]):
        if self.fullOpenValueEdit is None:
            return

        self.fullOpenValueEdit.blockSignals(True)
        if raw_value is None:
            self.fullOpenValueEdit.clear()
        else:
            self.fullOpenValueEdit.setText(self._format_full_open_value(raw_value))
        self.fullOpenValueEdit.blockSignals(False)

    def build_full_open_raw_value(self) -> int:
        if self.fullOpenValueEdit is None:
            raise ValueError('풀오픈 입력창을 찾을 수 없습니다.')

        text = self.fullOpenValueEdit.text().strip()
        if not text:
            raise ValueError('풀오픈 값을 입력하세요.')

        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError('풀오픈 값 형식이 올바르지 않습니다.') from exc

        if value < 0.0:
            raise ValueError('풀오픈 값은 0 이상이어야 합니다.')

        return int(round(value * FULL_OPEN_VALUE_SCALE))

    def _configure_monitor_table(self):
        table = self.rxMonitorTable
        ensure_table_shape(table, 4, MAX_CHANNELS, 'rxMonitorTable')
        # editTriggers, selectionMode, wordWrap, font (9pt), focusPolicy,
        # and vertical section sizes are set in .ui
        # ui-override: Designer 미지원 -- QHeaderView.Stretch는 .ui XML에 표현 불가
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        palette = table.palette()
        self._table_enabled_brush = QtGui.QBrush(palette.color(QtGui.QPalette.Text))
        self._table_disabled_brush = QtGui.QBrush(palette.color(QtGui.QPalette.Disabled, QtGui.QPalette.Text))

        # ui-dynamic: 테이블 아이템 런타임 생성, textAlignment 동적 설정
        for row in range(4):
            for col in range(MAX_CHANNELS):
                item = table.item(row, col)
                if item is None:
                    item = QtWidgets.QTableWidgetItem(PLACEHOLDER)
                    table.setItem(row, col, item)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                self._monitor_items[(row, col)] = item

    def _configure_frame_table(self):
        table = self.rxFrameTable
        # Now 1 row x 6 columns (horizontal)
        ensure_table_shape(table, 1, len(FRAME_FIXED_FIELDS), 'rxFrameTable')
        # editTriggers, selectionMode, focusPolicy, wordWrap are set in .ui
        # ui-override: Designer 미지원 -- QHeaderView.Stretch
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        # ui-dynamic: 프레임 테이블 아이템 런타임 생성
        for col, field in enumerate(FRAME_FIXED_FIELDS):
            item = table.item(0, col)
            if item is None:
                item = QtWidgets.QTableWidgetItem(PLACEHOLDER)
                table.setItem(0, col, item)
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self._frame_items[field] = item

    def _on_valve_display_toggled(self, _checked: bool):
        self._render_monitor(self._last_monitor_snapshot, self._last_monitor_status)

    def _valve_display_inverted(self) -> bool:
        return self.valveNoCheckBox.isChecked() if self.valveNoCheckBox is not None else False

    def update_monitor(self, snet_monitor: Optional[SnetMonitorSnapshot], status: str = PLACEHOLDER):
        self._last_monitor_snapshot = snet_monitor
        self._last_monitor_status = status
        self._render_monitor(snet_monitor, status)

    def _update_info_display(self, pressure: str, temperature: str):
        if self.pressValueLabel is not None:
            self.pressValueLabel.setText(pressure)
        if self.tempValueLabel is not None:
            self.tempValueLabel.setText(temperature)
            try:
                kelvin = float(temperature) + 273.15
                self.tempValueLabel.setToolTip(f'{kelvin:.2f} K')
            except ValueError:
                self.tempValueLabel.setToolTip('')

    def _render_monitor(self, snet_monitor: Optional[SnetMonitorSnapshot], status: str):
        if snet_monitor is None:
            self._update_info_display(PLACEHOLDER, PLACEHOLDER)
            for col in range(MAX_CHANNELS):
                self._set_monitor_column(col, None, invert_no=self._valve_display_inverted())
            return

        pressure_text = f'{pressure_raw_to_psi(snet_monitor.pressure_raw):.2f}'
        temperature_text = f'{temperature_raw_to_celsius(snet_monitor.temperature_raw):.2f}'

        self._update_info_display(pressure_text, temperature_text)

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
            ratio_val = ratio_raw_to_percent(channel.ratio_raw)
            ratio_text = str(int(ratio_val)) if ratio_val == int(ratio_val) else f'{ratio_val:.2f}'
            values = [
                (f'{flow_display:.2f}', f'0x{channel.flow_raw:04X}'),
                (str(channel.ad_raw), f'0x{channel.ad_raw:04X}'),
                (ratio_text, f'0x{channel.ratio_raw:04X}'),
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
