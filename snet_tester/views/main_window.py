"""Main window -- assembles panels, routes events, manages worker lifecycle.

v2 core integration: uses typed dataclass events/commands from snet_tester2
instead of v1 string-based ('kind', payload) tuples.  MockTransport replaces
the old QTimer-based mock sample generation.
"""

import queue
import threading
import time
from typing import Optional

import numpy as np
import serial.tools.list_ports
from PyQt5 import QtCore, QtWidgets

from ..config import SerialConfig
from ..protocol.codec import (
    default_io_payload,
    first_monitor_ratio_percent,
    format_sample_log,
)
from ..protocol.constants import (
    FULL_OPEN_VALUE_VAR_INDEX,
    MAX_CHANNELS,
    SAMPLE_PERIOD_S,
    WRITE_VAR_FULL_OPEN_CONTROL_FLAG_INDEX,
    WRITE_VAR_MODE_FLAG_INDEX,
    WRITE_VAR_READ_AD_FLAG_INDEX,
)
from ..protocol.types import IoPayload, SampleEvent, SnetMonitorSnapshot

from snet_tester2.comm.worker import SerialWorker as V2SerialWorker
from snet_tester2.comm.commands import (
    ApplySetpointCommand,
    BrooksGetKpCommand,
    ReadVarCommand,
    SetRunningCommand,
    WriteVarCommand,
)
from snet_tester2.comm.events import (
    AppliedSetpointEvent,
    BrooksKpEvent,
    ErrorEvent,
    RxFrameEvent,
    RxMonitorEvent,
    RunStateEvent,
    SampleReceivedEvent,
    TxFrameEvent,
    VarValueEvent,
    WorkerDoneEvent,
)
from snet_tester2.config import WorkerConfig
from snet_tester2.transport.mock import MockTransport
from snet_tester2.transport.serial import SerialTransport

from .helpers import build_fixed_font, load_ui, require_child, find_optional_child
from .tx_panel import TxPanelView
from .rx_panel import RxPanelView
from .plot_view import PlotView
from .response_tracker import ResponseTimeTracker

UI_TIMER_MS = 20
MAIN_WINDOW_START_SIZE = (1280, 820)
MAIN_WINDOW_MIN_SIZE = (1120, 760)
SIDE_PANEL_WIDTH = 455

