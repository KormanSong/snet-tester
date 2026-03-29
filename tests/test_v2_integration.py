"""Phase 2 integration checks — verifies v1 MainWindow ↔ v2 core compatibility.

These tests run WITHOUT Qt by testing the import chain, type compatibility,
and event/command contract between MainWindow and v2 core modules.
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

from snet_tester2.comm.worker import SerialWorker as V2SerialWorker
from snet_tester2.comm.commands import (
    ApplySetpointCommand, BrooksGetKpCommand, ReadVarCommand,
    SetRunningCommand, WriteVarCommand,
)
from snet_tester2.comm.events import (
    AppliedSetpointEvent, BrooksKpEvent, ErrorEvent, RxFrameEvent,
    RxMonitorEvent, RunStateEvent, SampleReceivedEvent, TxFrameEvent,
    VarValueEvent, WorkerDoneEvent,
)
from snet_tester2.config import WorkerConfig
from snet_tester2.transport.mock import MockTransport

# v1 protocol types — used by panels
from snet_tester.protocol.types import IoPayload, SampleEvent, SnetMonitorSnapshot
from snet_tester.protocol.codec import default_io_payload, first_monitor_ratio_percent
from snet_tester.protocol.constants import FULL_OPEN_VALUE_VAR_INDEX


FAST_CONFIG = WorkerConfig(rx_timeout_s=0.1, sample_period_s=0.01, run_forever=False, test_count=5)


def _collect_events(eq, timeout=3.0):
    events = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            event = eq.get(timeout=0.1)
            events.append(event)
            if isinstance(event, WorkerDoneEvent):
                break
        except queue.Empty:
            continue
    return events


class TestMainWindowEventContract:
    """Verify that v2 events carry data compatible with v1 panel duck-typing."""

    def test_sample_event_has_v1_compatible_fields(self):
        """SampleReceivedEvent.sample must have fields panels expect."""
        transport = MockTransport()
        eq = queue.SimpleQueue()
        cq = queue.SimpleQueue()
        stop = threading.Event()
        worker = V2SerialWorker(transport, eq, cq, stop, FAST_CONFIG)
        worker.start()
        cq.put(SetRunningCommand(running=True))
        events = _collect_events(eq)
        worker.join(timeout=2.0)

        samples = [e for e in events if isinstance(e, SampleReceivedEvent)]
        assert len(samples) >= 1

        sample = samples[0].sample
        # These fields are accessed by v1 panels via duck typing
        assert hasattr(sample, 'tx_payload')
        assert hasattr(sample, 'rx_monitor')
        assert hasattr(sample, 'latency_ms')
        assert hasattr(sample, 'success')
        assert hasattr(sample, 'index')
        assert hasattr(sample, 'seq')

    def test_applied_setpoint_payload_is_duck_compatible(self):
        """AppliedSetpointEvent.payload must have channel_count and channels."""
        transport = MockTransport()
        eq = queue.SimpleQueue()
        cq = queue.SimpleQueue()
        stop = threading.Event()
        worker = V2SerialWorker(transport, eq, cq, stop, FAST_CONFIG)
        worker.start()
        time.sleep(0.2)
        stop.set()
        worker.join(timeout=2.0)
        events = _collect_events(eq, timeout=1.0)

        apply_events = [e for e in events if isinstance(e, AppliedSetpointEvent)]
        assert len(apply_events) >= 1

        payload = apply_events[0].payload
        assert hasattr(payload, 'channel_count')
        assert hasattr(payload, 'channels')
        assert payload.channel_count >= 1

    def test_rx_monitor_has_panel_fields(self):
        """RxMonitorEvent.monitor must have fields rx_panel expects."""
        transport = MockTransport()
        eq = queue.SimpleQueue()
        cq = queue.SimpleQueue()
        stop = threading.Event()
        worker = V2SerialWorker(transport, eq, cq, stop, FAST_CONFIG)
        worker.start()
        cq.put(SetRunningCommand(running=True))
        events = _collect_events(eq)
        worker.join(timeout=2.0)

        monitor_events = [e for e in events if isinstance(e, RxMonitorEvent) and e.monitor is not None]
        assert len(monitor_events) >= 1

        mon = monitor_events[0].monitor
        assert hasattr(mon, 'channel_count')
        assert hasattr(mon, 'channels')
        assert hasattr(mon, 'pressure_raw')
        assert hasattr(mon, 'temperature_raw')

    def test_v1_first_monitor_ratio_works_on_v2_monitor(self):
        """v1's first_monitor_ratio_percent accepts v2 monitor objects."""
        transport = MockTransport()
        eq = queue.SimpleQueue()
        cq = queue.SimpleQueue()
        stop = threading.Event()
        worker = V2SerialWorker(transport, eq, cq, stop, FAST_CONFIG)
        worker.start()
        cq.put(SetRunningCommand(running=True))
        events = _collect_events(eq)
        worker.join(timeout=2.0)

        samples = [e for e in events if isinstance(e, SampleReceivedEvent)]
        assert len(samples) >= 1
        # This is the exact call MainWindow._handle_event makes
        ratio = first_monitor_ratio_percent(samples[0].sample.rx_monitor)
        assert ratio is not None or samples[0].sample.rx_monitor is None

    def test_var_value_event_from_read_command(self):
        """ReadVarCommand → VarValueEvent with correct var_index."""
        transport = MockTransport()
        eq = queue.SimpleQueue()
        cq = queue.SimpleQueue()
        stop = threading.Event()
        worker = V2SerialWorker(transport, eq, cq, stop, FAST_CONFIG)
        worker.start()
        cq.put(ReadVarCommand(var_index=FULL_OPEN_VALUE_VAR_INDEX))
        time.sleep(0.5)
        stop.set()
        worker.join(timeout=2.0)
        events = _collect_events(eq, timeout=1.0)

        var_events = [e for e in events if isinstance(e, VarValueEvent)]
        assert len(var_events) >= 1
        assert var_events[0].var_index == FULL_OPEN_VALUE_VAR_INDEX
        assert var_events[0].value == 0  # MockTransport default


