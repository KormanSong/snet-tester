"""Tests for frame encoding/decoding and payload serialization."""

from snet_tester.protocol.codec import (
    build_frame,
    build_io_payload_bytes,
    build_io_payload_model,
    build_write_var_frame,
    clamp_channel_count,
    decode_frame_view,
    decode_io_payload,
    decode_snet_monitor_payload,
    default_io_payload,
)
from snet_tester.protocol.constants import HEADER, REQUEST_CMD, WRITE_VAR_CMD


def test_clamp_channel_count():
    assert clamp_channel_count(0) == 1
    assert clamp_channel_count(3) == 3
    assert clamp_channel_count(99) == 6


def test_build_frame_basic():
    frame = build_frame(0xC0, REQUEST_CMD, b'\x00')
    assert frame[:2] == HEADER
    assert frame[2] == 0xC0
    assert frame[7] == 1  # payload length
    assert frame[8] == 0x00


def test_decode_frame_view_roundtrip():
    payload = b'\x01\x02\x03'
    frame = build_frame(0xAA, 0x1234, payload)
    view = decode_frame_view(frame)
    assert view.seq == 0xAA
    assert view.cmd == 0x1234
    assert view.length == 3
    assert view.data == payload
    assert view.raw == frame


def test_io_payload_roundtrip():
    model = build_io_payload_model(channel_count=2, ratio_percents=[50.0, 75.0])
    assert model.channel_count == 2
    assert len(model.channels) == 2

    encoded = build_io_payload_bytes(model)
    decoded = decode_io_payload(encoded)
    assert decoded is not None
    assert decoded.channel_count == 2
    assert decoded.channels[0].ratio_raw == model.channels[0].ratio_raw
    assert decoded.channels[1].ratio_raw == model.channels[1].ratio_raw


def test_default_io_payload():
    p = default_io_payload(3)
    assert p.channel_count == 3
    assert all(ch.ratio_raw == 0 for ch in p.channels)


def test_decode_io_payload_invalid():
    assert decode_io_payload(b'') is None
    assert decode_io_payload(b'\x00\x01') is None  # body_len=1, not divisible by 3


def test_decode_snet_monitor_payload():
    # 6 header bytes + 8 bytes per channel (1 channel)
    payload = bytes([
        0x00,  # status
        0x01,  # mode
        0x20, 0x7A,  # pressure_raw
        0x19, 0x74,  # temperature_raw
        0x10, 0x00,  # ad_raw
        0x00, 0x40,  # flow_raw
        0x40, 0x00,  # ratio_raw
        0x40, 0x00,  # valve_raw
    ])
    snap = decode_snet_monitor_payload(payload)
    assert snap is not None
    assert snap.status == 0x00
    assert snap.mode == 0x01
    assert snap.channel_count == 1
    assert snap.channels[0].ad_raw == 0x1000
    assert snap.channels[0].ratio_raw == 0x4000


def test_decode_snet_monitor_invalid():
    assert decode_snet_monitor_payload(b'\x00\x01\x02') is None  # too short
    assert decode_snet_monitor_payload(b'\x00' * 7) is None  # body_len=1, not divisible by 8


def test_build_write_var_frame():
    frame = build_write_var_frame(0x10, 0x0001, 42)
    view = decode_frame_view(frame)
    assert view.cmd == WRITE_VAR_CMD
    assert view.seq == 0x10
    assert view.length == 10  # 2 (var_index) + 8 (value)
