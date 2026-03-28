"""SNET stream protocol parser."""

from .constants import (
    FRAME_HEADER_LEN,
    FRAME_IDX_CMD_H,
    FRAME_IDX_CMD_L,
    FRAME_IDX_LEN,
    HEADER,
    MAX_PAYLOAD_LEN,
)
from .codec import decode_frame_view, decode_io_payload, decode_snet_monitor_payload
from .types import ProtocolFrame


class ProtocolParser:
    def __init__(self):
        self._buf = bytearray()

    def reset(self):
        self._buf.clear()

    def feed(self, data: bytes) -> list[ProtocolFrame]:
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
                    cmd=cmd,
                    raw=frame_view.raw,
                    view=frame_view,
                    io_payload=io_payload,
                    snet_monitor=snet_monitor,
                )
            )
            del self._buf[:frame_len]

        return frames
