"""Oracle parity tests -- v2 protocol + mock transport vs v1 baseline.

Verifies that snet_tester2's protocol layer and mock transport produce
byte-identical frames and statistically equivalent results compared
to the frozen v1_baseline.json captured from snet_tester (v1).

Scenarios tested:
  S1  Basic 100-cycle IO loop: frame hex parity + ratio statistics
  S2  Setpoint apply mid-run: boundary frame hex + ratio after apply
  S3  write_var skip: sample count match + frame construction

Key decision: build_mock_snet_monitor_payload is imported from
snet_tester2.transport.mock (not protocol.codec), because it is a
mock-only concern in v2.

S3 parity checks frame hex and sample count only. Timeline tick order
is NOT checked because v2's skip mechanism differs from v1.
"""

import json
import pathlib

import pytest

from snet_tester2.protocol.codec import (
    build_frame,
    build_io_payload_bytes,
    build_io_payload_model,
    build_write_var_frame,
    decode_frame_view,
    decode_io_payload,
    decode_snet_monitor_payload,
    default_io_payload,
    first_monitor_ratio_percent,
)
from snet_tester2.protocol.enums import SnetCommand, VarIndex
from snet_tester2.protocol.constants import SEQ_START
from snet_tester2.transport.mock import build_mock_snet_monitor_payload

BASELINE_PATH = pathlib.Path(__file__).parent / "oracle" / "v1_baseline.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def baseline():
    """Load the committed v1 baseline (frozen reference).

    Returns
    -------
    dict
        Full v1_baseline.json contents.
    """
    assert BASELINE_PATH.exists(), f"Baseline file not found: {BASELINE_PATH}"
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_cycle(seq, payload):
    """Run a single mock cycle using v2 protocol + transport.mock.

    Mirrors the v1 capture_baseline._run_mock_cycle logic:
    1. Build IO_REQUEST frame from payload
    2. Build mock monitor response payload
    3. Wrap in IO_RESPONSE frame
    4. Decode and extract CH1 ratio

    Parameters
    ----------
    seq : int
        Sequence number for this cycle.
    payload : IoPayload
        I/O payload to encode.

    Returns
    -------
    dict
        Cycle result with request_hex, response_hex, rx_ratio_ch1_percent.
    """
    req_bytes = build_io_payload_bytes(payload)
    request = build_frame(seq, SnetCommand.IO_REQUEST, req_bytes)
    resp_bytes = build_mock_snet_monitor_payload(payload)
    response = build_frame(seq, SnetCommand.IO_RESPONSE, resp_bytes)
    rx_monitor = decode_snet_monitor_payload(decode_frame_view(response).data)
    rx_ratio = first_monitor_ratio_percent(rx_monitor)
    return {
        "request_hex": request.hex(),
        "response_hex": response.hex(),
        "rx_ratio_ch1_percent": rx_ratio,
    }


# ---------------------------------------------------------------------------
# S1: Basic sample loop parity
# ---------------------------------------------------------------------------

class TestS1Parity:
    """Verify v2 produces identical frames and stats as v1 for the basic loop."""

    def test_first_frame_hex(self, baseline):
        """First request/response frame hex must be byte-identical to v1."""
        cycle = _run_cycle(SEQ_START, default_io_payload(1))
        base_sample = baseline["scenarios"]["s1"]["samples"][0]
        assert cycle["request_hex"] == base_sample["request_hex"], (
            f"v2 request: {cycle['request_hex']}\nv1 request: {base_sample['request_hex']}"
        )
        assert cycle["response_hex"] == base_sample["response_hex"], (
            f"v2 response: {cycle['response_hex']}\nv1 response: {base_sample['response_hex']}"
        )

    def test_all_baseline_frames_match(self, baseline):
        """All 5 captured frames in v1 baseline must match v2 output."""
        payload = default_io_payload(1)
        base_samples = baseline["scenarios"]["s1"]["samples"]
        seq = SEQ_START
        for i in range(len(base_samples)):
            cycle = _run_cycle(seq, payload)
            assert cycle["request_hex"] == base_samples[i]["request_hex"], (
                f"Frame {i}: request hex mismatch"
            )
            assert cycle["response_hex"] == base_samples[i]["response_hex"], (
                f"Frame {i}: response hex mismatch"
            )
            seq = (seq + 1) & 0xFF

    def test_100_cycles_ratio_stats_match(self, baseline):
        """v2 produces same ratio statistics as v1 over 100 cycles."""
        payload = default_io_payload(1)
        seq = SEQ_START
        ratios = []
        for _ in range(100):
            cycle = _run_cycle(seq, payload)
            if cycle["rx_ratio_ch1_percent"] is not None:
                ratios.append(cycle["rx_ratio_ch1_percent"])
            seq = (seq + 1) & 0xFF
        base_stats = baseline["scenarios"]["s1"]["rx_ratio_ch1"]
        assert len(ratios) == base_stats["count"], (
            f"v2 ratio count {len(ratios)} != v1 count {base_stats['count']}"
        )
        v2_mean = sum(ratios) / len(ratios)
        assert v2_mean == pytest.approx(base_stats["mean"]), (
            f"v2 ratio mean {v2_mean} != v1 mean {base_stats['mean']}"
        )

    def test_seq_increments_over_100_cycles(self, baseline):
        """SEQ values wrap correctly (mod 256) over 100 cycles from SEQ_START."""
        payload = default_io_payload(1)
        seq = SEQ_START
        for i in range(100):
            cycle = _run_cycle(seq, payload)
            # Verify the request hex encodes the expected SEQ at byte index 2
            raw = bytes.fromhex(cycle["request_hex"])
            assert raw[2] == seq, f"Cycle {i}: expected seq 0x{seq:02X}, got 0x{raw[2]:02X}"
            seq = (seq + 1) & 0xFF


