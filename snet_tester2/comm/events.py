"""Typed worker events -- replaces v1 string-based ('kind', payload) tuples.

Each event is a frozen dataclass emitted by SerialWorker onto the
event_queue.  The UI-thread dispatcher uses isinstance() checks
instead of string matching, giving static-analysis support and
eliminating typo-class bugs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from ..protocol.types import FrameView, IoPayload, SampleEvent, SnetMonitorSnapshot


# --- lifecycle events ---

@dataclass(frozen=True)
class RunStateEvent:
    """Worker's run/stop state changed."""
    running: bool


@dataclass(frozen=True)
class WorkerDoneEvent:
    """Worker thread has exited (normal or error)."""
    pass


# --- setpoint events ---

@dataclass(frozen=True)
class AppliedSetpointEvent:
    """Currently active IoPayload acknowledged by the worker."""
    payload: IoPayload


# --- frame-level events ---

@dataclass(frozen=True)
class TxFrameEvent:
    """A frame was transmitted."""
    frame: FrameView


@dataclass(frozen=True)
class RxFrameEvent:
    """A response frame was received (or None on timeout)."""
    frame: Optional[FrameView]


@dataclass(frozen=True)
class RxMonitorEvent:
    """Decoded monitor snapshot from an IO_RESPONSE (or None)."""
    monitor: Optional[SnetMonitorSnapshot]


# --- sample events ---

@dataclass(frozen=True)
class SampleReceivedEvent:
    """One complete TX/RX sample cycle result."""
    sample: SampleEvent


# --- variable read/write events ---

@dataclass(frozen=True)
class VarValueEvent:
    """Decoded variable value from a read_var or write_var response."""
    var_index: int
    value: int


# --- Brooks KP events ---

@dataclass(frozen=True)
class BrooksKpEvent:
    """Decoded Brooks KP calibration values for a channel."""
    channel: int
    values: tuple[float, ...]


# --- error events ---

@dataclass(frozen=True)
class ErrorEvent:
    """A recoverable error message from the worker."""
    message: str


# Union of all event types for type annotations
WorkerEvent = Union[
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
]
