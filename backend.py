import queue
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional, Sequence

import serial


PORT = 'COM6'
BAUD = 115200

RUN_FOREVER = True
TEST_COUNT = 100
RX_TIMEOUT_S = 1.0
SAMPLE_PERIOD_S = 0.05

HEADER = b'\xA5\x5A'
FRAME_IDX_STX_H = 0
FRAME_IDX_STX_L = 1
FRAME_IDX_SEQ = 2
FRAME_IDX_ID = 3
FRAME_IDX_CH = 4
FRAME_IDX_CMD_H = 5
FRAME_IDX_CMD_L = 6
FRAME_IDX_LEN = 7
FRAME_HEADER_LEN = 8
FRAME_IDX_PAYLOAD = FRAME_HEADER_LEN

FRAME_ID_DEFAULT = 0x00
FRAME_CH_DEFAULT = 0x00

REQUEST_CMD = 0x8000
RESPONSE_CMD = 0x8100
WRITE_VAR_CMD = 0x0002
MAX_PAYLOAD_LEN = 64
FRAME_FIXED_FIELDS = ('STX', 'SEQ', 'ID', 'CH', 'CMD', 'LEN')
FRAME_PANEL_PLACEHOLDER = '--'
HEX_DUMP_BYTES_PER_LINE = 16
MAX_CHANNELS = 6
SEQ_START = 0xC0
IO_CONTROL_MODE_DEFAULT = 0x00
IO_OVERRIDE_DEFAULT = 0x00
RATIO_FULL_SCALE_RAW = 0x8000
TEMPERATURE_FULL_SCALE_RAW = 0x8000
TEMPERATURE_FULL_SCALE_C = 100.0
PRESSURE_FULL_SCALE_RAW = 0x8000
PRESSURE_FULL_SCALE_PSI = 100.0
SNET_MONITOR_HEADER_LEN = 6
WRITE_VAR_READ_AD_FLAG_INDEX = 0x0001


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


def clamp_channel_count(channel_count: int) -> int:
    return max(1, min(MAX_CHANNELS, int(channel_count)))


def clamp_percent(percent: float) -> float:
    return max(0.0, min(100.0, float(percent)))


def ratio_percent_to_raw(percent: float) -> int:
    return int(round((clamp_percent(percent) / 100.0) * RATIO_FULL_SCALE_RAW))


def ratio_raw_to_percent(ratio_raw: int) -> float:
    ratio = max(0, min(RATIO_FULL_SCALE_RAW, int(ratio_raw)))
    return (ratio / RATIO_FULL_SCALE_RAW) * 100.0


def temperature_raw_to_celsius(temperature_raw: int) -> float:
    raw = max(0, min(TEMPERATURE_FULL_SCALE_RAW, int(temperature_raw)))
    return (raw / TEMPERATURE_FULL_SCALE_RAW) * TEMPERATURE_FULL_SCALE_C


def pressure_raw_to_psi(pressure_raw: int) -> float:
    raw = max(0, min(PRESSURE_FULL_SCALE_RAW, int(pressure_raw)))
    return (raw / PRESSURE_FULL_SCALE_RAW) * PRESSURE_FULL_SCALE_PSI


def flow_raw_to_display(flow_raw: int) -> float:
    raw = max(0, min(RATIO_FULL_SCALE_RAW, int(flow_raw)))
    return (raw / RATIO_FULL_SCALE_RAW) * 100.0


def valve_raw_to_display(valve_raw: int) -> float:
    raw = max(0, min(RATIO_FULL_SCALE_RAW, int(valve_raw)))
    return (raw / RATIO_FULL_SCALE_RAW) * 5.0


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


def build_write_var_payload(var_index: int, value: int) -> bytes:
    return (
        int(var_index).to_bytes(2, byteorder='big', signed=False)
        + int(value).to_bytes(8, byteorder='big', signed=False)
    )


def build_write_var_frame(seq: int, var_index: int, value: int) -> bytes:
    return build_frame(seq, WRITE_VAR_CMD, build_write_var_payload(var_index, value))


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
        frame_id=raw[FRAME_IDX_ID],
        ch=raw[FRAME_IDX_CH],
        cmd=(raw[FRAME_IDX_CMD_H] << 8) | raw[FRAME_IDX_CMD_L],
        length=payload_len,
        data=raw[FRAME_IDX_PAYLOAD:FRAME_IDX_PAYLOAD + payload_len],
    )


