"""Tests for the v2 stream protocol parser.

Mirrors tests/test_parser.py but imports from snet_tester2.
Key changes vs v1:
  - SnetCommand enum replaces REQUEST_CMD / RESPONSE_CMD constants
"""

from snet_tester2.protocol.codec import build_frame
from snet_tester2.protocol.enums import SnetCommand
from snet_tester2.protocol.parser import ProtocolParser


def test_parse_single_frame():
    parser = ProtocolParser()
    frame = build_frame(0xC0, SnetCommand.IO_REQUEST, b'\x00\x01\x02')
    results = parser.feed(frame)
    assert len(results) == 1
    assert results[0].seq == 0xC0
    assert results[0].cmd == SnetCommand.IO_REQUEST


def test_parse_multiple_frames():
    parser = ProtocolParser()
    f1 = build_frame(0x01, SnetCommand.IO_REQUEST, b'\x00')
    f2 = build_frame(0x02, SnetCommand.IO_RESPONSE, b'\xFF')
    results = parser.feed(f1 + f2)
    assert len(results) == 2
    assert results[0].seq == 0x01
    assert results[1].seq == 0x02


def test_parse_with_garbage():
    parser = ProtocolParser()
    garbage = b'\xFF\xFE\xFD'
    frame = build_frame(0xAA, SnetCommand.IO_REQUEST, b'\x00')
    results = parser.feed(garbage + frame)
    assert len(results) == 1
    assert results[0].seq == 0xAA


def test_parse_incremental():
    parser = ProtocolParser()
    frame = build_frame(0xBB, SnetCommand.IO_REQUEST, b'\x00\x01\x02\x03')
    # Feed one byte at a time
    results = []
    for byte in frame:
        results.extend(parser.feed(bytes([byte])))
    assert len(results) == 1
    assert results[0].seq == 0xBB


def test_parse_rejects_oversized_payload():
    parser = ProtocolParser()
    # Build a frame header with payload_len > MAX_PAYLOAD_LEN (64)
    bad_frame = b'\xA5\x5A\x00\x00\x00\x80\x00\xFF'  # len=255
    results = parser.feed(bad_frame)
    assert len(results) == 0


def test_reset_clears_buffer():
    parser = ProtocolParser()
    parser.feed(b'\xA5\x5A\x00')  # partial frame
    parser.reset()
    frame = build_frame(0xCC, SnetCommand.IO_REQUEST, b'\x00')
    results = parser.feed(frame)
    assert len(results) == 1
    assert results[0].seq == 0xCC
