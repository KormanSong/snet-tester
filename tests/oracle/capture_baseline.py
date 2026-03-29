"""v1 mock mode oracle baseline capture.

Reproduces the three core mock-mode paths from MainWindow without
importing any Qt or serial code, ensuring headless isolation.

Scenarios:
  S1  Basic sample loop — 100 REQUEST/RESPONSE cycles, channel_count=1
  S2  Setpoint apply mid-run — change payload at cycle 50 (ch_count=3, 50%/30%/20%)
  S3  write_var skip — simulate _mock_skip_cycles=1 (cycle skipped after var write)

Run:  python -m tests.oracle.capture_baseline
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import asdict, dataclass
from typing import Optional

from snet_tester.protocol.codec import (
    build_frame,
    build_io_payload_bytes,
    build_io_payload_model,
    build_mock_snet_monitor_payload,
    build_write_var_frame,
    decode_frame_view,
    decode_io_payload,
    decode_snet_monitor_payload,
    default_io_payload,
    first_monitor_ratio_percent,
)
from snet_tester.protocol.constants import (
    FULL_OPEN_VALUE_VAR_INDEX,
    REQUEST_CMD,
    RESPONSE_CMD,
    SEQ_START,
)
from snet_tester.protocol.types import IoPayload, SampleEvent

OUTPUT_PATH = pathlib.Path(__file__).parent / "v1_baseline.json"

MOCK_LATENCY_MS = 5.0


# ---------------------------------------------------------------------------
# Local RunningStats — independent of views/main_window.py (headless safe)
# ---------------------------------------------------------------------------

class RunningStats:
    """Welford online mean/variance — mirrors v1 MainWindow.RunningStats exactly."""

    def __init__(self):
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.min: Optional[float] = None
        self.max: Optional[float] = None

    def add(self, value: float):
        self.count += 1
        if self.min is None or value < self.min:
            self.min = value
        if self.max is None or value > self.max:
            self.max = value
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    def stdev(self) -> Optional[float]:
        if self.count < 2:
            return None
        return (self.m2 / (self.count - 1)) ** 0.5

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "mean": self.mean,
            "stdev": self.stdev(),
            "min": self.min,
            "max": self.max,
        }


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------

def _run_mock_cycle(seq: int, index: int, payload: IoPayload) -> dict:
    """Reproduce one MainWindow._emit_mock_sample cycle (main_window.py:535-569)."""
    request_bytes = build_io_payload_bytes(payload)
    request = build_frame(seq, REQUEST_CMD, request_bytes)
    tx_frame = decode_frame_view(request)
    tx_payload = decode_io_payload(tx_frame.data)

    response_bytes = build_mock_snet_monitor_payload(payload)
    response = build_frame(seq, RESPONSE_CMD, response_bytes)
    rx_frame = decode_frame_view(response)
    rx_monitor = decode_snet_monitor_payload(rx_frame.data)

    rx_ratio = first_monitor_ratio_percent(rx_monitor)

    return {
        "index": index,
        "seq": seq,
        "success": True,
        "latency_ms": MOCK_LATENCY_MS,
        "tx_channel_count": payload.channel_count,
        "tx_ratios": [ch.ratio_percent for ch in payload.channels[:payload.channel_count]],
        "rx_ratio_ch1_percent": rx_ratio,
        "request_hex": request.hex(),
        "response_hex": response.hex(),
    }


# ---------------------------------------------------------------------------
# S1: Basic sample loop — 100 cycles, 1 channel, 0% setpoint
# ---------------------------------------------------------------------------

def scenario_s1(cycle_count: int = 100) -> dict:
    """Basic mock sample loop — mirrors v1 default startup."""
    payload = default_io_payload(channel_count=1)
    lat_stats = RunningStats()
    ratio_stats = RunningStats()
    seq = SEQ_START
    samples = []

    for i in range(cycle_count):
        cycle = _run_mock_cycle(seq, i + 1, payload)
        lat_stats.add(cycle["latency_ms"])
        if cycle["rx_ratio_ch1_percent"] is not None:
            ratio_stats.add(cycle["rx_ratio_ch1_percent"])
        if i < 5:
            samples.append(cycle)
        seq = (seq + 1) & 0xFF

    return {
        "name": "s1_basic_sample_loop",
        "cycle_count": cycle_count,
        "success_count": cycle_count,
        "fail_count": 0,
        "latency": lat_stats.to_dict(),
        "rx_ratio_ch1": ratio_stats.to_dict(),
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# S2: Setpoint apply mid-run — change at cycle 50
# ---------------------------------------------------------------------------

def scenario_s2(cycle_count: int = 100, apply_at: int = 50) -> dict:
    """Setpoint change mid-run — v1 _on_set_clicked → applied_setpoint event."""
    payload_before = default_io_payload(channel_count=1)
    payload_after = build_io_payload_model(
        channel_count=3, ratio_percents=[50.0, 30.0, 20.0],
    )

    lat_stats = RunningStats()
    ratio_stats_before = RunningStats()
    ratio_stats_after = RunningStats()
    seq = SEQ_START
    samples_at_boundary = []

    for i in range(cycle_count):
        payload = payload_before if i < apply_at else payload_after
        cycle = _run_mock_cycle(seq, i + 1, payload)
        lat_stats.add(cycle["latency_ms"])

        rx_ratio = cycle["rx_ratio_ch1_percent"]
        if rx_ratio is not None:
            if i < apply_at:
                ratio_stats_before.add(rx_ratio)
            else:
                ratio_stats_after.add(rx_ratio)

        # Capture boundary samples: apply_at-1, apply_at, apply_at+1
        if apply_at - 1 <= i <= apply_at + 1:
            samples_at_boundary.append(cycle)

        seq = (seq + 1) & 0xFF

    return {
        "name": "s2_setpoint_apply",
        "cycle_count": cycle_count,
        "apply_at_cycle": apply_at,
        "payload_before": {"channel_count": 1, "ratios": [0.0]},
        "payload_after": {"channel_count": 3, "ratios": [50.0, 30.0, 20.0]},
        "latency": lat_stats.to_dict(),
        "rx_ratio_ch1_before": ratio_stats_before.to_dict(),
        "rx_ratio_ch1_after": ratio_stats_after.to_dict(),
        "samples_at_boundary": samples_at_boundary,
    }


# ---------------------------------------------------------------------------
# S3: write_var + skip cycle
# ---------------------------------------------------------------------------

def scenario_s3() -> dict:
    """write_var causes _mock_skip_cycles=1 — next sample cycle is skipped.

    Reproduces main_window.py:492-505:
    - emit_mock_write_var sets _mock_skip_cycles = max(_, 1)
    - _emit_mock_sample checks skip_cycles > 0 → decrement and return early
    """
    payload = default_io_payload(channel_count=1)
    seq = SEQ_START
    actual_samples = 0
    skipped_cycles = 0
    skip_counter = 0
    timeline = []  # list of ("sample", cycle_data) | ("write_var", var_info) | ("skipped",)

    total_timer_ticks = 20  # simulate 20 timer ticks

    # At tick 5, issue a write_var command
    write_var_at_tick = 5

    for tick in range(total_timer_ticks):
        if tick == write_var_at_tick:
            # Simulate _emit_mock_write_var (main_window.py:492-505)
            var_index = FULL_OPEN_VALUE_VAR_INDEX
            value = 42000
            request = build_write_var_frame(seq, var_index, value)
            tx_frame = decode_frame_view(request)
            timeline.append({
                "tick": tick,
                "type": "write_var",
                "var_index": var_index,
                "value": value,
                "frame_hex": request.hex(),
            })
            seq = (seq + 1) & 0xFF
            skip_counter = max(skip_counter, 1)  # main_window.py:505
            continue

        # Simulate _emit_mock_sample with skip check (main_window.py:536-538)
        if skip_counter > 0:
            skip_counter -= 1
            timeline.append({"tick": tick, "type": "skipped"})
            skipped_cycles += 1
            continue

        actual_samples += 1
        cycle = _run_mock_cycle(seq, actual_samples, payload)
        timeline.append({"tick": tick, "type": "sample", "index": actual_samples})
        seq = (seq + 1) & 0xFF

    # Extract frame hexes for parity verification
    write_var_frame_hex = None
    first_sample_after_skip_hex = None
    for e in timeline:
        if e["type"] == "write_var" and "frame_hex" in e:
            write_var_frame_hex = e["frame_hex"]
        if e["type"] == "sample" and "index" in e:
            cycle_data = e.get("cycle")
            if first_sample_after_skip_hex is None and e["tick"] > write_var_at_tick + 1:
                # First sample after skip
                first_sample_after_skip_hex = _run_mock_cycle(
                    (SEQ_START + e["tick"] - 1) & 0xFF,  # approximate seq
                    e["index"], payload,
                ).get("request_hex")

    return {
        "name": "s3_write_var_skip",
        "total_timer_ticks": total_timer_ticks,
        "write_var_at_tick": write_var_at_tick,
        "actual_samples": actual_samples,
        "skipped_cycles": skipped_cycles,
        "expected_skipped": 1,
        "write_var_frame_hex": write_var_frame_hex,
        "write_var_params": {"var_index": FULL_OPEN_VALUE_VAR_INDEX, "value": 42000},
        "timeline_summary": [
            {"tick": e["tick"], "type": e["type"]} for e in timeline
        ],
    }


# ---------------------------------------------------------------------------
# Full capture
# ---------------------------------------------------------------------------

def capture_current() -> dict:
    """Run all scenarios and return the full oracle dict."""
    return {
        "version": "v1",
        "scenarios": {
            "s1": scenario_s1(),
            "s2": scenario_s2(),
            "s3": scenario_s3(),
        },
    }


def main():
    data = capture_current()
    OUTPUT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Baseline written to {OUTPUT_PATH}")
    print(f"  S1: {data['scenarios']['s1']['cycle_count']} cycles, "
          f"latency mean={data['scenarios']['s1']['latency']['mean']:.2f}")
    print(f"  S2: apply at cycle {data['scenarios']['s2']['apply_at_cycle']}, "
          f"ratio after mean={data['scenarios']['s2']['rx_ratio_ch1_after']['mean']:.2f}%")
    print(f"  S3: {data['scenarios']['s3']['actual_samples']} samples, "
          f"{data['scenarios']['s3']['skipped_cycles']} skipped")


if __name__ == "__main__":
    main()
