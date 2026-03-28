"""Oracle regression tests — compares fresh capture against frozen v1 baseline.

Each test runs capture_current() to regenerate scenario data, then asserts
that key values match the committed v1_baseline.json.  This ensures that
protocol-layer changes in v2 do not silently alter v1-equivalent behavior.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from snet_tester.protocol.codec import decode_frame_view
from snet_tester.protocol.constants import REQUEST_CMD, RESPONSE_CMD

from .capture_baseline import capture_current

BASELINE_PATH = pathlib.Path(__file__).parent / "v1_baseline.json"


@pytest.fixture(scope="module")
def baseline() -> dict:
    """Load the committed v1 baseline (frozen reference)."""
    assert BASELINE_PATH.exists(), f"Baseline not found: {BASELINE_PATH}"
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fresh() -> dict:
    """Run capture_current() to get a fresh oracle from the current codebase."""
    return capture_current()


# ---------------------------------------------------------------------------
# S1: Basic sample loop regression
# ---------------------------------------------------------------------------

class TestS1BasicSampleLoop:
    def test_cycle_count(self, baseline, fresh):
        assert fresh["scenarios"]["s1"]["cycle_count"] == baseline["scenarios"]["s1"]["cycle_count"]

    def test_all_success(self, baseline, fresh):
        s1 = fresh["scenarios"]["s1"]
        assert s1["success_count"] == s1["cycle_count"]
        assert s1["fail_count"] == 0

    def test_latency_mean_matches(self, baseline, fresh):
        assert fresh["scenarios"]["s1"]["latency"]["mean"] == pytest.approx(
            baseline["scenarios"]["s1"]["latency"]["mean"]
        )

    def test_latency_stdev_matches(self, baseline, fresh):
        fresh_stdev = fresh["scenarios"]["s1"]["latency"]["stdev"]
        base_stdev = baseline["scenarios"]["s1"]["latency"]["stdev"]
        if base_stdev is None:
            assert fresh_stdev is None
        else:
            assert fresh_stdev == pytest.approx(base_stdev)

    def test_rx_ratio_mean_matches(self, baseline, fresh):
        assert fresh["scenarios"]["s1"]["rx_ratio_ch1"]["mean"] == pytest.approx(
            baseline["scenarios"]["s1"]["rx_ratio_ch1"]["mean"]
        )

    def test_first_frame_hex_matches(self, baseline, fresh):
        """First REQUEST frame must be byte-identical."""
        fresh_hex = fresh["scenarios"]["s1"]["samples"][0]["request_hex"]
        base_hex = baseline["scenarios"]["s1"]["samples"][0]["request_hex"]
        assert fresh_hex == base_hex

    def test_first_response_hex_matches(self, baseline, fresh):
        """First RESPONSE frame must be byte-identical."""
        fresh_hex = fresh["scenarios"]["s1"]["samples"][0]["response_hex"]
        base_hex = baseline["scenarios"]["s1"]["samples"][0]["response_hex"]
        assert fresh_hex == base_hex

    def test_frame_roundtrip(self, baseline):
        """Decode a baseline frame and verify cmd field."""
        raw = bytes.fromhex(baseline["scenarios"]["s1"]["samples"][0]["request_hex"])
        view = decode_frame_view(raw)
        assert view.cmd == REQUEST_CMD

    def test_sample_seq_progression(self, fresh):
        """SEQ values must increment (mod 256) from SEQ_START=0xC0."""
        samples = fresh["scenarios"]["s1"]["samples"]
        for i in range(1, len(samples)):
            expected = (samples[i - 1]["seq"] + 1) & 0xFF
            assert samples[i]["seq"] == expected


# ---------------------------------------------------------------------------
# S2: Setpoint apply mid-run
# ---------------------------------------------------------------------------

class TestS2SetpointApply:
    def test_apply_at_cycle(self, baseline, fresh):
        assert fresh["scenarios"]["s2"]["apply_at_cycle"] == baseline["scenarios"]["s2"]["apply_at_cycle"]

    def test_ratio_before_is_zero(self, fresh):
        """Before setpoint apply, CH1 ratio should be ~0%."""
        mean = fresh["scenarios"]["s2"]["rx_ratio_ch1_before"]["mean"]
        assert mean == pytest.approx(0.0, abs=0.1)

    def test_ratio_after_matches_setpoint(self, baseline, fresh):
        """After apply, CH1 ratio should match the 50% setpoint."""
        fresh_mean = fresh["scenarios"]["s2"]["rx_ratio_ch1_after"]["mean"]
        base_mean = baseline["scenarios"]["s2"]["rx_ratio_ch1_after"]["mean"]
        assert fresh_mean == pytest.approx(base_mean, abs=0.1)

    def test_boundary_channel_count_change(self, fresh):
        """At the boundary, channel count should change from 1 to 3."""
        boundary = fresh["scenarios"]["s2"]["samples_at_boundary"]
        assert len(boundary) >= 2
        # Last sample before apply: ch_count=1
        assert boundary[0]["tx_channel_count"] == 1
        # First sample after apply: ch_count=3
        assert boundary[1]["tx_channel_count"] == 3

    def test_boundary_frame_hex_matches(self, baseline, fresh):
        """Boundary frames must be byte-identical."""
        for i in range(min(len(fresh["scenarios"]["s2"]["samples_at_boundary"]),
                          len(baseline["scenarios"]["s2"]["samples_at_boundary"]))):
            assert (fresh["scenarios"]["s2"]["samples_at_boundary"][i]["request_hex"]
                    == baseline["scenarios"]["s2"]["samples_at_boundary"][i]["request_hex"])


# ---------------------------------------------------------------------------
# S3: write_var skip cycle
# ---------------------------------------------------------------------------

class TestS3WriteVarSkip:
    def test_exactly_one_skip(self, baseline, fresh):
        s3 = fresh["scenarios"]["s3"]
        assert s3["skipped_cycles"] == 1
        assert s3["skipped_cycles"] == baseline["scenarios"]["s3"]["skipped_cycles"]

    def test_actual_sample_count(self, baseline, fresh):
        assert fresh["scenarios"]["s3"]["actual_samples"] == baseline["scenarios"]["s3"]["actual_samples"]

    def test_skip_follows_write_var(self, fresh):
        """The skip must occur on the tick immediately after write_var."""
        timeline = fresh["scenarios"]["s3"]["timeline_summary"]
        write_tick = None
        for entry in timeline:
            if entry["type"] == "write_var":
                write_tick = entry["tick"]
            elif entry["type"] == "skipped" and write_tick is not None:
                assert entry["tick"] == write_tick + 1, (
                    f"Skip at tick {entry['tick']}, expected {write_tick + 1}"
                )
                break
        else:
            pytest.fail("No skip found after write_var")

    def test_timeline_matches(self, baseline, fresh):
        """Full timeline type sequence must match baseline."""
        fresh_types = [e["type"] for e in fresh["scenarios"]["s3"]["timeline_summary"]]
        base_types = [e["type"] for e in baseline["scenarios"]["s3"]["timeline_summary"]]
        assert fresh_types == base_types
