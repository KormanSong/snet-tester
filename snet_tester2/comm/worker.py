"""Serial communication worker thread.

Runs on a daemon thread, owns the TX/RX loop against a Transport.
Communicates with the UI thread via two queues:
  - command_queue (UI -> Worker): typed WorkerCommand dataclasses
  - event_queue   (Worker -> UI): typed WorkerEvent dataclasses

This is a refactoring of v1's snet_tester/comm/worker.py.
Key changes from v1:
  1. Takes a Transport instead of creating serial.Serial internally.
  2. Uses typed dataclass events/commands instead of ('kind', payload) tuples.
  3. Uses SnetCommand enum instead of bare REQUEST_CMD/RESPONSE_CMD constants.
  4. Catches OSError instead of serial.SerialException.
  5. write() only (no flush) -- Transport.write guarantees delivery.

The main loop algorithm, timing logic, pending_var_commands deque
pattern, and seq incrementing are preserved exactly as v1.
"""

from collections import deque
import queue
import threading
import time
from typing import Optional

from ..transport.base import Transport
from ..config import WorkerConfig

from .commands import (
    ApplySetpointCommand,
    BrooksGetKpCommand,
    ReadVarCommand,
    SetRunningCommand,
    WriteVarCommand,
)
from .events import (
    AppliedSetpointEvent,
    BrooksKpEvent,
    ErrorEvent,
    RxFrameEvent,
    RxMonitorEvent,
    RunStateEvent,
    SampleReceivedEvent,
    TxFrameEvent,
    VarValueEvent,
    WorkerDoneEvent,
)
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
    SEQ_START,
)
from ..protocol.enums import SnetCommand
from ..protocol.parser import ProtocolParser
from ..protocol.types import IoPayload, SampleEvent


