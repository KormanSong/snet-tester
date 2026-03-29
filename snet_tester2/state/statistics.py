"""Online statistics using Welford's algorithm.

Provides a RunningStats accumulator that computes count, mean,
standard deviation, min, and max in a single pass with O(1) memory.
Extracted from v1 main_window.py for reuse across the application.
"""

import math
from typing import Optional


class RunningStats:
    """Welford online mean/variance accumulator.

    Accepts float samples one at a time via add(). Computes
    mean and sample standard deviation without storing all values.

    Attributes:
        count: Number of samples added so far.
        mean:  Running mean of all samples.
        m2:    Sum of squared deviations (internal, for variance).
        min:   Minimum observed value, or None if no samples.
        max:   Maximum observed value, or None if no samples.
    """

    def __init__(self) -> None:
        self.count: int = 0
        self.mean: float = 0.0
        self.m2: float = 0.0
        self.min: Optional[float] = None
        self.max: Optional[float] = None

    def add(self, value: float) -> None:
        """Incorporate a new sample into the running statistics.

        Args:
            value: The sample value to add.
        """
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
        """Return sample standard deviation, or None if fewer than 2 samples.

        Returns:
            Sample standard deviation (Bessel-corrected), or None.
        """
        if self.count < 2:
            return None
        return math.sqrt(self.m2 / (self.count - 1))

    def to_dict(self) -> dict:
        """Return a summary dictionary of the current statistics.

        Returns:
            Dict with keys: count, mean, stdev, min, max.
            stdev is None if fewer than 2 samples.
            min/max are None if no samples have been added.
        """
        return {
            "count": self.count,
            "mean": self.mean,
            "stdev": self.stdev(),
            "min": self.min,
            "max": self.max,
        }