MAIN_WINDOW_OBJECTS = {
    'txPanel': QtWidgets.QWidget,
    'rxPanel': QtWidgets.QWidget,
    'plotPanel': QtWidgets.QGroupBox,
    'debugTabWidget': QtWidgets.QTabWidget,
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


class RunningStats:
    def __init__(self):
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.min = None
        self.max = None

    def add(self, value: float):
        self.count += 1
        if self.min is None or value < self.min:
            self.min = value
        if self.max is None or value > self.max:
            self.max = value
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    def stdev(self) -> Optional[float]:
        if self.count < 2:
            return None
        return (self.m2 / (self.count - 1)) ** 0.5


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, mock_mode: bool = False, config: Optional[SerialConfig] = None):
        super().__init__()
        self._config = config or SerialConfig()
        load_ui(self, 'main_window.ui')

        for name, child_type in MAIN_WINDOW_OBJECTS.items():
            setattr(self, name, require_child(self, child_type, name))

        # plotPanel minimumWidth, txPanel/rxPanel sizePolicy and minimumWidth are set in .ui

        self._mock_mode = mock_mode
        self._shutdown_done = False
        self._summary_printed = False
        self._last_error_message = None
        self._applied_payload = default_io_payload(channel_count=1)
        self._awaiting_apply_feedback = False
        self._relay_channel = 0

        self._event_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._command_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._stop_event = threading.Event()
        self._worker: Optional[V2SerialWorker] = None

        self._lat_stats = RunningStats()
        self._rx_ratio_stats = RunningStats()
        self._latencies: Optional[list] = [] if not self._config.run_forever else None
        self._rx_ratios: Optional[list] = [] if not self._config.run_forever else None
        self._total = 0
        self._success_count = 0
        self._fail_count = 0
        self._last_rx_monitor: Optional[SnetMonitorSnapshot] = None
        self._response_tracker = ResponseTimeTracker()

        fixed_font = build_fixed_font()
        self.relayChannelBar = find_optional_child(self, QtWidgets.QWidget, 'relayChannelBar')
        self._relay_channel_buttons = {
            0: find_optional_child(self, QtWidgets.QPushButton, 'relayAllButton'),
            1: find_optional_child(self, QtWidgets.QPushButton, 'relayCh1Button'),
            2: find_optional_child(self, QtWidgets.QPushButton, 'relayCh2Button'),
            3: find_optional_child(self, QtWidgets.QPushButton, 'relayCh3Button'),
            4: find_optional_child(self, QtWidgets.QPushButton, 'relayCh4Button'),
            5: find_optional_child(self, QtWidgets.QPushButton, 'relayCh5Button'),
            6: find_optional_child(self, QtWidgets.QPushButton, 'relayCh6Button'),
        }
        self._relay_channel_group: Optional[QtWidgets.QButtonGroup] = None
        self._init_relay_channel_selector()
        self.calibrationGroup = self._build_calibration_group()
        if self.calibrationGroup is not None:
            # ui-override: 동적 생성 위젯 -- .ui 이관 대상
            self.calibrationGroup.setMinimumWidth(SIDE_PANEL_WIDTH)
            self.calibrationGroup.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        # ui-override: Designer 미지원 -- QHBoxLayout stretch는 .ui XML에 표현 불가
        central_layout = self.centralWidget().layout()
        if isinstance(central_layout, QtWidgets.QHBoxLayout):
            central_layout.setStretch(0, 5)
            central_layout.setStretch(1, 2)

        # minimumSize and geometry are set in .ui

        # Port combo -- starts empty, connect on selection
        self._port_combo = find_optional_child(self.txPanel, QtWidgets.QComboBox, 'portCombo')
        if self._port_combo is not None:
            self._populate_ports()
            self._port_combo.currentTextChanged.connect(self._on_port_selected)

        self.tx_panel = TxPanelView(root=self.txPanel, debug_root=self.debugTabWidget, font=fixed_font)
        self.rx_panel = RxPanelView(root=self.rxPanel, debug_root=self.debugTabWidget, font=fixed_font)
        self.rx_panel.set_full_open_value_raw(None)

        for name, child_type in PLOT_PANEL_OBJECTS.items():
            setattr(self, name, require_child(self.plotPanel, child_type, name))

        toggle_buttons = {}
        for ch in range(1, MAX_CHANNELS + 1):
            toggle_buttons[(ch - 1, 'tx')] = getattr(self, f'legendTx{ch}Button')
            toggle_buttons[(ch - 1, 'rx')] = getattr(self, f'legendRx{ch}Button')
        self.plot_view = PlotView(self.plotPanel, self.plotHost, toggle_buttons, fixed_font)
        self.plot_view.note_applied_payload(self._applied_payload)

        self.tx_panel.connect_actions(self._on_run_clicked, self._on_stop_clicked, self._on_set_clicked)
        if self.rx_panel.adCommandCheckBox is not None:
            self.rx_panel.adCommandCheckBox.toggled.connect(self._on_ad_command_toggled)
        if self.rx_panel.fullOpenControlCheckBox is not None:
            self.rx_panel.fullOpenControlCheckBox.toggled.connect(self._on_full_open_control_toggled)
        if self.rx_panel.fullOpenApplyButton is not None:
            self.rx_panel.fullOpenApplyButton.clicked.connect(self._on_full_open_apply_clicked)
        if self.tx_panel.modeToggle is not None:
            self.tx_panel.modeToggle.toggled.connect(self._on_mode_toggled)
        if self.tx_panel.btnLoadKp is not None:
            self.tx_panel.btnLoadKp.clicked.connect(self._on_load_kp_clicked)

        self.tx_panel.set_applied_payload(self._applied_payload)
        self.tx_panel.update_run_state(False)
        self.tx_panel.update_frame(None, status='waiting')

        self._ui_timer = QtCore.QTimer(self)
        self._ui_timer.setInterval(UI_TIMER_MS)
        self._ui_timer.timeout.connect(self._on_ui_timer)
        self._ui_timer.start()

        if mock_mode:
            transport = MockTransport()
            worker_config = WorkerConfig(
                rx_timeout_s=self._config.rx_timeout_s,
                sample_period_s=max(0.001, self._config.sample_period_s),
                run_forever=self._config.run_forever,
                test_count=self._config.test_count,
            )
            self._worker = V2SerialWorker(
                transport=transport,
                event_queue=self._event_queue,
                command_queue=self._command_queue,
                stop_event=self._stop_event,
                config=worker_config,
            )
            self._worker.start()
            self._command_queue.put(ReadVarCommand(var_index=FULL_OPEN_VALUE_VAR_INDEX))
            self.statusBar().showMessage('Mock mode enabled')
        else:
            self.statusBar().showMessage('Select COM port to connect')

    def minimumSizeHint(self):
        return QtCore.QSize(*MAIN_WINDOW_MIN_SIZE)

    def _init_relay_channel_selector(self):
        buttons = {channel: button for channel, button in self._relay_channel_buttons.items() if button is not None}
        if not buttons:
            return

        # styleSheet, toolTip, checkable, and checked are set in .ui
        self._relay_channel_group = QtWidgets.QButtonGroup(self)
        self._relay_channel_group.setExclusive(True)

        for channel, button in buttons.items():
            self._relay_channel_group.addButton(button, channel)

        self._relay_channel_group.buttonClicked[int].connect(self._on_relay_channel_changed)

    def _build_calibration_group(self) -> Optional[QtWidgets.QGroupBox]:
        if self.relayChannelBar is None:
            return None

        right_layout = self.findChild(QtWidgets.QVBoxLayout, 'rightLayout')
        if right_layout is None:
            return None

        calibration_group = self.findChild(QtWidgets.QGroupBox, 'calibrationGroup')
        if calibration_group is not None:
            return calibration_group

        relay_index = self._layout_index_of(right_layout, self.relayChannelBar)
        debug_index = self._layout_index_of(right_layout, self.debugTabWidget)
        if relay_index < 0 or debug_index < 0:
            return None

        calibration_group = QtWidgets.QGroupBox('Calibration', self.centralWidget())
        calibration_group.setObjectName('calibrationGroup')
        calibration_group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        group_layout = QtWidgets.QVBoxLayout(calibration_group)
        group_layout.setContentsMargins(6, 6, 6, 6)
        group_layout.setSpacing(3)

        # relayChannelBar title, flat, styleSheet, min/maxHeight are set in .ui

        right_layout.removeWidget(self.relayChannelBar)
        right_layout.removeWidget(self.debugTabWidget)
        group_layout.addWidget(self.relayChannelBar)
        debug_scroll = QtWidgets.QScrollArea(calibration_group)
        debug_scroll.setObjectName('calibrationScrollArea')
        debug_scroll.setWidgetResizable(True)
        debug_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        debug_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        debug_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        # ui-override: 동적 생성 스크롤 영역 + debugTabWidget 재배치 -- .ui 이관 대상
        debug_scroll.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.debugTabWidget.setMinimumSize(0, 0)
        self.debugTabWidget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        debug_scroll.setWidget(self.debugTabWidget)
        group_layout.addWidget(debug_scroll, 1)
        right_layout.insertWidget(min(relay_index, debug_index), calibration_group)

        return calibration_group

    def _layout_index_of(self, layout: QtWidgets.QLayout, widget: QtWidgets.QWidget) -> int:
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item.widget() is widget:
                return index
        return -1

    def _on_relay_channel_changed(self, channel: int):
        self._relay_channel = int(channel)
        channel_text = 'ALL' if self._relay_channel == 0 else str(self._relay_channel)
        self.statusBar().showMessage(f'Relay channel selected: {channel_text}')

    # --- UI timer ---

    def _on_ui_timer(self):
        while True:
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)
        self.plot_view.refresh()

    # --- Event routing ---

    def _handle_event(self, event):
        if isinstance(event, RunStateEvent):
            self.tx_panel.update_run_state(event.running)
            self.plot_view.set_run_state(event.running)
            return

        if isinstance(event, AppliedSetpointEvent):
            self._applied_payload = event.payload
            self.tx_panel.set_applied_payload(event.payload, highlight_inputs=self._awaiting_apply_feedback)
            self._awaiting_apply_feedback = False
            self.plot_view.note_applied_payload(event.payload)
            self.plot_view.set_series_counts(tx_count=event.payload.channel_count)
            self._response_tracker.start(event.payload, self._last_rx_monitor)
            if self._response_tracker.is_active and self.plot_view.plotLastUpdateValueLabel is not None:
                self.plot_view.plotLastUpdateValueLabel.setText('-- s')
            return

        if isinstance(event, TxFrameEvent):
            self.tx_panel.update_frame(event.frame)
            return

        if isinstance(event, RxFrameEvent):
            self.rx_panel.update_frame(event.frame, status='OK' if event.frame is not None else 'TIMEOUT')
            return

        if isinstance(event, RxMonitorEvent):
            self._last_rx_monitor = event.monitor
            self.rx_panel.update_monitor(event.monitor, status='OK' if event.monitor is not None else 'TIMEOUT')
            self.plot_view.note_rx_monitor(event.monitor)
            return

        if isinstance(event, VarValueEvent):
            if event.var_index == FULL_OPEN_VALUE_VAR_INDEX:
                self.rx_panel.set_full_open_value_raw(event.value)
            return

        if isinstance(event, BrooksKpEvent):
            self.tx_panel.set_kp_values(event.channel, event.values)
            visible_count = self.tx_panel.visible_kp_field_count()
            channel_text = 'ALL' if event.channel == 0 else str(event.channel)
            if len(event.values) > visible_count:
                self.statusBar().showMessage(
                    f'KP loaded from CH {channel_text} (extra value available in tooltip)'
                )
            else:
                self.statusBar().showMessage(f'KP loaded from CH {channel_text}')
            return

        if isinstance(event, SampleReceivedEvent):
            sample = event.sample
            self._total += 1
            self.plot_view.add_point(sample.tx_payload, sample.rx_monitor)
            print(format_sample_log(sample, self._config.run_forever, self._config.test_count))

            elapsed = self._response_tracker.check(sample)
            if elapsed is not None and self.plot_view.plotLastUpdateValueLabel is not None:
                self.plot_view.plotLastUpdateValueLabel.setText(f'{elapsed:.2f} s')

            if sample.success:
                self._success_count += 1
                self._lat_stats.add(sample.latency_ms)
                if self._latencies is not None:
                    self._latencies.append(sample.latency_ms)
            else:
                self._fail_count += 1

            rx_ratio = first_monitor_ratio_percent(sample.rx_monitor)
            if rx_ratio is not None:
                self._rx_ratio_stats.add(rx_ratio)
                if self._rx_ratios is not None:
                    self._rx_ratios.append(rx_ratio)
            return

        if isinstance(event, ErrorEvent):
            self._last_error_message = event.message
            print(event.message)
            self.statusBar().showMessage(event.message)
            return

        if isinstance(event, WorkerDoneEvent):
            self.tx_panel.update_run_state(False)
            self.plot_view.set_run_state(False)
            if not self._last_error_message:
                self.statusBar().showMessage('Worker stopped')

    # --- Button callbacks ---

    def _on_run_clicked(self):
        if self._worker is None:
            self.statusBar().showMessage('Select COM port to connect')
            return
        self._command_queue.put(SetRunningCommand(running=True))

    def _on_stop_clicked(self):
        if self._worker is None:
            return
        self._command_queue.put(SetRunningCommand(running=False))

    def _on_set_clicked(self):
        if self._worker is None:
            self.statusBar().showMessage('Select COM port to connect')
            return
        try:
            pending_payload = self.tx_panel.build_pending_payload()
        except ValueError as exc:
            self._awaiting_apply_feedback = False
            self.tx_panel.show_validation_error(str(exc))
            return

        self._awaiting_apply_feedback = True
        self._command_queue.put(ApplySetpointCommand(payload=pending_payload))

    def _on_ad_command_toggled(self, checked: bool):
        if self._worker is None:
            return
        self._command_queue.put(WriteVarCommand(var_index=WRITE_VAR_READ_AD_FLAG_INDEX, value=1 if checked else 0))

    def _on_full_open_control_toggled(self, checked: bool):
        if self._worker is None:
            return
        self._command_queue.put(WriteVarCommand(var_index=WRITE_VAR_FULL_OPEN_CONTROL_FLAG_INDEX, value=1 if checked else 0))

    def _on_full_open_apply_clicked(self):
        try:
            raw_value = self.rx_panel.build_full_open_raw_value()
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return

        if self._worker is None:
            self.statusBar().showMessage('Select COM port to connect')
            return

        self._command_queue.put(WriteVarCommand(var_index=FULL_OPEN_VALUE_VAR_INDEX, value=raw_value))

    def _on_mode_toggled(self, checked: bool):
        """checked=True -> CAL mode, False -> RUN mode."""
        if self._worker is None:
            return
        self._command_queue.put(WriteVarCommand(var_index=WRITE_VAR_MODE_FLAG_INDEX, value=1 if checked else 0))

    def _on_load_kp_clicked(self):
        if self._worker is None:
            self.statusBar().showMessage('Select COM port to connect')
            return

        channel_text = 'ALL' if self._relay_channel == 0 else str(self._relay_channel)
        self.statusBar().showMessage(f'Loading KP from CH {channel_text}...')
        self._command_queue.put(BrooksGetKpCommand(channel=self._relay_channel))

    # --- Port combo ---

    def _populate_ports(self):
        if self._port_combo is None:
            return
        self._port_combo.blockSignals(True)
        self._port_combo.clear()
        self._port_combo.addItem('')  # empty first item
        ports = serial.tools.list_ports.comports()
        for port in sorted(ports, key=lambda p: p.device):
            self._port_combo.addItem(port.device)
        self._port_combo.setCurrentIndex(0)  # start with empty
        self._port_combo.blockSignals(False)

    def _on_port_selected(self, port_name: str):
        if not port_name or self._mock_mode:
            return
        if self._worker is not None:
            self._command_queue.put(SetRunningCommand(running=False))
            self._stop_event.set()
            self._worker.join(timeout=2.0)
            self._on_ui_timer()
            self._worker = None
        # Drain stale commands (reuse queues, don't recreate)
        while not self._command_queue.empty():
            try:
                self._command_queue.get_nowait()
            except queue.Empty:
                break
        self._stop_event = threading.Event()
        self._last_error_message = None
        self._config.port = port_name
        transport = SerialTransport(port=port_name, baud=self._config.baud)
        worker_config = WorkerConfig(
            rx_timeout_s=self._config.rx_timeout_s,
            sample_period_s=self._config.sample_period_s,
            run_forever=self._config.run_forever,
            test_count=self._config.test_count,
        )
        self._worker = V2SerialWorker(
            transport=transport,
            event_queue=self._event_queue,
            command_queue=self._command_queue,
            stop_event=self._stop_event,
            config=worker_config,
        )
        self._worker.start()
        self.rx_panel.set_full_open_value_raw(None)
        self._command_queue.put(ReadVarCommand(var_index=FULL_OPEN_VALUE_VAR_INDEX))
        self.statusBar().showMessage(f'Connected: {port_name}')

    # --- Lifecycle ---

    def shutdown(self):
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._ui_timer.stop()
        if self._worker is not None:
            self._command_queue.put(SetRunningCommand(running=False))
            self._stop_event.set()
            self._worker.join(timeout=2.0)
            self._on_ui_timer()

    def print_summary(self):
        if self._summary_printed:
            return
        self._summary_printed = True

        if self._last_error_message:
            print(self._last_error_message)

        if self._config.run_forever and self._total == 0:
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
            stdev = self._lat_stats.stdev()
            if stdev is not None:
                print(f'    StdDev : {stdev:7.2f} ms')

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
            stdev = self._rx_ratio_stats.stdev()
            if stdev is not None:
                print(f'    StdDev : {stdev:7.2f}%')
        print('=' * 60)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
