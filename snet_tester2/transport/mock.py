"""MockTransport -- in-memory transport with programmable fault injection.

Implements the Transport protocol for testing without real hardware.
Parses outgoing SNET frames, generates plausible responses, and
buffers them for the caller to read back. A FaultScript mechanism
lets tests inject specific error conditions (timeout, corruption,
disconnect, etc.) at precise request indices.

Response generation logic:
  - IO_REQUEST  -> build mock monitor payload, wrap in IO_RESPONSE frame
  - WRITE_VAR   -> echo the request frame, store variable value
  - READ_VAR    -> respond with WRITE_VAR frame containing stored value
  - BROOKS_GET_KP -> respond with KP values from constructor parameter
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..protocol.codec import (
    build_frame,
    build_write_var_frame,
    build_brooks_get_kp_response_frame,
    decode_io_payload,
    decode_var_value_payload,
)
from ..protocol.constants import (
    BROOKS_GET_KP_CMD_L,
    BROOKS_REQUEST_CMD_BASE,
    FRAME_IDX_CH,
    FRAME_IDX_CMD_H,
    FRAME_IDX_CMD_L,
    FRAME_IDX_SEQ,
)
from ..protocol.enums import SnetCommand
from ..protocol.parser import ProtocolParser
from ..protocol.types import IoPayload, ProtocolFrame


# ---------------------------------------------------------------------------
# Mock data helper (ported from v1 codec.py:328-342)
# ---------------------------------------------------------------------------

def build_mock_snet_monitor_payload(io_payload: IoPayload) -> bytes:
    """Build a synthetic SNET monitor response payload.

    Generates plausible AD, flow, ratio, and valve values derived from
    the request's channel ratios so the UI sees moving data.

    Parameters
    ----------
    io_payload : IoPayload
        The I/O request that triggered this response.

    Returns
    -------
    bytes
        Monitor payload ready to be wrapped in an IO_RESPONSE frame.
    """
    # 2-byte header: status=0x00, mode=control_mode
    payload = bytearray((0x00, io_payload.control_mode & 0xFF))
    # 4-byte pressure/temperature stub
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


# ---------------------------------------------------------------------------
# Fault injection types
# ---------------------------------------------------------------------------

class FaultKind(Enum):
    """Fault types that MockTransport can inject."""
    TIMEOUT     = "timeout"      # No response buffered at all
    CORRUPT     = "corrupt"      # XOR some payload bytes
    PARTIAL     = "partial"      # Only buffer first half of response
    WRONG_SEQ   = "wrong_seq"    # Modify seq byte in response
    WRONG_CMD   = "wrong_cmd"    # Modify cmd bytes in response
    WRONG_CH    = "wrong_ch"     # Modify ch byte in response
    DISCONNECT  = "disconnect"   # Close transport, raise OSError
    OPEN_FAIL   = "open_fail"    # Fail on open()
    INVALID_KP  = "invalid_kp"   # Truncate KP response payload


@dataclass(frozen=True)
class FaultRule:
    """Schedules a fault at a specific request index.

    Parameters
    ----------
    at_request : int
        0-based request index where the fault fires.
        Use -1 to trigger at open() time.
    kind : FaultKind
        Which fault to inject.
    """
    at_request: int
    kind: FaultKind


# ---------------------------------------------------------------------------
# MockTransport
# ---------------------------------------------------------------------------

class MockTransport:
    """In-memory Transport with programmable fault injection.

    Parameters
    ----------
    faults : list[FaultRule] | None
        Optional list of faults to inject at specific request indices.
    kp_values : tuple[float, ...]
        KP calibration values returned by BROOKS_GET_KP responses.
        Defaults to (0.25, 0.75, 1.5, 3.0, 4.5, 6.0).
    """

    def __init__(
        self,
        faults: list[FaultRule] | None = None,
        kp_values: tuple[float, ...] = (0.25, 0.75, 1.5, 3.0, 4.5, 6.0),
    ):
        self._faults: dict[int, FaultKind] = {
            f.at_request: f.kind for f in (faults or [])
        }
        self._rx_buffer = bytearray()
        self._request_count = 0
        self._is_open = False
        self._var_values: dict[int, int] = {}
        self._kp_values = kp_values
        self._parser = ProtocolParser()

    # -- Lifecycle --

    def open(self) -> None:
        """Open the mock transport.

        Raises
        ------
        OSError
            If an OPEN_FAIL fault is scheduled at request index -1.
        """
        fault = self._faults.get(-1)
        if fault == FaultKind.OPEN_FAIL:
            raise OSError("Mock: port open failed")
        self._is_open = True

    def close(self) -> None:
        """Close the mock transport and reset all session state."""
        self._is_open = False
        self._rx_buffer.clear()
        self._request_count = 0
        self._var_values.clear()
        self._parser.reset()

    # -- Data I/O --

    def write(self, data: bytes) -> None:
        """Parse outgoing SNET frame(s) and generate mock responses.

        For each valid frame found in *data*, a response is generated
        based on the command type and (optionally) corrupted according
        to the fault schedule.

        Parameters
        ----------
        data : bytes
            Raw frame bytes being "sent" to the device.

        Raises
        ------
        OSError
            If not open, or if a DISCONNECT fault fires.
        """
        if not self._is_open:
            raise OSError("Mock: not open")

        # Parse outgoing frame(s)
        frames = self._parser.feed(data)

        for frame in frames:
            fault = self._faults.get(self._request_count)

            # DISCONNECT: close transport immediately
            if fault == FaultKind.DISCONNECT:
                self._is_open = False
                self._request_count += 1
                raise OSError("Mock: disconnected")

            response = self._generate_response(frame)
            if not response:
                self._request_count += 1
                continue

            # Apply fault to response bytes
            response = self._apply_fault(response, fault)
            if response is not None:
                self._rx_buffer.extend(response)

            self._request_count += 1

        # If no frames parsed (empty/unparseable data), still count as a request
        if not frames:
            fault = self._faults.get(self._request_count)
            if fault == FaultKind.DISCONNECT:
                self._is_open = False
                self._request_count += 1
                raise OSError("Mock: disconnected")
            self._request_count += 1

    def read(self, size: int) -> bytes:
        """Read up to *size* bytes from the mock receive buffer.

        Parameters
        ----------
        size : int
            Maximum number of bytes to return.

        Returns
        -------
        bytes
            Buffered response data; may be empty.

        Raises
        ------
        OSError
            If the transport is not open.
        """
        if not self._is_open:
            raise OSError("Mock: not open")
        chunk = bytes(self._rx_buffer[:size])
        del self._rx_buffer[:size]
        return chunk

    # -- Buffer management --

    @property
    def in_waiting(self) -> int:
        """Number of bytes available in the mock receive buffer."""
        return len(self._rx_buffer)

    def reset_input_buffer(self) -> None:
        """Discard all data in the receive buffer."""
        self._rx_buffer.clear()

    def reset_output_buffer(self) -> None:
        """No-op for mock (writes are processed immediately)."""
        pass

    # -- Status --

    @property
    def is_open(self) -> bool:
        """Whether the mock transport is currently open."""
        return self._is_open

    # -- Response generation (private) --

    def _generate_response(self, frame: ProtocolFrame) -> bytes:
        """Dispatch to the appropriate response generator by command.

        Parameters
        ----------
        frame : ProtocolFrame
            Parsed outgoing frame.

        Returns
        -------
        bytes
            Raw response frame, or empty bytes if unrecognized.
        """
        cmd = frame.cmd

        if cmd == SnetCommand.IO_REQUEST:
            return self._generate_io_response(frame)
        elif cmd == SnetCommand.WRITE_VAR:
            return self._generate_write_var_response(frame)
        elif cmd == SnetCommand.READ_VAR:
            return self._generate_read_var_response(frame)
        elif self._is_brooks_get_kp(cmd):
            return self._generate_kp_response(frame)
        else:
            # Unknown command: echo frame as-is
            return frame.raw

    def _generate_io_response(self, frame: ProtocolFrame) -> bytes:
        """Build an IO_RESPONSE from an IO_REQUEST frame.

        Parameters
        ----------
        frame : ProtocolFrame
            Parsed IO_REQUEST frame.

        Returns
        -------
        bytes
            IO_RESPONSE frame with synthetic monitor data.
        """
        io_payload = frame.io_payload
        if io_payload is None:
            io_payload = decode_io_payload(frame.view.data)
        if io_payload is None:
            return b''
        resp_payload = build_mock_snet_monitor_payload(io_payload)
        return build_frame(
            frame.seq,
            SnetCommand.IO_RESPONSE,
            resp_payload,
            frame_id=frame.view.frame_id,
            ch=frame.view.ch,
        )

    def _generate_write_var_response(self, frame: ProtocolFrame) -> bytes:
        """Echo a WRITE_VAR request and store the variable value.

        Parameters
        ----------
        frame : ProtocolFrame
            Parsed WRITE_VAR frame.

        Returns
        -------
        bytes
            The original frame echoed back (matching v1 behavior).
        """
        decoded = decode_var_value_payload(frame.view.data)
        if decoded is not None:
            var_index, value = decoded
            self._var_values[var_index] = value
        # Echo same frame as response
        return frame.raw

    def _generate_read_var_response(self, frame: ProtocolFrame) -> bytes:
        """Respond to a READ_VAR with a WRITE_VAR containing the stored value.

        Parameters
        ----------
        frame : ProtocolFrame
            Parsed READ_VAR frame. Payload is 2 bytes (var_index only).

        Returns
        -------
        bytes
            WRITE_VAR frame with the stored value (or 0 if never written).
        """
        data = frame.view.data
        if len(data) >= 2:
            var_index = int.from_bytes(data[:2], byteorder='big', signed=False)
            value = self._var_values.get(var_index, 0)
            return build_write_var_frame(
                frame.seq, var_index, value, ch=frame.view.ch,
            )
        # Fallback: echo original frame
        return frame.raw

    def _generate_kp_response(self, frame: ProtocolFrame) -> bytes:
        """Build a BROOKS_GET_KP response.

        Parameters
        ----------
        frame : ProtocolFrame
            Parsed Brooks GET_KP request frame.

        Returns
        -------
        bytes
            KP response frame with the configured kp_values.
        """
        return build_brooks_get_kp_response_frame(
            frame.seq, self._kp_values, ch=frame.view.ch,
        )

    # -- Fault application (private) --

    def _apply_fault(
        self, response: bytes, fault: Optional[FaultKind],
    ) -> Optional[bytes]:
        """Apply a fault to a response, or return it unchanged.

        Parameters
        ----------
        response : bytes
            The clean response frame.
        fault : FaultKind | None
            Fault to apply, or None for clean pass-through.

        Returns
        -------
        bytes | None
            Modified response, or None if the response should be
            suppressed entirely (e.g. TIMEOUT).
        """
        if fault is None:
            return response
        if not response:
            return response

        if fault == FaultKind.TIMEOUT:
            # Suppress the response entirely
            return None

        if fault == FaultKind.CORRUPT:
            return self._corrupt_response(response)

        if fault == FaultKind.PARTIAL:
            # Buffer only the first half
            half = max(1, len(response) // 2)
            return response[:half]

        if fault == FaultKind.WRONG_SEQ:
            return self._modify_byte(response, FRAME_IDX_SEQ)

        if fault == FaultKind.WRONG_CMD:
            # Modify both cmd bytes
            modified = self._modify_byte(response, FRAME_IDX_CMD_H)
            return self._modify_byte(modified, FRAME_IDX_CMD_L)

        if fault == FaultKind.WRONG_CH:
            return self._modify_byte(response, FRAME_IDX_CH)

        if fault == FaultKind.INVALID_KP:
            # Build a valid frame but with truncated KP payload (3 bytes instead of 60)
            # so parser completes the frame but decode_brooks_kp_payload returns None
            from ..protocol.constants import FRAME_HEADER_LEN
            if len(response) > FRAME_HEADER_LEN + 3:
                header = bytearray(response[:FRAME_HEADER_LEN])
                short_payload = response[FRAME_HEADER_LEN:FRAME_HEADER_LEN + 3]
                header[7] = len(short_payload)  # fix LEN field
                return bytes(header) + short_payload
            return response

        # DISCONNECT and OPEN_FAIL are handled before response generation,
        # so they should never reach here. Return unchanged as fallback.
        return response

    @staticmethod
    def _corrupt_response(response: bytes) -> bytes:
        """XOR payload bytes to simulate data corruption.

        Parameters
        ----------
        response : bytes
            Clean response frame.

        Returns
        -------
        bytes
            Frame with some payload bytes XOR'd with 0xFF.
        """
        buf = bytearray(response)
        # XOR bytes in the payload area (after the 8-byte header)
        for i in range(8, len(buf)):
            buf[i] ^= 0xFF
        return bytes(buf)

    @staticmethod
    def _modify_byte(response: bytes, index: int) -> bytes:
        """XOR a single byte in the response to create a mismatch.

        Parameters
        ----------
        response : bytes
            Clean response frame.
        index : int
            Byte offset to modify.

        Returns
        -------
        bytes
            Frame with the specified byte XOR'd with 0xFF.
        """
        if index >= len(response):
            return response
        buf = bytearray(response)
        buf[index] ^= 0xFF
        return bytes(buf)

    @staticmethod
    def _is_brooks_get_kp(cmd: int) -> bool:
        """Check whether a command code is a Brooks GET_KP request.

        Parameters
        ----------
        cmd : int
            16-bit command code from the parsed frame.

        Returns
        -------
        bool
            True if this is a Brooks GET_KP request command.
        """
        return cmd == (BROOKS_REQUEST_CMD_BASE | BROOKS_GET_KP_CMD_L)