class TestWorkerGuardContract:
    """Verify guard behavior that MainWindow callbacks depend on."""

    def test_commands_before_worker_are_harmless(self):
        """Commands put into queue before worker starts are consumed without crash."""
        transport = MockTransport()
        eq = queue.SimpleQueue()
        cq = queue.SimpleQueue()
        stop = threading.Event()

        # Queue commands before worker exists (simulates connected-but-not-yet-started)
        cq.put(SetRunningCommand(running=True))
        cq.put(WriteVarCommand(var_index=0x0001, value=1))

        worker = V2SerialWorker(transport, eq, cq, stop, FAST_CONFIG)
        worker.start()
        time.sleep(0.3)
        stop.set()
        worker.join(timeout=2.0)
        events = _collect_events(eq, timeout=1.0)

        # Worker should have processed the commands without crashing
        assert any(isinstance(e, WorkerDoneEvent) for e in events)

    def test_error_then_done_sequence(self):
        """ErrorEvent is always followed by WorkerDoneEvent on failure."""
        from snet_tester2.transport.mock import FaultKind, FaultRule
        transport = MockTransport(faults=[FaultRule(at_request=-1, kind=FaultKind.OPEN_FAIL)])
        eq = queue.SimpleQueue()
        cq = queue.SimpleQueue()
        stop = threading.Event()

        worker = V2SerialWorker(transport, eq, cq, stop, FAST_CONFIG)
        worker.start()
        worker.join(timeout=2.0)
        events = _collect_events(eq, timeout=1.0)

        types = [type(e) for e in events]
        assert ErrorEvent in types
        assert WorkerDoneEvent in types
        # ErrorEvent must come before WorkerDoneEvent
        error_idx = types.index(ErrorEvent)
        done_idx = types.index(WorkerDoneEvent)
        assert error_idx < done_idx
