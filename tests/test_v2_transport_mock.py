"""Tests for MockTransport response generation and fault injection.

Validates that the in-memory MockTransport correctly:
  - Handles lifecycle (open/close/is_open)
  - Generates IO_RESPONSE from IO_REQUEST with valid monitor data
  - Echoes WRITE_VAR and stores variable values
  - Returns stored values for READ_VAR
  - Generates BROOKS_GET_KP responses
  - Runs multiple consecutive IO cycles
  - Injects faults at specific request indices (TIMEOUT, CORRUPT, PARTIAL,
    WRONG_SEQ, WRONG_CMD, WRONG_CH, DISCONNECT, OPEN_FAIL, INVALID_KP)
  - Recovers to normal operation after transient faults
"""

import pytest

from snet_tester2.transport.mock import MockTransport, FaultKind, FaultRule
from snet_tester2.protocol.codec import (
    build_frame,
    build_io_payload_bytes,
    decode_frame_view,
    decode_snet_monitor_payload,
    decode_io_payload,
    decode_var_value_payload,
    decode_brooks_kp_payload,
    default_io_payload,
    build_write_var_frame,
    build_read_var_frame,
    build_brooks_get_kp_frame,
)
from snet_tester2.protocol.enums import SnetCommand, VarIndex
from snet_tester2.protocol.parser import ProtocolParser
from snet_tester2.protocol.constants import SEQ_START


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def send_io_request(transport, seq, payload):
    """Send an IO_REQUEST frame and return parsed response frames.

    Parameters
    ----------
    transport : MockTransport
        An open MockTransport instance.
    seq : int
        Sequence number for the request frame.
    payload : IoPayload
        I/O payload to encode in the request.

    Returns
    -------
    list[ProtocolFrame]
        Parsed response frames from the mock transport's RX buffer.
    """
    request_bytes = build_io_payload_bytes(payload)
    request = build_frame(seq, SnetCommand.IO_REQUEST, request_bytes)
    transport.write(request)
    response_data = transport.read(transport.in_waiting)
    parser = ProtocolParser()
    return parser.feed(response_data)


# ---------------------------------------------------------------------------
# Basic functionality
# ---------------------------------------------------------------------------