class ProtocolParser:
    def __init__(self):
        self._buf = bytearray()

    def reset(self):
        self._buf.clear()

    def feed(self, data: bytes):
        if data:
            self._buf.extend(data)

        frames = []

        while True:
            idx = self._buf.find(HEADER)
            if idx < 0:
                if len(self._buf) > 1:
                    del self._buf[:-1]
                break

            if idx > 0:
                del self._buf[:idx]

            if len(self._buf) < FRAME_HEADER_LEN:
                break

            cmd = (self._buf[FRAME_IDX_CMD_H] << 8) | self._buf[FRAME_IDX_CMD_L]
            payload_len = self._buf[FRAME_IDX_LEN]
            frame_len = FRAME_HEADER_LEN + payload_len

            if payload_len > MAX_PAYLOAD_LEN:
                del self._buf[0]
                continue

            if len(self._buf) < frame_len:
                break

            candidate = bytes(self._buf[:frame_len])
            frame_view = decode_frame_view(candidate)
            io_payload = decode_io_payload(frame_view.data)
            snet_monitor = decode_snet_monitor_payload(frame_view.data)
            frames.append(
                ProtocolFrame(
                    seq=frame_view.seq,
                    cmd=frame_view.cmd,
                    raw=frame_view.raw,
                    view=frame_view,
                    io_payload=io_payload,
                    snet_monitor=snet_monitor,
                )
            )
            del self._buf[:frame_len]

        return frames


def build_frame(seq: int, cmd: int, payload: bytes = b'') -> bytes:
    if len(payload) > 0xFF:
        raise ValueError('payload length must be <= 255')

    return (
        HEADER
        + bytes(
            (
                seq & 0xFF,
                FRAME_ID_DEFAULT & 0xFF,
                FRAME_CH_DEFAULT & 0xFF,
                (cmd >> 8) & 0xFF,
                cmd & 0xFF,
                len(payload) & 0xFF,
            )
        )
        + payload
    )


def wait_for_response(ser, parser: ProtocolParser, expected_seq: int, timeout=RX_TIMEOUT_S, expected_cmd: Optional[int] = RESPONSE_CMD):
    start = time.perf_counter()

    while True:
        if (time.perf_counter() - start) > timeout:
            return None

        waiting = ser.in_waiting
        if waiting > 0:
            data = ser.read(waiting)
            frames = parser.feed(data)
            for frame in frames:
                if (
                    frame.seq == expected_seq
                    and (expected_cmd is None or frame.cmd == expected_cmd)
                    and frame.view.frame_id == FRAME_ID_DEFAULT
                    and frame.view.ch == FRAME_CH_DEFAULT
                ):
                    return frame
        else:
            time.sleep(0.001)


def hex_bytes(data: bytes) -> str:
    if not data:
        return '0x'
    return '0x ' + ' '.join(f'{byte:02X}' for byte in data)


