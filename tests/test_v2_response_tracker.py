"""Unit tests for ResponseTimeTracker — 98~102% tolerance, 0% target, state transitions."""

import pytest

from snet_tester2.protocol.codec import build_io_payload_model
from snet_tester2.protocol.convert import ratio_percent_to_raw
from snet_tester2.protocol.types import (
    IoPayload, SampleEvent, SnetChannelMonitor, SnetMonitorSnapshot,
)
from snet_tester2.views.response_tracker import ResponseTimeTracker


def _make_monitor(ratios_percent: list[float]) -> SnetMonitorSnapshot:
    """Build a SnetMonitorSnapshot from ratio percentages."""
    channels = tuple(
        SnetChannelMonitor(
            ad_raw=0, flow_raw=0,
            ratio_raw=ratio_percent_to_raw(r),
            valve_raw=0,
        )
        for r in ratios_percent
    )
    return SnetMonitorSnapshot(
        status=0, mode=0, pressure_raw=0, temperature_raw=0,
        channel_count=len(channels), channels=channels,
    )


def _make_sample(monitor: SnetMonitorSnapshot, payload: IoPayload) -> SampleEvent:
    return SampleEvent(
        index=1, seq=0, request_raw=b'', response_raw=b'',
        tx_payload=payload, rx_monitor=monitor,
        latency_ms=5.0, success=True,
    )


class TestAllInRange:
    """Test the 98~102% tolerance logic."""

    def test_exact_match(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [50.0])
        t.start(payload, None)
        mon = _make_monitor([50.0])
        sample = _make_sample(mon, payload)
        elapsed = t.check(sample)
        assert elapsed is not None

    def test_at_98_percent_boundary(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [50.0])
        t.start(payload, None)
        # 50 * 0.98 = 49.0 — use 49.1 to account for raw/percent quantization
        mon = _make_monitor([49.1])
        sample = _make_sample(mon, payload)
        elapsed = t.check(sample)
        assert elapsed is not None

    def test_at_102_percent_boundary(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [50.0])
        t.start(payload, None)
        # 50 * 1.02 = 51.0 — use 50.9 to account for raw/percent quantization
        mon = _make_monitor([50.9])
        sample = _make_sample(mon, payload)
        elapsed = t.check(sample)
        assert elapsed is not None

    def test_below_98_percent(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [50.0])
        t.start(payload, None)
        # 48.0 < 49.0 (98% of 50) — out of range
        mon = _make_monitor([48.0])
        sample = _make_sample(mon, payload)
        elapsed = t.check(sample)
        assert elapsed is None
        assert t.is_active

    def test_above_102_percent(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [50.0])
        t.start(payload, None)
        # 52.0 > 51.0 (102% of 50) — out of range
        mon = _make_monitor([52.0])
        sample = _make_sample(mon, payload)
        elapsed = t.check(sample)
        assert elapsed is None


class TestZeroTarget:
    """Test the special 0% target handling (accept actual <= 2%)."""

    def test_zero_target_at_zero(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [0.0])
        t.start(payload, None)
        mon = _make_monitor([0.0])
        sample = _make_sample(mon, payload)
        elapsed = t.check(sample)
        assert elapsed is not None

    def test_zero_target_at_2_percent(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [0.0])
        t.start(payload, None)
        mon = _make_monitor([2.0])
        sample = _make_sample(mon, payload)
        elapsed = t.check(sample)
        assert elapsed is not None

    def test_zero_target_above_2_percent(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [0.0])
        t.start(payload, None)
        mon = _make_monitor([3.0])
        sample = _make_sample(mon, payload)
        elapsed = t.check(sample)
        assert elapsed is None
        assert t.is_active


class TestStateTransitions:
    """Test is_active / is_settled state machine."""

    def test_initial_state(self):
        t = ResponseTimeTracker()
        assert not t.is_active
        assert not t.is_settled

    def test_start_activates(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [50.0])
        t.start(payload, None)
        assert t.is_active
        assert not t.is_settled

    def test_already_in_range_does_not_activate(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [50.0])
        mon = _make_monitor([50.0])
        t.start(payload, mon)
        assert not t.is_active  # already settled

    def test_settle_deactivates(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [50.0])
        t.start(payload, None)
        mon = _make_monitor([50.0])
        sample = _make_sample(mon, payload)
        elapsed = t.check(sample)
        assert elapsed is not None
        assert not t.is_active
        assert t.is_settled

    def test_check_after_settle_returns_none(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [50.0])
        t.start(payload, None)
        mon = _make_monitor([50.0])
        sample = _make_sample(mon, payload)
        t.check(sample)  # settles
        assert t.check(sample) is None  # already settled

    def test_rx_monitor_none_does_not_settle(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(1, [50.0])
        t.start(payload, None)
        sample = SampleEvent(
            index=1, seq=0, request_raw=b'', response_raw=None,
            tx_payload=payload, rx_monitor=None,
            latency_ms=5.0, success=False,
        )
        assert t.check(sample) is None
        assert t.is_active


class TestMultiChannel:
    """Test multi-channel tolerance (all channels must be in range)."""

    def test_all_channels_in_range(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(3, [50.0, 30.0, 20.0])
        t.start(payload, None)
        mon = _make_monitor([50.0, 30.0, 20.0])
        sample = _make_sample(mon, payload)
        assert t.check(sample) is not None

    def test_one_channel_out_of_range(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(3, [50.0, 30.0, 20.0])
        t.start(payload, None)
        # CH3 at 15% — out of range for 20% target (19.6~20.4)
        mon = _make_monitor([50.0, 30.0, 15.0])
        sample = _make_sample(mon, payload)
        assert t.check(sample) is None

    def test_monitor_fewer_channels(self):
        t = ResponseTimeTracker()
        payload = build_io_payload_model(3, [50.0, 30.0, 20.0])
        t.start(payload, None)
        mon = _make_monitor([50.0])  # only 1 channel
        sample = _make_sample(mon, payload)
        assert t.check(sample) is None
