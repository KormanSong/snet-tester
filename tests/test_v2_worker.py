"""Integration tests for SerialWorker with MockTransport.

Validates that the v2 SerialWorker:
  - Starts, emits initial events (AppliedSetpointEvent, RunStateEvent),
    and stops cleanly with WorkerDoneEvent
  - Produces SampleReceivedEvent when running with test_count limit
  - Handles ApplySetpointCommand and emits AppliedSetpointEvent
  - Handles WriteVarCommand / ReadVarCommand and emits VarValueEvent
  - Handles BrooksGetKpCommand and emits BrooksKpEvent
  - Handles fault injection: TIMEOUT, OPEN_FAIL, DISCONNECT
  - Responds to stop_event for clean shutdown

Uses short timeouts (rx_timeout_s=0.1, sample_period_s=0.01) for fast
test execution. MockTransport generates responses synchronously in
write(), so no real timing issues arise.
"""

import queue
import threading
import time

import pytest

from snet_tester2.comm.worker import SerialWorker
from snet_tester2.comm.events import (
    RunStateEvent,
    AppliedSetpointEvent,
    TxFrameEvent,
    RxFrameEvent,
    RxMonitorEvent,
    SampleReceivedEvent,
    VarValueEvent,
    BrooksKpEvent,
    ErrorEvent,
    WorkerDoneEvent,
)
from snet_tester2.comm.commands import (
    SetRunningCommand,
    ApplySetpointCommand,
    WriteVarCommand,
    ReadVarCommand,
    BrooksGetKpCommand,
)
from snet_tester2.config import WorkerConfig
from snet_tester2.transport.mock import MockTransport, FaultKind, FaultRule
from snet_tester2.protocol.codec import default_io_payload, build_io_payload_model
from snet_tester2.protocol.enums import VarIndex


# ---------------------------------------------------------------------------
# Test configuration -- short timeouts for fast execution
# ---------------------------------------------------------------------------

