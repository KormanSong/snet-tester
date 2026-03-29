"""Typed worker commands -- replaces v1 string-based ('kind', payload) tuples.

Each command is a frozen dataclass placed onto the command_queue by
the UI thread.  The worker's _drain_commands() dispatches via
isinstance() checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from ..protocol.types import IoPayload


@dataclass(frozen=True)
class SetRunningCommand:
    """Start or stop the periodic IO polling loop."""
    running: bool


@dataclass(frozen=True)
class ApplySetpointCommand:
    """Update the active IoPayload for subsequent TX cycles."""
    payload: IoPayload


@dataclass(frozen=True)
class WriteVarCommand:
    """Write a value to a device variable by index."""
    var_index: int
    value: int


@dataclass(frozen=True)
class ReadVarCommand:
    """Read a device variable by index."""
    var_index: int


@dataclass(frozen=True)
class BrooksGetKpCommand:
    """Request Brooks KP calibration values for a channel."""
    channel: int


# Union of all command types for type annotations
WorkerCommand = Union[
    SetRunningCommand,
    ApplySetpointCommand,
    WriteVarCommand,
    ReadVarCommand,
    BrooksGetKpCommand,
]