class TestMockTransportBasic:
    """Tests for MockTransport lifecycle and normal response generation."""

    def test_open_close(self):
        """open() sets is_open=True, close() sets is_open=False."""
        t = MockTransport()
        assert not t.is_open
        t.open()
        assert t.is_open
        t.close()
        assert not t.is_open

    def test_write_before_open_raises(self):
        """write() on a closed transport must raise OSError."""
        t = MockTransport()
        payload = default_io_payload(1)
        request = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        with pytest.raises(OSError):
            t.write(request)

    def test_read_before_open_raises(self):
        """read() on a closed transport must raise OSError."""
        t = MockTransport()
        with pytest.raises(OSError):
            t.read(100)

    def test_io_request_response(self):
        """Write IO_REQUEST, read IO_RESPONSE with valid monitor data."""
        t = MockTransport()
        t.open()
        payload = default_io_payload(1)
        frames = send_io_request(t, SEQ_START, payload)
        assert len(frames) == 1
        assert frames[0].cmd == SnetCommand.IO_RESPONSE
        assert frames[0].snet_monitor is not None
        assert frames[0].snet_monitor.channel_count == 1

    def test_io_response_seq_matches_request(self):
        """IO_RESPONSE must echo the same SEQ as the request."""
        t = MockTransport()
        t.open()
        payload = default_io_payload(1)
        frames = send_io_request(t, SEQ_START, payload)
        assert len(frames) == 1
        assert frames[0].seq == SEQ_START

    def test_io_response_multichannel(self):
        """IO_REQUEST with 3 channels returns monitor with 3 channels."""
        from snet_tester2.protocol.codec import build_io_payload_model
        t = MockTransport()
        t.open()
        payload = build_io_payload_model(3, [50.0, 30.0, 20.0])
        frames = send_io_request(t, SEQ_START, payload)
        assert len(frames) == 1
        assert frames[0].snet_monitor is not None
        assert frames[0].snet_monitor.channel_count == 3

    def test_write_var_echo(self):
        """Write WRITE_VAR, verify echo response parses correctly."""
        t = MockTransport()
        t.open()
        request = build_write_var_frame(SEQ_START, VarIndex.FULL_OPEN_VALUE, 42000)
        t.write(request)
        data = t.read(t.in_waiting)
        # Response should be parseable
        parser = ProtocolParser()
        frames = parser.feed(data)
        assert len(frames) >= 1
        assert frames[0].seq == SEQ_START

    def test_read_var_returns_stored(self):
        """Write a var, then read it back -- value should match."""
        t = MockTransport()
        t.open()
        # Write value 12345
        write_req = build_write_var_frame(SEQ_START, VarIndex.FULL_OPEN_VALUE, 12345)
        t.write(write_req)
        t.read(t.in_waiting)  # drain write response
        # Read it back
        read_req = build_read_var_frame(SEQ_START + 1, VarIndex.FULL_OPEN_VALUE)
        t.write(read_req)
        data = t.read(t.in_waiting)
        parser = ProtocolParser()
        frames = parser.feed(data)
        assert len(frames) >= 1
        decoded = decode_var_value_payload(frames[0].view.data)
        assert decoded is not None
        assert decoded[0] == VarIndex.FULL_OPEN_VALUE
        assert decoded[1] == 12345

    def test_read_var_returns_zero_if_never_written(self):
        """READ_VAR for a key that was never written should return 0."""
        t = MockTransport()
        t.open()
        read_req = build_read_var_frame(SEQ_START, VarIndex.FULL_OPEN_VALUE)
        t.write(read_req)
        data = t.read(t.in_waiting)
        parser = ProtocolParser()
        frames = parser.feed(data)
        assert len(frames) >= 1
        decoded = decode_var_value_payload(frames[0].view.data)
        assert decoded is not None
        assert decoded[1] == 0

    def test_brooks_get_kp(self):
        """GET_KP returns valid KP values matching the configured defaults."""
        t = MockTransport()
        t.open()
        request = build_brooks_get_kp_frame(SEQ_START, ch=1)
        t.write(request)
        data = t.read(t.in_waiting)
        parser = ProtocolParser()
        frames = parser.feed(data)
        assert len(frames) >= 1
        kp = decode_brooks_kp_payload(frames[0].view.data)
        assert kp is not None
        assert len(kp) == 6

    def test_brooks_get_kp_custom_values(self):
        """GET_KP returns custom KP values when provided at construction."""
        custom_kp = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
        t = MockTransport(kp_values=custom_kp)
        t.open()
        request = build_brooks_get_kp_frame(SEQ_START, ch=1)
        t.write(request)
        data = t.read(t.in_waiting)
        parser = ProtocolParser()
        frames = parser.feed(data)
        assert len(frames) >= 1
        kp = decode_brooks_kp_payload(frames[0].view.data)
        assert kp is not None
        for actual, expected in zip(kp, custom_kp):
            assert abs(actual - expected) < 1e-9

    def test_multiple_cycles(self):
        """10 consecutive IO cycles all produce valid responses."""
        t = MockTransport()
        t.open()
        payload = default_io_payload(1)
        for i in range(10):
            seq = (SEQ_START + i) & 0xFF
            frames = send_io_request(t, seq, payload)
            assert len(frames) == 1, f"cycle {i}: expected 1 frame, got {len(frames)}"
            assert frames[0].cmd == SnetCommand.IO_RESPONSE
            assert frames[0].seq == seq

    def test_in_waiting_zero_before_write(self):
        """in_waiting should be 0 before any write."""
        t = MockTransport()
        t.open()
        assert t.in_waiting == 0

    def test_reset_input_buffer(self):
        """reset_input_buffer() clears any pending RX data."""
        t = MockTransport()
        t.open()
        payload = default_io_payload(1)
        request = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        t.write(request)
        assert t.in_waiting > 0
        t.reset_input_buffer()
        assert t.in_waiting == 0

    def test_close_then_reopen(self):
        """Transport can be closed and reopened with session state reset."""
        t = MockTransport(faults=[FaultRule(at_request=0, kind=FaultKind.TIMEOUT)])
        t.open()
        payload = default_io_payload(1)
        # Request 0 should timeout due to fault
        req = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        t.write(req)
        assert t.in_waiting == 0  # timeout: no response
        # Write a var to test var_values persistence
        from snet_tester2.protocol.codec import build_write_var_frame
        t.write(build_write_var_frame(SEQ_START, 0x1000, 99999))
        t.read(t.in_waiting)  # drain
        t.close()
        assert not t.is_open
        # Reopen — session state should be reset
        t.open()
        assert t.is_open
        # Request 0 after reopen: fault at_request=0 should fire again (request_count reset)
        t.write(req)
        assert t.in_waiting == 0, "Fault should re-fire after reopen (request_count reset)"
        # Var values should be cleared
        from snet_tester2.protocol.codec import build_read_var_frame, decode_var_value_payload
        t.write(build_read_var_frame(SEQ_START + 1, 0x1000))
        data = t.read(t.in_waiting)
        from snet_tester2.protocol.parser import ProtocolParser
        frames = ProtocolParser().feed(data)
        if frames:
            decoded = decode_var_value_payload(frames[0].view.data)
            if decoded:
                assert decoded[1] == 0, "var_values should be cleared after close/reopen"


# ---------------------------------------------------------------------------
# Fault injection
# ---------------------------------------------------------------------------