def frame_view_fixed_rows(frame_view: FrameView):
    return {
        'STX': hex_bytes(frame_view.stx),
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
        return FRAME_PANEL_PLACEHOLDER

    parts = []
    for index, channel in enumerate(io_payload.channels[:io_payload.channel_count], start=1):
        parts.append(f'CH{index}={channel.ratio_percent:6.2f}% (0x{channel.ratio_raw:04X})')
    return ', '.join(parts)


def format_monitor_summary(snet_monitor: Optional[SnetMonitorSnapshot]) -> str:
    if snet_monitor is None or snet_monitor.channel_count == 0:
        return FRAME_PANEL_PLACEHOLDER

    parts = []
    for index, channel in enumerate(snet_monitor.channels[:snet_monitor.channel_count], start=1):
        parts.append(f'CH{index}={ratio_raw_to_percent(channel.ratio_raw):6.2f}% (0x{channel.ratio_raw:04X})')
    return ', '.join(parts)


def monitor_channel_ratio_percents(snet_monitor: Optional[SnetMonitorSnapshot]) -> list[Optional[float]]:
    ratios = [None] * MAX_CHANNELS
    if snet_monitor is None:
        return ratios

    for index, channel in enumerate(snet_monitor.channels[:snet_monitor.channel_count]):
        ratios[index] = ratio_raw_to_percent(channel.ratio_raw)
    return ratios


def first_monitor_ratio_percent(snet_monitor: Optional[SnetMonitorSnapshot]) -> Optional[float]:
    if snet_monitor is None or snet_monitor.channel_count < 1:
        return None
    return ratio_raw_to_percent(snet_monitor.channels[0].ratio_raw)


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


def format_sample_log(event: SampleEvent) -> str:
    status = 'OK' if event.success else 'FAIL'
    if event.response_raw is None:
        rsp_text = 'TIMEOUT'
    else:
        rsp_text = f"{hex_bytes(event.response_raw)} | {format_monitor_summary(event.rx_monitor)}"

    index_text = f"{event.index:6d}" if RUN_FOREVER else f"{event.index:3d}/{TEST_COUNT}"
    return (
        f'  [{index_text}] {status} | SEQ=0x{event.seq:02X} | '
        f'TX: {format_channel_summary(event.tx_payload)} | RX: {rsp_text} | '
        f'LAT={event.latency_ms:7.2f} ms'
    )


class SerialWorker(threading.Thread):
    def __init__(self, event_queue: queue.SimpleQueue, command_queue: queue.SimpleQueue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self._queue = event_queue
        self._command_queue = command_queue
        self._stop_event = stop_event

    def _drain_commands(self, running: bool, applied_payload: IoPayload):
        write_var_values = []
        while True:
            try:
                kind, payload = self._command_queue.get_nowait()
            except queue.Empty:
                break

            if kind == 'set_running':
                running = bool(payload)
                self._queue.put(('run_state', running))
            elif kind == 'apply_setpoint':
                applied_payload = payload
                self._queue.put(('applied_setpoint', applied_payload))
            elif kind == 'write_var':
                write_var_values.append(int(payload))

        return running, applied_payload, write_var_values

    def run(self):
        parser = ProtocolParser()
        seq = SEQ_START
        index = 0
        running = False
        applied_payload = default_io_payload(channel_count=1)
        pending_write_var_values = []

        try:
            with serial.Serial(
                PORT,
                BAUD,
                parity=serial.PARITY_ODD,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                timeout=0,
            ) as ser:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                time.sleep(0.1)
                self._queue.put(('applied_setpoint', applied_payload))
                self._queue.put(('run_state', running))

                while not self._stop_event.is_set():
                    running, applied_payload, write_var_values = self._drain_commands(running, applied_payload)
                    pending_write_var_values.extend(write_var_values)
                    if pending_write_var_values:
                        pending_write_var_values = [pending_write_var_values[-1]]

                    if pending_write_var_values:
                        value = pending_write_var_values.pop()
                        request = build_write_var_frame(seq, WRITE_VAR_READ_AD_FLAG_INDEX, value)
                        tx_frame = decode_frame_view(request)

                        ser.reset_input_buffer()
                        parser.reset()

                        self._queue.put(('tx_frame', tx_frame))
                        ser.write(request)
                        ser.flush()

                        response = wait_for_response(
                            ser,
                            parser,
                            expected_seq=seq,
                            timeout=RX_TIMEOUT_S,
                            expected_cmd=None,
                        )
                        self._queue.put(('rx_frame', response.view if response is not None else None))

                        seq = (seq + 1) & 0xFF
                        target_next = time.perf_counter() + SAMPLE_PERIOD_S
                        while not self._stop_event.is_set():
                            remain = target_next - time.perf_counter()
                            if remain <= 0:
                                break
                            running, applied_payload, extra_write_var_values = self._drain_commands(running, applied_payload)
                            if extra_write_var_values:
                                pending_write_var_values.extend(extra_write_var_values)
                                pending_write_var_values = [pending_write_var_values[-1]]
                                break
                            time.sleep(min(0.01, remain))
                        continue

                    if not running:
                        time.sleep(0.01)
                        continue

                    index += 1
                    if not RUN_FOREVER and index > TEST_COUNT:
                        break

                    request_payload = build_io_payload_bytes(applied_payload)
                    request = build_frame(seq, REQUEST_CMD, request_payload)
                    tx_frame = decode_frame_view(request)
                    tx_payload = decode_io_payload(tx_frame.data)

                    ser.reset_input_buffer()
                    parser.reset()

                    t_start = time.perf_counter()
                    self._queue.put(('tx_frame', tx_frame))
                    ser.write(request)
                    ser.flush()

                    response = wait_for_response(ser, parser, expected_seq=seq, timeout=RX_TIMEOUT_S)
                    t_end = time.perf_counter()

                    latency_ms = (t_end - t_start) * 1000
                    response_raw = response.raw if response is not None else None
                    rx_monitor = response.snet_monitor if response is not None else None

                    self._queue.put(('rx_frame', response.view if response is not None else None))
                    self._queue.put(('rx_monitor', rx_monitor))
                    self._queue.put(
                        (
                            'sample',
                            SampleEvent(
                                index=index,
                                seq=seq,
                                request_raw=request,
                                response_raw=response_raw,
                                tx_payload=tx_payload if tx_payload is not None else applied_payload,
                                rx_monitor=rx_monitor,
                                latency_ms=latency_ms,
                                success=response is not None,
                            ),
                        )
                    )

                    seq = (seq + 1) & 0xFF

                    target_next = t_start + SAMPLE_PERIOD_S
                    while not self._stop_event.is_set():
                        remain = target_next - time.perf_counter()
                        if remain <= 0:
                            break
                        running, applied_payload, extra_write_var_values = self._drain_commands(running, applied_payload)
                        if extra_write_var_values:
                            pending_write_var_values.extend(extra_write_var_values)
                            pending_write_var_values = [pending_write_var_values[-1]]
                            break
                        if not running:
                            break
                        time.sleep(min(0.01, remain))

        except serial.SerialException as exc:
            self._queue.put(('error', f'[Serial Error] {exc}'))
        except Exception as exc:
            self._queue.put(('error', f'[Worker Error] {exc}'))
        finally:
            self._queue.put(('done', None))
