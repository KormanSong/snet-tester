"""Main window — assembles panels, routes events, manages worker lifecycle."""

import queue
import threading
import time
from typing import Optional

import numpy as np
import serial.tools.list_ports
from PyQt5 import QtCore, QtWidgets

from ..config import SerialConfig
from ..protocol.codec import (
    build_frame,
    build_io_payload_bytes,
    build_mock_snet_monitor_payload,
    build_write_var_frame,
    decode_frame_view,
    decode_io_payload,
    decode_snet_monitor_payload,
    default_io_payload,
    first_monitor_ratio_percent,
    format_sample_log,
)
from ..protocol.constants import (
    MAX_CHANNELS,
    REQUEST_CMD,
    RESPONSE_CMD,
    SAMPLE_PERIOD_S,
    SEQ_START,
    WRITE_VAR_READ_AD_FLAG_INDEX,
)
from ..protocol.types import IoPayload, SampleEvent, SnetMonitorSnapshot
from ..comm.worker import SerialWorker
from .helpers import build_fixed_font, load_ui, require_child, find_optional_child
from .tx_panel import TxPanelView
from .rx_panel import RxPanelView
from .plot_view import PlotView
from .response_tracker import ResponseTimeTracker

UI_TIMER_MS = 20
MOCK_LATENCY_MS = 5.0

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

        # Fix right panel width
        RIGHT_PANEL_WIDTH = 459
        for panel in (self.txPanel, self.rxPanel, self.debugTabWidget):
            panel.setMinimumWidth(RIGHT_PANEL_WIDTH)
            panel.setMaximumWidth(RIGHT_PANEL_WIDTH)

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

        self._event_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._command_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._stop_event = threading.Event()
        self._worker: Optional[SerialWorker] = None

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
        # Port combo — starts empty, connect on selection
        self._port_combo = find_optional_child(self.txPanel, QtWidgets.QComboBox, 'portCombo')
        if self._port_combo is not None:
            self._populate_ports()
            self._port_combo.currentTextChanged.connect(self._on_port_selected)

        self.tx_panel = TxPanelView(root=self.txPanel, debug_root=self.debugTabWidget, font=fixed_font)
        self.rx_panel = RxPanelView(root=self.rxPanel, debug_root=self.debugTabWidget, font=fixed_font)

        for name, child_type in PLOT_PANEL_OBJECTS.items():
            setattr(self, name, require_child(self.plotPanel, child_type, name))

        self.graphHintLabel = self.plotPanel.findChild(QtWidgets.QLabel, 'graphHintLabel')
        if self.graphHintLabel is not None:
            self.graphHintLabel.setWordWrap(True)

        toggle_buttons = {}
        for ch in range(1, MAX_CHANNELS + 1):
            toggle_buttons[(ch - 1, 'tx')] = getattr(self, f'legendTx{ch}Button')
            toggle_buttons[(ch - 1, 'rx')] = getattr(self, f'legendRx{ch}Button')
        self.plot_view = PlotView(self.plotPanel, self.plotHost, toggle_buttons, fixed_font)

        self.tx_panel.connect_actions(self._on_run_clicked, self._on_stop_clicked, self._on_set_clicked)
        if self.rx_panel.adCommandCheckBox is not None:
            self.rx_panel.adCommandCheckBox.toggled.connect(self._on_ad_command_toggled)

        self.tx_panel.set_applied_payload(self._applied_payload)
        self.tx_panel.update_run_state(False)
        self.tx_panel.update_frame(None, status='waiting')

        self._ui_timer = QtCore.QTimer(self)
        self._ui_timer.setInterval(UI_TIMER_MS)
        self._ui_timer.timeout.connect(self._on_ui_timer)
        self._ui_timer.start()

        self._mock_timer: Optional[QtCore.QTimer] = None
        if self._mock_mode:
            self._mock_timer = QtCore.QTimer(self)
            self._mock_timer.setInterval(max(1, int(SAMPLE_PERIOD_S * 1000)))
            self._mock_timer.timeout.connect(self._emit_mock_sample)
            self.statusBar().showMessage('Mock mode enabled')
        else:
            # Don't start worker yet — wait for port selection
            self.statusBar().showMessage('Select COM port to connect')

    # --- UI timer ---

    def _on_ui_timer(self):
        while True:
            try:
                kind, payload = self._event_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event(kind, payload)
        self.plot_view.refresh()

    # --- Event routing ---

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
            # Response time: start measurement
            self._response_tracker.start(payload, self._last_rx_monitor)
            if self._response_tracker.is_active and self.plot_view.plotLastUpdateValueLabel is not None:
                self.plot_view.plotLastUpdateValueLabel.setText('--')
            return

        if kind == 'tx_frame':
            self.tx_panel.update_frame(payload)
            return

        if kind == 'rx_frame':
            self.rx_panel.update_frame(payload, status='OK' if payload is not None else 'TIMEOUT')
            return

        if kind == 'rx_monitor':
            self._last_rx_monitor = payload
            self.rx_panel.update_monitor(payload, status='OK' if payload is not None else 'TIMEOUT')
            self.plot_view.note_rx_monitor(payload)
            return

        if kind == 'sample':
            event: SampleEvent = payload
            self._total += 1
            self.plot_view.add_point(event.tx_payload, event.rx_monitor)
            print(format_sample_log(event, self._config.run_forever, self._config.test_count))

            # Response time check
            elapsed = self._response_tracker.check(event)
            if elapsed is not None and self.plot_view.plotLastUpdateValueLabel is not None:
                self.plot_view.plotLastUpdateValueLabel.setText(f'{elapsed:.2f}')

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

    # --- Button callbacks ---

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

    # --- Mock ---

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
        # Stop existing worker if any
        if self._worker is not None:
            self._command_queue.put(('set_running', False))
            self._stop_event.set()
            self._worker.join(timeout=2.0)
            self._on_ui_timer()  # drain remaining events
            self._worker = None

        # Start new worker with selected port
        self._stop_event = threading.Event()
        self._event_queue = queue.SimpleQueue()
        self._command_queue = queue.SimpleQueue()
        self._config.port = port_name
        self._worker = SerialWorker(
            event_queue=self._event_queue,
            command_queue=self._command_queue,
            stop_event=self._stop_event,
            config=self._config,
        )
        self._worker.start()
        self.statusBar().showMessage(f'Connected: {port_name}')

    # --- Lifecycle ---

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
