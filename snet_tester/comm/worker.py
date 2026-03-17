"""Serial communication worker thread."""

from collections import deque
import queue
import threading
import time
from typing import Optional

import serial

from ..config import SerialConfig
from ..protocol.codec import (
    build_brooks_get_kp_frame,
    build_frame,
    build_io_payload_bytes,
    build_read_var_frame,
    build_write_var_frame,
    brooks_response_cmd,
    decode_brooks_kp_payload,
    decode_var_value_payload,
    decode_frame_view,
    decode_io_payload,
    default_io_payload,
)
from ..protocol.constants import (
    BROOKS_GET_KP_CMD_L,
    BROOKS_GET_KP_TIMEOUT_S,
    FRAME_CH_DEFAULT,
    FRAME_ID_DEFAULT,
    REQUEST_CMD,
    RESPONSE_CMD,
    SEQ_START,
)
from ..protocol.parser import ProtocolParser
from ..protocol.types import IoPayload, SampleEvent


def _wait_for_response(
    ser,
    parser: ProtocolParser,
    expected_seq: int,
    timeout: float,
    expected_cmd: Optional[int] = RESPONSE_CMD,
    expected_ch: int = FRAME_CH_DEFAULT,
):
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
                    and frame.view.ch == expected_ch
                ):
                    return frame
        else:
            time.sleep(0.001)


class SerialWorker(threading.Thread):
    def __init__(
        self,
        event_queue: queue.SimpleQueue,
        command_queue: queue.SimpleQueue,
        stop_event: threading.Event,
        config: SerialConfig,
    ):
        super().__init__(daemon=True)
        self._queue = event_queue
        self._command_queue = command_queue
        self._stop_event = stop_event
        self._config = config

    def _drain_commands(self, running: bool, applied_payload: IoPayload):
        aux_commands = []
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
                aux_commands.append((kind, payload))
            elif kind == 'read_var':
                aux_commands.append((kind, payload))
            elif kind == 'brooks_get_kp':
                aux_commands.append((kind, int(payload)))

        return running, applied_payload, aux_commands

    def run(self):
        cfg = self._config
        parser = ProtocolParser()
        seq = SEQ_START
        index = 0
        running = False
        applied_payload = default_io_payload(channel_count=1)
        pending_var_commands = deque()

        try:
            with serial.Serial(
                cfg.port,
                cfg.baud,
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
                    running, applied_payload, aux_commands = self._drain_commands(running, applied_payload)
                    pending_var_commands.extend(aux_commands)

                    if pending_var_commands:
                        command_kind, payload = pending_var_commands.popleft()
                        expected_cmd = None
                        var_index = None
                        response_timeout = cfg.rx_timeout_s
                        if command_kind == 'write_var':
                            var_index, value = payload
                            request = build_write_var_frame(seq, var_index, value)
                        elif command_kind == 'read_var':
                            var_index = int(payload)
                            request = build_read_var_frame(seq, var_index)
                        else:
                            relay_channel = int(payload)
                            request = build_brooks_get_kp_frame(seq, ch=relay_channel)
                            expected_cmd = brooks_response_cmd(BROOKS_GET_KP_CMD_L)
                            response_timeout = max(cfg.rx_timeout_s, BROOKS_GET_KP_TIMEOUT_S)
                        tx_frame = decode_frame_view(request)

                        ser.reset_input_buffer()
                        parser.reset()

                        self._queue.put(('tx_frame', tx_frame))
                        ser.write(request)
                        ser.flush()

                        response = _wait_for_response(
                            ser, parser,
                            expected_seq=seq,
                            timeout=response_timeout,
                            expected_cmd=expected_cmd,
                            expected_ch=tx_frame.ch,
                        )
                        self._queue.put(('rx_frame', response.view if response is not None else None))
                        if command_kind in {'write_var', 'read_var'} and response is not None and var_index is not None:
                            decoded_var_value = decode_var_value_payload(response.view.data)
                            if decoded_var_value is not None and decoded_var_value[0] == var_index:
                                self._queue.put(('var_value', decoded_var_value))
                        elif command_kind == 'brooks_get_kp':
                            if response is None:
                                self._queue.put(('error', 'GET_KP response timeout'))
                            else:
                                decoded_kp_values = decode_brooks_kp_payload(response.view.data)
                                if decoded_kp_values is None:
                                    self._queue.put(('error', 'GET_KP response payload is invalid'))
                                else:
                                    self._queue.put(('brooks_kp_values', (response.view.ch, decoded_kp_values)))

                        seq = (seq + 1) & 0xFF
                        target_next = time.perf_counter() + cfg.sample_period_s
                        while not self._stop_event.is_set():
                            remain = target_next - time.perf_counter()
                            if remain <= 0:
                                break
                            running, applied_payload, extra = self._drain_commands(running, applied_payload)
                            if extra:
                                pending_var_commands.extend(extra)
                                break
                            time.sleep(min(0.01, remain))
                        continue

                    if not running:
                        time.sleep(0.01)
                        continue

                    index += 1
                    if not cfg.run_forever and index > cfg.test_count:
                        break

                    # I/O request cycle
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

                    response = _wait_for_response(ser, parser, expected_seq=seq, timeout=cfg.rx_timeout_s)
                    t_end = time.perf_counter()

                    latency_ms = (t_end - t_start) * 1000
                    response_raw = response.raw if response is not None else None
                    rx_monitor = response.snet_monitor if response is not None else None

                    self._queue.put(('rx_frame', response.view if response is not None else None))
                    self._queue.put(('rx_monitor', rx_monitor))
                    self._queue.put((
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
                    ))

                    seq = (seq + 1) & 0xFF

                    target_next = t_start + cfg.sample_period_s
                    while not self._stop_event.is_set():
                        remain = target_next - time.perf_counter()
                        if remain <= 0:
                            break
                        running, applied_payload, extra = self._drain_commands(running, applied_payload)
                        if extra:
                            pending_var_commands.extend(extra)
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
