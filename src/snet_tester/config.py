"""Runtime configuration."""

from dataclasses import dataclass


@dataclass
class SerialConfig:
    port: str = 'COM6'
    baud: int = 115200
    rx_timeout_s: float = 1.0
    sample_period_s: float = 0.05
    run_forever: bool = True
    test_count: int = 100
