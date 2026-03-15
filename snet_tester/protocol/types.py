"""SNET protocol data types."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class IoChannelValue:
    override: int
    ratio_raw: int
    ratio_percent: float


@dataclass(frozen=True)
class IoPayload:
    control_mode: int
    channel_count: int
    channels: tuple[IoChannelValue, ...]


@dataclass(frozen=True)
class SnetChannelMonitor:
    ad_raw: int
    flow_raw: int
    ratio_raw: int
    valve_raw: int


@dataclass(frozen=True)
class SnetMonitorSnapshot:
    status: int
    mode: int
    pressure_raw: int
    temperature_raw: int
    channel_count: int
    channels: tuple[SnetChannelMonitor, ...]


@dataclass(frozen=True)
class FrameView:
    raw: bytes
    stx: bytes
    seq: int
    frame_id: int
    ch: int
    cmd: int
    length: int
    data: bytes


@dataclass(frozen=True)
class ProtocolFrame:
    seq: int
    cmd: int
    raw: bytes
    view: FrameView
    io_payload: Optional[IoPayload] = None
    snet_monitor: Optional[SnetMonitorSnapshot] = None


@dataclass(frozen=True)
class SampleEvent:
    index: int
    seq: int
    request_raw: bytes
    response_raw: Optional[bytes]
    tx_payload: IoPayload
    rx_monitor: Optional[SnetMonitorSnapshot]
    latency_ms: float
    success: bool