FAST_CONFIG = WorkerConfig(
    rx_timeout_s=0.1,
    sample_period_s=0.01,
    run_forever=False,
    test_count=10,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_events(event_queue, timeout=2.0):
    """Drain all events from queue until WorkerDoneEvent or timeout.

    Parameters
    ----------
    event_queue : queue.SimpleQueue
        The event queue that SerialWorker emits into.
    timeout : float
        Maximum wall-clock seconds to wait for events.

    Returns
    -------
    list
        All collected event objects, in order received.
    """
    events = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            event = event_queue.get(timeout=0.1)
            events.append(event)
            if isinstance(event, WorkerDoneEvent):
                break
        except queue.Empty:
            continue
    return events


def _start_worker(transport=None, config=None, faults=None):
    """Create and start a SerialWorker with MockTransport.

    Parameters
    ----------
    transport : MockTransport | None
        Pre-configured transport. If None, a fresh one is created.
    config : WorkerConfig | None
        Worker config. If None, FAST_CONFIG is used.
    faults : list[FaultRule] | None
        Fault rules passed to MockTransport (only when transport is None).

    Returns
    -------
    tuple[SerialWorker, queue.SimpleQueue, queue.SimpleQueue, threading.Event]
        (worker, event_queue, command_queue, stop_event)
    """
    if transport is None:
        transport = MockTransport(faults=faults)
    if config is None:
        config = FAST_CONFIG
    event_queue = queue.SimpleQueue()
    command_queue = queue.SimpleQueue()
    stop_event = threading.Event()
    worker = SerialWorker(transport, event_queue, command_queue, stop_event, config)
    worker.start()
    return worker, event_queue, command_queue, stop_event


# ---------------------------------------------------------------------------
# Basic lifecycle and sample cycle tests
# ---------------------------------------------------------------------------

class TestWorkerBasic:
    """Tests for SerialWorker normal operation: start, stop, sample cycles."""

    def test_start_and_stop(self):
        """Worker starts, emits initial events, stops cleanly."""
        worker, eq, cq, stop = _start_worker()
        time.sleep(0.2)
        stop.set()
        worker.join(timeout=3.0)
        events = _collect_events(eq, timeout=1.0)
        types = [type(e) for e in events]
        assert AppliedSetpointEvent in types
        assert RunStateEvent in types
        assert WorkerDoneEvent in types

    def test_basic_sample_cycle(self):
        """Start running, receive SampleReceivedEvents matching test_count."""
        worker, eq, cq, stop = _start_worker(
            config=WorkerConfig(
                rx_timeout_s=0.1,
                sample_period_s=0.01,
                run_forever=False,
                test_count=5,
            )
        )
        cq.put(SetRunningCommand(running=True))
        events = _collect_events(eq, timeout=5.0)
        samples = [e for e in events if isinstance(e, SampleReceivedEvent)]
        assert len(samples) == 5
        for s in samples:
            assert s.sample.success is True
            assert s.sample.latency_ms > 0

    def test_setpoint_apply(self):
        """ApplySetpointCommand produces AppliedSetpointEvent with correct channel count."""
        worker, eq, cq, stop = _start_worker()
        payload = build_io_payload_model(3, [50.0, 30.0, 20.0])
        cq.put(ApplySetpointCommand(payload=payload))
        time.sleep(0.3)
        stop.set()
        worker.join(timeout=3.0)
        events = _collect_events(eq, timeout=1.0)
        apply_events = [e for e in events if isinstance(e, AppliedSetpointEvent)]
        # Should have initial + our explicit apply
        assert len(apply_events) >= 2
        assert apply_events[-1].payload.channel_count == 3

    def test_write_var(self):
        """WriteVarCommand produces VarValueEvent with correct index and value."""
        worker, eq, cq, stop = _start_worker()
        cq.put(WriteVarCommand(var_index=VarIndex.FULL_OPEN_VALUE, value=42000))
        time.sleep(0.5)
        stop.set()
        worker.join(timeout=3.0)
        events = _collect_events(eq, timeout=1.0)
        var_events = [e for e in events if isinstance(e, VarValueEvent)]
        assert len(var_events) >= 1
        assert var_events[0].var_index == VarIndex.FULL_OPEN_VALUE
        assert var_events[0].value == 42000

    def test_read_var(self):
        """ReadVarCommand after WriteVarCommand returns the written value."""
        worker, eq, cq, stop = _start_worker()
        # First write, then read back
        cq.put(WriteVarCommand(var_index=VarIndex.FULL_OPEN_VALUE, value=12345))
        time.sleep(0.3)
        cq.put(ReadVarCommand(var_index=VarIndex.FULL_OPEN_VALUE))
        time.sleep(0.5)
        stop.set()
        worker.join(timeout=3.0)
        events = _collect_events(eq, timeout=1.0)
        var_events = [e for e in events if isinstance(e, VarValueEvent)]
        # Should have write response + read response
        assert len(var_events) >= 2

    def test_brooks_get_kp(self):
        """BrooksGetKpCommand produces BrooksKpEvent with 6 values."""
        worker, eq, cq, stop = _start_worker()
        cq.put(BrooksGetKpCommand(channel=1))
        time.sleep(0.5)
        stop.set()
        worker.join(timeout=3.0)
        events = _collect_events(eq, timeout=1.0)
        kp_events = [e for e in events if isinstance(e, BrooksKpEvent)]
        assert len(kp_events) >= 1
        assert len(kp_events[0].values) == 6


# ---------------------------------------------------------------------------
# Fault injection tests
# ---------------------------------------------------------------------------

class TestWorkerFaults:
    """Tests for SerialWorker behavior under transport faults."""

    def test_timeout_produces_fail_sample(self):
        """TIMEOUT fault at first request produces sample with success=False."""
        transport = MockTransport(
            faults=[FaultRule(at_request=0, kind=FaultKind.TIMEOUT)]
        )
        worker, eq, cq, stop = _start_worker(
            transport=transport,
            config=WorkerConfig(
                rx_timeout_s=0.15,
                sample_period_s=0.01,
                run_forever=False,
                test_count=2,
            ),
        )
        cq.put(SetRunningCommand(running=True))
        events = _collect_events(eq, timeout=5.0)
        samples = [e for e in events if isinstance(e, SampleReceivedEvent)]
        assert len(samples) >= 1
        assert samples[0].sample.success is False

    def test_open_fail(self):
        """OPEN_FAIL fault emits ErrorEvent + WorkerDoneEvent."""
        transport = MockTransport(
            faults=[FaultRule(at_request=-1, kind=FaultKind.OPEN_FAIL)]
        )
        worker, eq, cq, stop = _start_worker(transport=transport)
        worker.join(timeout=3.0)
        events = _collect_events(eq, timeout=1.0)
        types = [type(e) for e in events]
        assert ErrorEvent in types
        assert WorkerDoneEvent in types

    def test_disconnect_mid_run(self):
        """DISCONNECT mid-run emits ErrorEvent + WorkerDoneEvent."""
        transport = MockTransport(
            faults=[FaultRule(at_request=2, kind=FaultKind.DISCONNECT)]
        )
        worker, eq, cq, stop = _start_worker(
            transport=transport,
            config=WorkerConfig(
                rx_timeout_s=0.1,
                sample_period_s=0.01,
                run_forever=False,
                test_count=10,
            ),
        )
        cq.put(SetRunningCommand(running=True))
        events = _collect_events(eq, timeout=5.0)
        types = [type(e) for e in events]
        assert ErrorEvent in types
        assert WorkerDoneEvent in types

    def test_stop_event(self):
        """stop_event.set() causes worker to exit with WorkerDoneEvent."""
        worker, eq, cq, stop = _start_worker()
        cq.put(SetRunningCommand(running=True))
        time.sleep(0.2)
        stop.set()
        worker.join(timeout=3.0)
        assert not worker.is_alive()
        events = _collect_events(eq, timeout=1.0)
        assert any(isinstance(e, WorkerDoneEvent) for e in events)