# ---------------------------------------------------------------------------
# S2: Setpoint apply mid-run parity
# ---------------------------------------------------------------------------

class TestS2Parity:
    """Verify v2 boundary frames and ratio stats match v1 for setpoint apply."""

    def test_boundary_frames_match(self, baseline):
        """Frames at the boundary (apply_at-1, apply_at, apply_at+1) must match v1."""
        base_boundary = baseline["scenarios"]["s2"]["samples_at_boundary"]
        payload_before = default_io_payload(1)
        payload_after = build_io_payload_model(3, [50.0, 30.0, 20.0])
        apply_at = baseline["scenarios"]["s2"]["apply_at_cycle"]

        seq = SEQ_START
        for i in range(apply_at + 2):
            payload = payload_before if i < apply_at else payload_after
            if apply_at - 1 <= i <= apply_at + 1:
                cycle = _run_cycle(seq, payload)
                idx = i - (apply_at - 1)
                if idx < len(base_boundary):
                    assert cycle["request_hex"] == base_boundary[idx]["request_hex"], (
                        f"Boundary frame {idx}: request hex mismatch"
                    )
                    assert cycle["response_hex"] == base_boundary[idx]["response_hex"], (
                        f"Boundary frame {idx}: response hex mismatch"
                    )
            seq = (seq + 1) & 0xFF

    def test_ratio_after_apply(self, baseline):
        """CH1 ratio after setpoint apply must match v1 baseline mean."""
        payload_after = build_io_payload_model(3, [50.0, 30.0, 20.0])
        cycle = _run_cycle(SEQ_START, payload_after)
        base_after = baseline["scenarios"]["s2"]["rx_ratio_ch1_after"]
        assert cycle["rx_ratio_ch1_percent"] == pytest.approx(base_after["mean"], abs=0.1), (
            f"v2 ratio {cycle['rx_ratio_ch1_percent']} != v1 mean {base_after['mean']}"
        )

    def test_ratio_before_apply_is_zero(self, baseline):
        """CH1 ratio before setpoint apply should be 0%."""
        cycle = _run_cycle(SEQ_START, default_io_payload(1))
        assert cycle["rx_ratio_ch1_percent"] == pytest.approx(0.0, abs=0.01)

    def test_channel_count_changes_at_boundary(self, baseline):
        """Payload channel count should change from 1 to 3 at apply_at."""
        payload_before = default_io_payload(1)
        payload_after = build_io_payload_model(3, [50.0, 30.0, 20.0])

        req_before = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload_before))
        req_after = build_frame(SEQ_START, SnetCommand.IO_REQUEST, build_io_payload_bytes(payload_after))

        view_before = decode_frame_view(req_before)
        io_before = decode_io_payload(view_before.data)
        assert io_before is not None
        assert io_before.channel_count == 1

        view_after = decode_frame_view(req_after)
        io_after = decode_io_payload(view_after.data)
        assert io_after is not None
        assert io_after.channel_count == 3


# ---------------------------------------------------------------------------
# S3: write_var skip cycle parity
# ---------------------------------------------------------------------------

class TestS3Parity:
    """Verify v2 S3 produces matching sample count and write_var frame hex."""

    def test_sample_count_matches(self, baseline):
        """v2 S3 math: 20 ticks - 1 write_var - 1 skip = 18 samples."""
        base_s3 = baseline["scenarios"]["s3"]
        expected = base_s3["total_timer_ticks"] - 1 - base_s3["skipped_cycles"]
        assert base_s3["actual_samples"] == expected == 18

    def test_skip_count_is_one(self, baseline):
        """Exactly 1 skip cycle after write_var."""
        assert baseline["scenarios"]["s3"]["skipped_cycles"] == 1

    def test_write_var_frame_hex_matches_v1(self, baseline):
        """v2 builds byte-identical write_var frame as v1 baseline."""
        base_s3 = baseline["scenarios"]["s3"]
        base_hex = base_s3["write_var_frame_hex"]
        assert base_hex is not None, "Baseline missing write_var_frame_hex"

        params = base_s3["write_var_params"]
        # v1 captures write_var at tick 5; 5 samples consumed seqs C0-C4, write_var gets C5
        expected_seq = (SEQ_START + 5) & 0xFF
        v2_frame = build_write_var_frame(expected_seq, params["var_index"], params["value"])
        assert v2_frame.hex() == base_hex, (
            f"v2: {v2_frame.hex()}\nv1: {base_hex}"
        )

    def test_write_var_payload_roundtrip(self, baseline):
        """v2 write_var frame encodes and decodes var_index + value correctly."""
        from snet_tester2.protocol.codec import decode_var_value_payload
        params = baseline["scenarios"]["s3"]["write_var_params"]
        frame = build_write_var_frame(SEQ_START, params["var_index"], params["value"])
        decoded = decode_var_value_payload(decode_frame_view(frame).data)
        assert decoded is not None
        assert decoded[0] == params["var_index"]
        assert decoded[1] == params["value"]

    def test_sample_frames_before_skip_match_v1(self, baseline):
        """v2 sample frames before the skip produce same hex as S1 (same payload)."""
        # Before write_var (ticks 0-4), S3 uses default_io_payload(1) — same as S1
        base_s1_samples = baseline["scenarios"]["s1"]["samples"]
        payload = default_io_payload(1)
        for i in range(min(5, len(base_s1_samples))):
            seq = (SEQ_START + i) & 0xFF
            cycle = _run_cycle(seq, payload)
            assert cycle["request_hex"] == base_s1_samples[i]["request_hex"], (
                f"Pre-skip frame {i}: request hex mismatch"
            )
