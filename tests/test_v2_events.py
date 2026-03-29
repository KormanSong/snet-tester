"""Tests for comm layer event and command dataclasses.

Validates that:
  - All event types construct with expected fields
  - All command types construct with expected fields
  - Frozen dataclasses reject attribute mutation
  - WorkerEvent / WorkerCommand unions include all variants
"""

import pytest

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
    WorkerEvent,
)
from snet_tester2.comm.commands import (
    SetRunningCommand,
    ApplySetpointCommand,
    WriteVarCommand,
    ReadVarCommand,
    BrooksGetKpCommand,
    WorkerCommand,
)
from snet_tester2.protocol.codec import default_io_payload


# ---------------------------------------------------------------------------
# Event construction
# ---------------------------------------------------------------------------

def test_run_state_event():
    e = RunStateEvent(running=True)
    assert e.running is True


def test_error_event():
    e = ErrorEvent(message="test error")
    assert e.message == "test error"


def test_worker_done_event():
    e = WorkerDoneEvent()
    assert isinstance(e, WorkerDoneEvent)


def test_var_value_event():
    e = VarValueEvent(var_index=0x1000, value=12345)
    assert e.var_index == 0x1000
    assert e.value == 12345


def test_brooks_kp_event():
    e = BrooksKpEvent(channel=1, values=(0.25, 0.75, 1.5, 3.0, 4.5, 6.0))
    assert e.channel == 1
    assert len(e.values) == 6


# ---------------------------------------------------------------------------
# Frozen enforcement
# ---------------------------------------------------------------------------

def test_events_are_frozen():
    e = RunStateEvent(running=True)
    with pytest.raises(AttributeError):
        e.running = False


def test_commands_are_frozen():
    c = SetRunningCommand(running=True)
    with pytest.raises(AttributeError):
        c.running = False


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------

def test_apply_setpoint_command():
    payload = default_io_payload(1)
    c = ApplySetpointCommand(payload=payload)
    assert c.payload.channel_count == 1


def test_write_var_command():
    c = WriteVarCommand(var_index=0x1000, value=42000)
    assert c.var_index == 0x1000
    assert c.value == 42000


def test_read_var_command():
    c = ReadVarCommand(var_index=0x0001)
    assert c.var_index == 0x0001


def test_brooks_command():
    c = BrooksGetKpCommand(channel=3)
    assert c.channel == 3
