"""SNET frame encoding/decoding and payload serialization."""

from typing import Optional, Sequence

from .constants import (
    FRAME_HEADER_LEN,
    FRAME_IDX_CMD_H,
    FRAME_IDX_CMD_L,
    FRAME_IDX_LEN,
    FRAME_IDX_PAYLOAD,
    FRAME_IDX_SEQ,
    FRAME_IDX_STX_H,
    FRAME_IDX_STX_L,
    FRAME_ID_DEFAULT,
    FRAME_CH_DEFAULT,
    FRAME_FIXED_FIELDS,
    HEADER,
    HEX_DUMP_BYTES_PER_LINE,
    IO_CONTROL_MODE_DEFAULT,
    IO_OVERRIDE_DEFAULT,
    MAX_CHANNELS,
    PLACEHOLDER,
    RATIO_FULL_SCALE_RAW,
    SNET_MONITOR_HEADER_LEN,
    WRITE_VAR_CMD,
    WRITE_VAR_READ_AD_FLAG_INDEX,
)
from .convert import ratio_percent_to_raw, ratio_raw_to_percent
from .types import (
    FrameView,
    IoChannelValue,
    IoPayload,
    SnetChannelMonitor,
    SnetMonitorSnapshot,
)


# --- Channel count ---

def clamp_channel_count(channel_count: int) -> int:
    return max(1, min(MAX_CHANNELS, int(channel_count)))


# --- IoPayload build / encode / decode ---

def build_io_payload_model(
    channel_count: int,
    ratio_percents: Sequence[float],
    control_mode: int = IO_CONTROL_MODE_DEFAULT,
    overrides: Optional[Sequence[int]] = None,
) -> IoPayload:
    normalized_count = clamp_channel_count(channel_count)
    ratio_values = list(ratio_percents)
    override_values = list(overrides) if overrides is not None else []
    channels = []

    for index in range(normalized_count):
        percent = ratio_values[index] if index < len(ratio_values) else 0.0
        override = override_values[index] if index < len(override_values) else IO_OVERRIDE_DEFAULT
        ratio_raw = ratio_percent_to_raw(percent)
        channels.append(
            IoChannelValue(
                override=override & 0xFF,
                ratio_raw=ratio_raw,
                ratio_percent=ratio_raw_to_percent(ratio_raw),
            )
        )

    return IoPayload(
        control_mode=control_mode & 0xFF,
        channel_count=normalized_count,
        channels=tuple(channels),
    )


def default_io_payload(channel_count: int = 1) -> IoPayload:
    return build_io_payload_model(channel_count=channel_count, ratio_percents=[0.0] * channel_count)


def build_io_payload_bytes(io_payload: IoPayload) -> bytes:
    payload = bytearray((io_payload.control_mode & 0xFF,))
    for channel in io_payload.channels[:io_payload.channel_count]:
        payload.append(channel.override & 0xFF)
        payload.extend(channel.ratio_raw.to_bytes(2, byteorder='big', signed=False))
    return bytes(payload)


def decode_io_payload(payload: bytes) -> Optional[IoPayload]:
    if len(payload) < 1:
        return None

    body_len = len(payload) - 1
    if body_len % 3 != 0:
        return None

    channel_count = body_len // 3
    if channel_count < 1 or channel_count > MAX_CHANNELS:
        return None

    channels = []
    for index in range(channel_count):
        base = 1 + (index * 3)
        override = payload[base]
        ratio_raw = int.from_bytes(payload[base + 1:base + 3], byteorder='big', signed=False)
        channels.append(
            IoChannelValue(
                override=override,
                ratio_raw=ratio_raw,
                ratio_percent=ratio_raw_to_percent(ratio_raw),
            )
        )

    return IoPayload(
        control_mode=payload[0],
        channel_count=channel_count,
        channels=tuple(channels),
    )


# --- SnetMonitorSnapshot decode ---

