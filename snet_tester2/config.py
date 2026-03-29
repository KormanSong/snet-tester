"""v2 worker configuration — timing only, no port/baud (Transport owns those)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerConfig:
    rx_timeout_s: float = 1.0
    sample_period_s: float = 0.05
    run_forever: bool = True
    test_count: int = 100
