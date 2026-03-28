"""Raw value to physical unit conversion functions."""

from .constants import (
    FLOW_FULL_SCALE_PERCENT,
    FLOW_FULL_SCALE_RAW,
    PRESSURE_FULL_SCALE_PSI,
    PRESSURE_FULL_SCALE_RAW,
    RATIO_FULL_SCALE_RAW,
    TEMPERATURE_FULL_SCALE_C,
    TEMPERATURE_FULL_SCALE_RAW,
)


def ratio_percent_to_raw(percent: float) -> int:
    clamped = max(0.0, min(100.0, float(percent)))
    return int(round((clamped / 100.0) * RATIO_FULL_SCALE_RAW))


def ratio_raw_to_percent(ratio_raw: int) -> float:
    raw = max(0, min(RATIO_FULL_SCALE_RAW, int(ratio_raw)))
    return (raw / RATIO_FULL_SCALE_RAW) * 100.0


def temperature_raw_to_celsius(temperature_raw: int) -> float:
    raw = max(0, min(TEMPERATURE_FULL_SCALE_RAW, int(temperature_raw)))
    return (raw / TEMPERATURE_FULL_SCALE_RAW) * TEMPERATURE_FULL_SCALE_C


def pressure_raw_to_psi(pressure_raw: int) -> float:
    raw = max(0, min(PRESSURE_FULL_SCALE_RAW, int(pressure_raw)))
    return (raw / PRESSURE_FULL_SCALE_RAW) * PRESSURE_FULL_SCALE_PSI


def flow_raw_to_display(flow_raw: int) -> float:
    raw = max(0, min(FLOW_FULL_SCALE_RAW, int(flow_raw)))
    return (raw / FLOW_FULL_SCALE_RAW) * FLOW_FULL_SCALE_PERCENT


def valve_raw_to_display(valve_raw: int) -> float:
    raw = max(0, min(RATIO_FULL_SCALE_RAW, int(valve_raw)))
    return (raw / RATIO_FULL_SCALE_RAW) * 5.0