def decode_snet_monitor_payload(payload: bytes) -> Optional[SnetMonitorSnapshot]:
    if len(payload) < SNET_MONITOR_HEADER_LEN:
        return None

    body_len = len(payload) - SNET_MONITOR_HEADER_LEN
    if body_len % 8 != 0:
        return None

    channel_count = body_len // 8
    if channel_count < 1 or channel_count > MAX_CHANNELS:
        return None

    channels = []
    for index in range(channel_count):
        base = SNET_MONITOR_HEADER_LEN + (index * 8)
        channels.append(
            SnetChannelMonitor(
                ad_raw=int.from_bytes(payload[base:base + 2], byteorder='big', signed=False),
                flow_raw=int.from_bytes(payload[base + 2:base + 4], byteorder='big', signed=False),
                ratio_raw=int.from_bytes(payload[base + 4:base + 6], byteorder='big', signed=False),
                valve_raw=int.from_bytes(payload[base + 6:base + 8], byteorder='big', signed=False),
            )
        )

    return SnetMonitorSnapshot(
        status=payload[0],
        mode=payload[1],
        pressure_raw=int.from_bytes(payload[2:4], byteorder='big', signed=False),
        temperature_raw=int.from_bytes(payload[4:6], byteorder='big', signed=False),
        channel_count=channel_count,
        channels=tuple(channels),
    )


# --- Frame build / decode ---

def decode_frame_view(frame_bytes: bytes) -> FrameView:
    if len(frame_bytes) < FRAME_HEADER_LEN:
        raise ValueError('frame too short')

    payload_len = frame_bytes[FRAME_IDX_LEN]
    frame_len = FRAME_HEADER_LEN + payload_len
    if len(frame_bytes) < frame_len:
        raise ValueError('frame payload is incomplete')

    raw = bytes(frame_bytes[:frame_len])
    return FrameView(
        raw=raw,
        stx=raw[FRAME_IDX_STX_H:FRAME_IDX_STX_L + 1],
        seq=raw[FRAME_IDX_SEQ],
        frame_id=raw[3],
        ch=raw[4],
        cmd=(raw[FRAME_IDX_CMD_H] << 8) | raw[FRAME_IDX_CMD_L],
        length=payload_len,
        data=raw[FRAME_IDX_PAYLOAD:FRAME_IDX_PAYLOAD + payload_len],
    )


def build_frame(seq: int, cmd: int, payload: bytes = b'') -> bytes:
    if len(payload) > 0xFF:
        raise ValueError('payload length must be <= 255')

    return (
        HEADER
        + bytes((
            seq & 0xFF,
            FRAME_ID_DEFAULT & 0xFF,
            FRAME_CH_DEFAULT & 0xFF,
            (cmd >> 8) & 0xFF,
            cmd & 0xFF,
            len(payload) & 0xFF,
        ))
        + payload
    )


def build_write_var_payload(var_index: int, value: int) -> bytes:
    return (
        int(var_index).to_bytes(2, byteorder='big', signed=False)
        + int(value).to_bytes(8, byteorder='big', signed=False)
    )


def build_write_var_frame(seq: int, var_index: int, value: int) -> bytes:
    return build_frame(seq, WRITE_VAR_CMD, build_write_var_payload(var_index, value))


# --- Mock data ---

