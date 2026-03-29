"""Tests for v2 raw value conversion functions.

Mirrors tests/test_convert.py but imports from snet_tester2.
The conversion logic is identical to v1; only the import path changes.
"""

from snet_tester2.protocol.constants import (
    FLOW_FULL_SCALE_PERCENT,
    PRESSURE_FULL_SCALE_PSI,
    TEMPERATURE_FULL_SCALE_C,
)
from snet_tester2.protocol.convert import (
    flow_raw_to_display,
    pressure_raw_to_psi,
    ratio_percent_to_raw,
    ratio_raw_to_percent,
    temperature_raw_to_celsius,
    valve_raw_to_display,
)


def test_ratio_roundtrip():
    raw = ratio_percent_to_raw(50.0)
    percent = ratio_raw_to_percent(raw)
    assert abs(percent - 50.0) < 0.01


def test_ratio_clamp():
    assert ratio_percent_to_raw(-10.0) == 0
    assert ratio_percent_to_raw(200.0) == 0x8000
    assert ratio_raw_to_percent(-1) == 0.0
    assert ratio_raw_to_percent(0xFFFF) == 100.0


def test_ratio_zero_and_full():
    assert ratio_percent_to_raw(0.0) == 0
    assert ratio_percent_to_raw(100.0) == 0x8000
    assert ratio_raw_to_percent(0) == 0.0
    assert ratio_raw_to_percent(0x8000) == 100.0


def test_temperature_conversion():
    assert temperature_raw_to_celsius(0) == 0.0
    assert temperature_raw_to_celsius(0x8000) == TEMPERATURE_FULL_SCALE_C
    mid = temperature_raw_to_celsius(0x4000)
    assert abs(mid - (TEMPERATURE_FULL_SCALE_C / 2.0)) < 0.01


def test_pressure_conversion():
    assert pressure_raw_to_psi(0) == 0.0
    assert pressure_raw_to_psi(0x8000) == PRESSURE_FULL_SCALE_PSI


def test_flow_raw_to_display():
    assert flow_raw_to_display(0) == 0.0
    assert flow_raw_to_display(0x8000) == FLOW_FULL_SCALE_PERCENT


def test_valve_raw_to_display():
    assert valve_raw_to_display(0) == 0.0
    assert valve_raw_to_display(0x8000) == 5.0