class TestMockTransportFaults:
    """Tests for MockTransport fault injection at specific request indices."""

    def test_s02_timeout(self):
        """TIMEOUT at request 2 -> no response bytes for that request only."""
        t = MockTransport(faults=[FaultRule(at_request=2, kind=FaultKind.TIMEOUT)])
        t.open()
        payload = default_io_payload(1)
        for i in range(5):
            seq = (SEQ_START + i) & 0xFF
            request = build_frame(seq, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
            t.write(request)
            available = t.in_waiting
            if i == 2:
                assert available == 0, f"Expected timeout at request 2, got {available} bytes"
            else:
                assert available > 0, f"Expected response at request {i}, got 0 bytes"
            t.read(available)

    def test_s04_open_fail(self):
        """OPEN_FAIL -> open() raises OSError."""
        t = MockTransport(faults=[FaultRule(at_request=-1, kind=FaultKind.OPEN_FAIL)])
        with pytest.raises(OSError):
            t.open()
        assert not t.is_open

    def test_s05_disconnect(self):
        """DISCONNECT at request 4 -> write() raises OSError."""
        t = MockTransport(faults=[FaultRule(at_request=4, kind=FaultKind.DISCONNECT)])
        t.open()
        payload = default_io_payload(1)
        # Requests 0-3 should succeed
        for i in range(4):
            seq = (SEQ_START + i) & 0xFF
            request = build_frame(seq, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
            t.write(request)
            t.read(t.in_waiting)
        # Request 4 should raise OSError
        with pytest.raises(OSError):
            request = build_frame(
                (SEQ_START + 4) & 0xFF,
                SnetCommand.IO_REQUEST,
                build_io_payload_bytes(payload),
            )
            t.write(request)

    def test_s06_corrupt(self):
        """CORRUPT at request 1 -> response bytes differ from clean response."""
        t_normal = MockTransport()
        t_normal.open()
        t_corrupt = MockTransport(faults=[FaultRule(at_request=1, kind=FaultKind.CORRUPT)])
        t_corrupt.open()
        payload = default_io_payload(1)

        # Request 0: both should produce identical responses
        req0 = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        t_normal.write(req0)
        t_corrupt.write(req0)
        normal0 = t_normal.read(t_normal.in_waiting)
        corrupt0 = t_corrupt.read(t_corrupt.in_waiting)
        assert normal0 == corrupt0, "Request 0 should not be affected by fault at request 1"

        # Request 1: corrupt should differ
        req1 = build_frame(SEQ_START + 1, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        t_normal.write(req1)
        t_corrupt.write(req1)
        normal1 = t_normal.read(t_normal.in_waiting)
        corrupt1 = t_corrupt.read(t_corrupt.in_waiting)
        assert normal1 != corrupt1, "Corrupted response should differ from clean response"

    def test_s06_corrupt_same_length(self):
        """CORRUPT should produce same-length response (only content differs)."""
        t_normal = MockTransport()
        t_normal.open()
        t_corrupt = MockTransport(faults=[FaultRule(at_request=0, kind=FaultKind.CORRUPT)])
        t_corrupt.open()
        payload = default_io_payload(1)
        req = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        t_normal.write(req)
        t_corrupt.write(req)
        normal = t_normal.read(t_normal.in_waiting)
        corrupt = t_corrupt.read(t_corrupt.in_waiting)
        assert len(normal) == len(corrupt), "Corrupt response should have same length"
        assert normal != corrupt

    def test_s07_partial(self):
        """PARTIAL at request 0 -> response is truncated to less than full size."""
        t = MockTransport(faults=[FaultRule(at_request=0, kind=FaultKind.PARTIAL)])
        t.open()
        payload = default_io_payload(1)
        request = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        t.write(request)
        available = t.in_waiting
        # Should have some bytes, but fewer than a full response
        assert available > 0, "Partial response should have some bytes"

        # Get full response length from normal transport for comparison
        t_normal = MockTransport()
        t_normal.open()
        t_normal.write(request)
        normal_len = t_normal.in_waiting
        assert available < normal_len, (
            f"Partial response ({available} bytes) should be shorter than full ({normal_len} bytes)"
        )

    def test_s08_wrong_seq(self):
        """WRONG_SEQ -> response has different seq than request."""
        t = MockTransport(faults=[FaultRule(at_request=0, kind=FaultKind.WRONG_SEQ)])
        t.open()
        payload = default_io_payload(1)
        request = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        t.write(request)
        data = t.read(t.in_waiting)
        assert len(data) > 0, "WRONG_SEQ should still produce response bytes"
        resp = decode_frame_view(data)
        assert resp.seq != SEQ_START, (
            f"Response seq 0x{resp.seq:02X} should differ from request seq 0x{SEQ_START:02X}"
        )

    def test_s09_wrong_cmd(self):
        """WRONG_CMD -> response has different cmd than expected IO_RESPONSE."""
        t = MockTransport(faults=[FaultRule(at_request=0, kind=FaultKind.WRONG_CMD)])
        t.open()
        payload = default_io_payload(1)
        request = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        t.write(request)
        data = t.read(t.in_waiting)
        assert len(data) > 0, "WRONG_CMD should still produce response bytes"
        resp = decode_frame_view(data)
        assert resp.cmd != SnetCommand.IO_RESPONSE, (
            f"Response cmd 0x{resp.cmd:04X} should differ from IO_RESPONSE"
        )

    def test_s10_wrong_ch(self):
        """WRONG_CH -> response has different ch than request."""
        t = MockTransport(faults=[FaultRule(at_request=0, kind=FaultKind.WRONG_CH)])
        t.open()
        payload = default_io_payload(1)
        request = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        t.write(request)
        data = t.read(t.in_waiting)
        assert len(data) > 0, "WRONG_CH should still produce response bytes"
        resp = decode_frame_view(data)
        assert resp.ch != 0, (
            f"Response ch 0x{resp.ch:02X} should differ from default ch 0x00"
        )

    def test_s13_kp_timeout(self):
        """KP request with TIMEOUT -> no response bytes."""
        t = MockTransport(faults=[FaultRule(at_request=0, kind=FaultKind.TIMEOUT)])
        t.open()
        request = build_brooks_get_kp_frame(SEQ_START, ch=1)
        t.write(request)
        assert t.in_waiting == 0, "TIMEOUT should suppress all response bytes"

    def test_s14_invalid_kp(self):
        """INVALID_KP -> frame parses but KP payload decode returns None."""
        t = MockTransport(faults=[FaultRule(at_request=0, kind=FaultKind.INVALID_KP)])
        t.open()
        request = build_brooks_get_kp_frame(SEQ_START, ch=1)
        t.write(request)
        data = t.read(t.in_waiting)
        assert len(data) > 0, "INVALID_KP should produce a frame (not timeout)"
        parser = ProtocolParser()
        frames = parser.feed(data)
        assert len(frames) >= 1, "INVALID_KP frame should parse successfully"
        kp = decode_brooks_kp_payload(frames[0].view.data)
        assert kp is None, "Truncated KP payload must fail decode"

    def test_s16_recovery_after_timeout(self):
        """TIMEOUT at request 3, then normal recovery for remaining requests."""
        t = MockTransport(faults=[FaultRule(at_request=3, kind=FaultKind.TIMEOUT)])
        t.open()
        payload = default_io_payload(1)
        results = []
        for i in range(7):
            seq = (SEQ_START + i) & 0xFF
            request = build_frame(seq, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
            t.write(request)
            available = t.in_waiting
            results.append(available > 0)
            t.read(available)
        # All should succeed except index 3
        assert results == [True, True, True, False, True, True, True], (
            f"Expected [T,T,T,F,T,T,T] got {results}"
        )

    def test_timeout_does_not_affect_subsequent_requests(self):
        """After a TIMEOUT, the next request should work normally."""
        t = MockTransport(faults=[FaultRule(at_request=0, kind=FaultKind.TIMEOUT)])
        t.open()
        payload = default_io_payload(1)
        # Request 0: timeout
        req0 = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        t.write(req0)
        assert t.in_waiting == 0
        # Request 1: should work
        req1 = build_frame(SEQ_START + 1, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
        t.write(req1)
        assert t.in_waiting > 0
        data = t.read(t.in_waiting)
        parser = ProtocolParser()
        frames = parser.feed(data)
        assert len(frames) == 1
        assert frames[0].seq == SEQ_START + 1

    def test_multiple_faults_at_different_indices(self):
        """Multiple fault rules targeting different request indices."""
        t = MockTransport(faults=[
            FaultRule(at_request=1, kind=FaultKind.TIMEOUT),
            FaultRule(at_request=3, kind=FaultKind.TIMEOUT),
        ])
        t.open()
        payload = default_io_payload(1)
        results = []
        for i in range(5):
            seq = (SEQ_START + i) & 0xFF
            request = build_frame(seq, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload))
            t.write(request)
            results.append(t.in_waiting > 0)
            t.read(t.in_waiting)
        assert results == [True, False, True, False, True], (
            f"Expected [T,F,T,F,T] got {results}"
        )

    def test_write_var_with_timeout(self):
        """TIMEOUT applies to WRITE_VAR commands as well."""
        t = MockTransport(faults=[FaultRule(at_request=0, kind=FaultKind.TIMEOUT)])
        t.open()
        request = build_write_var_frame(SEQ_START, VarIndex.FULL_OPEN_VALUE, 42000)
        t.write(request)
        assert t.in_waiting == 0, "TIMEOUT should suppress WRITE_VAR response too"
