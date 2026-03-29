"""Response time tracker -- measures time from SET to target ratio reached."""

import time
from typing import Optional

from ..protocol.convert import ratio_raw_to_percent
from ..protocol.types import IoPayload, SampleEvent, SnetMonitorSnapshot


class ResponseTimeTracker:
    def __init__(self):
        self._active = False
        self._settled = False
        self._start_time: float = 0.0
        self._targets: list[float] = []  # target ratio_percent per channel
        self._channel_count: int = 0

    def start(self, applied_payload: IoPayload, current_monitor: Optional[SnetMonitorSnapshot]):
        """Called when SET is applied. Starts measurement if not already in range."""
        self._channel_count = applied_payload.channel_count
        self._targets = [ch.ratio_percent for ch in applied_payload.channels[:self._channel_count]]
        self._settled = False

        # Check if already within 98~102% of target
        if current_monitor is not None and self._all_in_range(current_monitor):
            self._active = False
            return

        self._active = True
        self._start_time = time.perf_counter()

    def check(self, event: SampleEvent) -> Optional[float]:
        """Called on each sample. Returns elapsed seconds if just settled, else None."""
        if not self._active:
            return None

        if event.rx_monitor is None:
            return None

        if self._all_in_range(event.rx_monitor):
            elapsed = time.perf_counter() - self._start_time
            self._active = False
            self._settled = True
            return elapsed

        return None

    def _all_in_range(self, monitor: SnetMonitorSnapshot) -> bool:
        """Check if all active channels are within 98~102% of their target."""
        if monitor.channel_count < self._channel_count:
            return False

        for i in range(self._channel_count):
            target = self._targets[i]
            actual = ratio_raw_to_percent(monitor.channels[i].ratio_raw)

            if target == 0.0:
                # For 0% target, accept actual <= 2%
                if actual > 2.0:
                    return False
            else:
                low = target * 0.98
                high = target * 1.02
                if actual < low or actual > high:
                    return False

        return True

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_settled(self) -> bool:
        return self._settled