def _wait_for_response(
    transport: Transport,
    parser: ProtocolParser,
    expected_seq: int,
    timeout: float,
    expected_cmd: Optional[int] = SnetCommand.IO_RESPONSE,
    expected_ch: int = FRAME_CH_DEFAULT,
):
    """Block until a matching response frame arrives or timeout elapses.

    Args:
        transport: Open transport to read bytes from.
        parser: ProtocolParser instance (caller should reset before call).
        expected_seq: Sequence number to match.
        timeout: Maximum wait time in seconds.
        expected_cmd: Command code to match, or None to accept any.
        expected_ch: Channel byte to match.

    Returns:
        ProtocolFrame if a matching frame is found, None on timeout.
    """
    start = time.perf_counter()

    while True:
        if (time.perf_counter() - start) > timeout:
            return None

        waiting = transport.in_waiting
        if waiting > 0:
            data = transport.read(waiting)
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
    """Daemon thread that runs the SNET TX/RX polling loop.

    Args:
        transport: An opened (or openable) Transport backend.
        event_queue: SimpleQueue for emitting WorkerEvent to the UI.
        command_queue: SimpleQueue for receiving WorkerCommand from the UI.
        stop_event: Threading event signalling graceful shutdown.
        config: WorkerConfig with timing parameters.
    """

    def __init__(
        self,
        transport: Transport,
        event_queue: queue.SimpleQueue,
        command_queue: queue.SimpleQueue,
        stop_event: threading.Event,
        config: WorkerConfig,
    ):
        super().__init__(daemon=True)
        self._transport = transport
        self._queue = event_queue
        self._command_queue = command_queue
        self._stop_event = stop_event
        self._config = config

    def _drain_commands(self, running: bool, applied_payload: IoPayload):
        """Consume all pending commands from the queue without blocking.

        Args:
            running: Current run state.
            applied_payload: Current active IoPayload.

        Returns:
            (running, applied_payload, aux_commands) -- updated state
            and a list of auxiliary commands (var read/write, Brooks KP).
        """
        aux_commands = []
        while True:
            try:
                cmd = self._command_queue.get_nowait()
            except queue.Empty:
                break

            if isinstance(cmd, SetRunningCommand):
                running = cmd.running
                self._queue.put(RunStateEvent(running=running))
            elif isinstance(cmd, ApplySetpointCommand):
                applied_payload = cmd.payload
                self._queue.put(AppliedSetpointEvent(payload=applied_payload))
            elif isinstance(cmd, (WriteVarCommand, ReadVarCommand, BrooksGetKpCommand)):
                aux_commands.append(cmd)

        return running, applied_payload, aux_commands

    def run(self):
        """Main worker loop -- opened transport, polls commands, sends/receives frames."""
        cfg = self._config
        parser = ProtocolParser()
        seq = SEQ_START
        index = 0
        running = False
        applied_payload = default_io_payload(channel_count=1)
        pending_var_commands: deque = deque()

        try:
            self._transport.open()
            self._transport.reset_input_buffer()
            self._transport.reset_output_buffer()
            time.sleep(0.1)
            self._queue.put(AppliedSetpointEvent(payload=applied_payload))
            self._queue.put(RunStateEvent(running=running))

            while not self._stop_event.is_set():
                running, applied_payload, aux_commands = self._drain_commands(running, applied_payload)
                pending_var_commands.extend(aux_commands)

                # --- Auxiliary command processing (var read/write, Brooks KP) ---
                if pending_var_commands:
                    cmd = pending_var_commands.popleft()
                    expected_cmd = None
                    var_index = None
                    response_timeout = cfg.rx_timeout_s

                    if isinstance(cmd, WriteVarCommand):
                        var_index = cmd.var_index
                        request = build_write_var_frame(seq, cmd.var_index, cmd.value)
                    elif isinstance(cmd, ReadVarCommand):
                        var_index = cmd.var_index
                        request = build_read_var_frame(seq, cmd.var_index)
                    else:  # BrooksGetKpCommand
                        request = build_brooks_get_kp_frame(seq, ch=cmd.channel)
                        expected_cmd = brooks_response_cmd(BROOKS_GET_KP_CMD_L)
                        response_timeout = max(cfg.rx_timeout_s, BROOKS_GET_KP_TIMEOUT_S)

                    tx_frame = decode_frame_view(request)

                    self._transport.reset_input_buffer()
                    parser.reset()

                    self._queue.put(TxFrameEvent(frame=tx_frame))
                    self._transport.write(request)

                    response = _wait_for_response(
                        self._transport, parser,
                        expected_seq=seq,
                        timeout=response_timeout,
                        expected_cmd=expected_cmd,
                        expected_ch=tx_frame.ch,
                    )
                    self._queue.put(RxFrameEvent(frame=response.view if response is not None else None))

                    if isinstance(cmd, (WriteVarCommand, ReadVarCommand)) and response is not None and var_index is not None:
                        decoded_var_value = decode_var_value_payload(response.view.data)
                        if decoded_var_value is not None and decoded_var_value[0] == var_index:
                            self._queue.put(VarValueEvent(var_index=decoded_var_value[0], value=decoded_var_value[1]))
                    elif isinstance(cmd, BrooksGetKpCommand):
                        if response is None:
                            self._queue.put(ErrorEvent(message='GET_KP response timeout'))
                        else:
                            decoded_kp_values = decode_brooks_kp_payload(response.view.data)
                            if decoded_kp_values is None:
                                self._queue.put(ErrorEvent(message='GET_KP response payload is invalid'))
                            else:
                                self._queue.put(BrooksKpEvent(channel=response.view.ch, values=decoded_kp_values))

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

                # --- Idle when not running ---
                if not running:
                    time.sleep(0.01)
                    continue

                # --- I/O request cycle ---
                index += 1
                if not cfg.run_forever and index > cfg.test_count:
                    break

                request_payload = build_io_payload_bytes(applied_payload)
                request = build_frame(seq, SnetCommand.IO_REQUEST, request_payload)
                tx_frame = decode_frame_view(request)
                tx_payload = decode_io_payload(tx_frame.data)

                self._transport.reset_input_buffer()
                parser.reset()

                t_start = time.perf_counter()
                self._queue.put(TxFrameEvent(frame=tx_frame))
                self._transport.write(request)

                response = _wait_for_response(self._transport, parser, expected_seq=seq, timeout=cfg.rx_timeout_s)
                t_end = time.perf_counter()

                latency_ms = (t_end - t_start) * 1000
                response_raw = response.raw if response is not None else None
                rx_monitor = response.snet_monitor if response is not None else None

                self._queue.put(RxFrameEvent(frame=response.view if response is not None else None))
                self._queue.put(RxMonitorEvent(monitor=rx_monitor))
                self._queue.put(SampleReceivedEvent(
                    sample=SampleEvent(
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

        except OSError as exc:
            self._queue.put(ErrorEvent(message=f'[Serial Error] {exc}'))
        except Exception as exc:
            self._queue.put(ErrorEvent(message=f'[Worker Error] {exc}'))
        finally:
            self._transport.close()
            self._queue.put(WorkerDoneEvent())
