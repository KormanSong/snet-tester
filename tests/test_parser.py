"""Tests for the stream protocol parser."""

from snet_tester.protocol.codec import build_frame
from snet_tester.protocol.constants import REQUEST_CMD, RESPONSE_CMD
from snet_tester.protocol.parser import ProtocolParser


def test_parse_single_frame():
    parser = ProtocolParser()
    frame = build_frame(0xC0, REQUEST_CMD, b'\x00\x01\x02')
    results = parser.feed(frame)
    assert len(results) == 1
    assert results[0].seq == 0xC0
    assert results[0].cmd == REQUEST_CMD


def test_parse_multiple_frames():
    parser = ProtocolParser()
    f1 = build_frame(0x01, REQUEST_CMD, b'\x00')
    f2 = build_frame(0x02, RESPONSE_CMD, b'\xFF')
    results = parser.feed(f1 + f2)
    assert len(results) == 2
    assert results[0].seq == 0x01
    assert results[1].seq == 0x02


def test_parse_with_garbage():
    parser = ProtocolParser()
    garbage = b'\xFF\xFE\xFD'
    frame = build_frame(0xAA, REQUEST_CMD, b'\x00')
    results = parser.feed(garbage + frame)
    assert len(results) == 1
    assert results[0].seq == 0xAA


def test_parse_incremental():
    parser = ProtocolParser()
    frame = build_frame(0xBB, REQUEST_CMD, b'\x00\x01\x02\x03')
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
    frame = build_frame(0xCC, REQUEST_CMD, b'\x00')
    results = parser.feed(frame)
    assert len(results) == 1
    assert results[0].seq == 0xCC