def build_mock_snet_monitor_payload(io_payload: IoPayload) -> bytes:
    payload = bytearray((0x00, io_payload.control_mode & 0xFF))
    payload.extend((0x20, 0x7A, 0x19, 0x74))

    for index, channel in enumerate(io_payload.channels[:io_payload.channel_count], start=1):
        ad_raw = min(0xFFFF, 0x1000 + (index * 0x0200) + (channel.ratio_raw // 0x40))
        flow_raw = min(0xFFFF, channel.ratio_raw // 0x80)
        ratio_raw = channel.ratio_raw
        valve_raw = min(0xFFFF, channel.ratio_raw)
        payload.extend(ad_raw.to_bytes(2, byteorder='big', signed=False))
        payload.extend(flow_raw.to_bytes(2, byteorder='big', signed=False))
        payload.extend(ratio_raw.to_bytes(2, byteorder='big', signed=False))
        payload.extend(valve_raw.to_bytes(2, byteorder='big', signed=False))

    return bytes(payload)


# --- Display formatting ---

def hex_bytes(data: bytes) -> str:
    if not data:
        return '0x'
    return '0x ' + ' '.join(f'{byte:02X}' for byte in data)


def frame_view_fixed_rows(frame_view: FrameView) -> dict[str, str]:
    return {
        'STX': '0x' + frame_view.stx.hex().upper(),
        'SEQ': f'0x{frame_view.seq:02X}',
        'ID': f'0x{frame_view.frame_id:02X}',
        'CH': f'0x{frame_view.ch:02X}',
        'CMD': f'0x{frame_view.cmd:04X}',
        'LEN': f'0x{frame_view.length:02X}',
    }


def format_data_hexdump(data: bytes, bytes_per_line: int = HEX_DUMP_BYTES_PER_LINE) -> str:
    if not data:
        return '0x'

    lines = []
    for offset in range(0, len(data), bytes_per_line):
        chunk = data[offset:offset + bytes_per_line]
        lines.append(f'{offset:04X}: ' + ' '.join(f'{byte:02X}' for byte in chunk))
    return '\n'.join(lines)


def format_channel_summary(io_payload: Optional[IoPayload]) -> str:
    if io_payload is None or io_payload.channel_count == 0:
        return PLACEHOLDER

    parts = []
    for index, channel in enumerate(io_payload.channels[:io_payload.channel_count], start=1):
        parts.append(f'CH{index}={channel.ratio_percent:6.2f}% (0x{channel.ratio_raw:04X})')
    return ', '.join(parts)


def format_monitor_summary(snet_monitor: Optional[SnetMonitorSnapshot]) -> str:
    if snet_monitor is None or snet_monitor.channel_count == 0:
        return PLACEHOLDER

    parts = []
    for index, channel in enumerate(snet_monitor.channels[:snet_monitor.channel_count], start=1):
        parts.append(f'CH{index}={ratio_raw_to_percent(channel.ratio_raw):6.2f}% (0x{channel.ratio_raw:04X})')
    return ', '.join(parts)


def monitor_channel_ratio_percents(snet_monitor: Optional[SnetMonitorSnapshot]) -> list[Optional[float]]:
    ratios: list[Optional[float]] = [None] * MAX_CHANNELS
    if snet_monitor is None:
        return ratios

    for index, channel in enumerate(snet_monitor.channels[:snet_monitor.channel_count]):
        ratios[index] = ratio_raw_to_percent(channel.ratio_raw)
    return ratios


def first_monitor_ratio_percent(snet_monitor: Optional[SnetMonitorSnapshot]) -> Optional[float]:
    if snet_monitor is None or snet_monitor.channel_count < 1:
        return None
    return ratio_raw_to_percent(snet_monitor.channels[0].ratio_raw)


def format_sample_log(event, run_forever: bool = True, test_count: int = 100) -> str:
    from .types import SampleEvent
    status = 'OK' if event.success else 'FAIL'
    if event.response_raw is None:
        rsp_text = 'TIMEOUT'
    else:
        rsp_text = f"{hex_bytes(event.response_raw)} | {format_monitor_summary(event.rx_monitor)}"

    index_text = f"{event.index:6d}" if run_forever else f"{event.index:3d}/{test_count}"
    return (
        f'  [{index_text}] {status} | SEQ=0x{event.seq:02X} | '
        f'TX: {format_channel_summary(event.tx_payload)} | RX: {rsp_text} | '
        f'LAT={event.latency_ms:7.2f} ms'
    )
