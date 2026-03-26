"""Tests for compact summary row preparation."""

from snet_tester.protocol.types import IoChannelValue, IoPayload, SnetChannelMonitor, SnetMonitorSnapshot
from snet_tester.views.plot_view import build_channel_console_rows


def test_build_channel_console_rows_live_channel():
    tx_payload = IoPayload(
        control_mode=0,
        channel_count=2,
        channels=(
            IoChannelValue(override=0, ratio_raw=0x4000, ratio_percent=50.0),
            IoChannelValue(override=0, ratio_raw=0x2000, ratio_percent=25.0),
        ),
    )
    rx_monitor = SnetMonitorSnapshot(
        status=0,
        mode=0,
        pressure_raw=0,
        temperature_raw=0,
        channel_count=2,
        channels=(
            SnetChannelMonitor(ad_raw=0, flow_raw=0x1000, ratio_raw=0x4000, valve_raw=0x4000),
            SnetChannelMonitor(ad_raw=0, flow_raw=0x0800, ratio_raw=0x2000, valve_raw=0x2000),
        ),
    )

    rows = build_channel_console_rows(tx_payload, rx_monitor, rx_stale=False)

    assert rows[0].set_percent == 50.0
    assert rows[0].actual_percent is not None
    assert rows[0].valve_volts is not None
    assert rows[0].state_text == 'LIVE'
    assert rows[2].state_text == 'IDLE'


def test_build_channel_console_rows_set_only_and_stale():
    tx_payload = IoPayload(
        control_mode=0,
        channel_count=1,
        channels=(IoChannelValue(override=0, ratio_raw=0x199A, ratio_percent=10.0),),
    )

    rows = build_channel_console_rows(tx_payload, None, rx_stale=True)

    assert rows[0].set_percent == 10.0
    assert rows[0].actual_percent is None
    assert rows[0].state_text == 'SET'
    assert rows[1].state_text == 'IDLE'


def test_build_channel_console_rows_includes_valve_values():
    tx_payload = IoPayload(
        control_mode=0,
        channel_count=1,
        channels=(IoChannelValue(override=0, ratio_raw=0x4000, ratio_percent=50.0),),
    )
    rx_monitor = SnetMonitorSnapshot(
        status=0,
        mode=0,
        pressure_raw=0,
        temperature_raw=0,
        channel_count=1,
        channels=(
            SnetChannelMonitor(
                ad_raw=0,
                flow_raw=0x0800,
                ratio_raw=0x4000,
                valve_raw=0x4000,
            ),
        ),
    )

    rows = build_channel_console_rows(tx_payload, rx_monitor, rx_stale=False)

    assert rows[0].valve_volts is not None
    assert rows[0].actual_percent == 50.0
    assert rows[0].state_text == 'LIVE'
