"""Tests for frame encoding/decoding and payload serialization."""

from snet_tester.protocol.codec import (
    build_brooks_get_kp_frame,
    build_brooks_get_kp_response_frame,
    build_frame,
    build_io_payload_bytes,
    build_io_payload_model,
    build_read_var_frame,
    build_write_var_frame,
    clamp_channel_count,
    decode_brooks_kp_payload,
    decode_var_value_payload,
    decode_frame_view,
    decode_io_payload,
    decode_snet_monitor_payload,
    default_io_payload,
)
from snet_tester.protocol.constants import (
    BROOKS_GET_KP_DUMMY_LEN,
    BROOKS_GET_KP_CMD_L,
    BROOKS_KP_DOUBLE_LEN,
    BROOKS_KP_STATUS_LEN,
    BROOKS_KP_VALUE_COUNT,
    HEADER,
    READ_VAR_CMD,
    REQUEST_CMD,
    WRITE_VAR_CMD,
)


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


def test_build_read_var_frame():
    frame = build_read_var_frame(0x11, 0x1000)
    view = decode_frame_view(frame)
    assert view.cmd == READ_VAR_CMD
    assert view.seq == 0x11
    assert view.length == 2
    assert view.data == b'\x10\x00'


def test_decode_var_value_payload():
    decoded = decode_var_value_payload(b'\x10\x00' + (500).to_bytes(8, byteorder='big'))
    assert decoded == (0x1000, 500)


def test_build_brooks_get_kp_frame():
    frame = build_brooks_get_kp_frame(0x22, ch=0x03)
    view = decode_frame_view(frame)
    assert view.seq == 0x22
    assert view.ch == 0x03
    assert view.cmd == 0x1000 | BROOKS_GET_KP_CMD_L
    assert view.length == 1 + BROOKS_GET_KP_DUMMY_LEN
    assert view.data == (bytes((BROOKS_KP_VALUE_COUNT,)) + (b'\x00' * BROOKS_GET_KP_DUMMY_LEN))


def test_decode_brooks_kp_payload():
    values = (0.0, 0.7, 0.5, 0.3, 0.0, 0.0)
    response = build_brooks_get_kp_response_frame(0x22, values, ch=0x01)
    decoded = decode_brooks_kp_payload(response[8:])
    assert decoded is not None
    assert len(response[8:]) == BROOKS_KP_VALUE_COUNT * (BROOKS_KP_STATUS_LEN + BROOKS_KP_DOUBLE_LEN)
    assert len(decoded) == BROOKS_KP_VALUE_COUNT
    for actual, expected in zip(decoded, values):
        assert abs(actual - expected) < 1e-9


def test_decode_brooks_kp_payload_rejects_bad_length():
    assert decode_brooks_kp_payload(b'\x01\x00') is None
