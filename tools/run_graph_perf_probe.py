"""Automated graph-performance probe runner for snet_tester2.

Runs the real display path (no offscreen override), applies a fixed TX setup,
resets frame metrics and setData counters, waits for a measurement window, then
prints a JSON snapshot to stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import types
from dataclasses import replace
from typing import Sequence

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt

from snet_tester2 import configure_qt_environment
from snet_tester2.views.main_window import MainWindow


def _compute_metrics(
    intervals_ms: Sequence[float],
    *,
    target_fps: float,
    timer_interval_ms: float,
    drop_tolerance_ms: float = 0.5,
) -> dict[str, float] | None:
    if not intervals_ms:
        return None

    n = len(intervals_ms)
    target_budget_ms = 1000.0 / max(1.0, float(target_fps))
    drop_threshold_ms = max(target_budget_ms, float(timer_interval_ms)) + max(0.0, float(drop_tolerance_ms))
    dropped = sum(1 for interval_ms in intervals_ms if interval_ms > drop_threshold_ms)
    sorted_intervals = sorted(intervals_ms)
    avg_interval_ms = sum(intervals_ms) / n
    avg_fps = 1000.0 / max(1e-6, avg_interval_ms)

    one_pct_count = max(1, int(math.ceil(n * 0.01)))
    worst_one_pct = sorted_intervals[-one_pct_count:]
    low_1pct_fps = 1000.0 / max(1e-6, sum(worst_one_pct) / len(worst_one_pct))
    perceptual_threshold_ms = 1000.0 / 40.0
    severe_threshold_ms = 1000.0 / 30.0
    perceptual_drops = sum(1 for interval_ms in intervals_ms if interval_ms > perceptual_threshold_ms)
    severe_drops = sum(1 for interval_ms in intervals_ms if interval_ms > severe_threshold_ms)

    def percentile_ms(ratio: float) -> float:
        rank = max(1, int(math.ceil(ratio * n)))
        idx = min(n - 1, rank - 1)
        return sorted_intervals[idx]

    return {
        "avg_fps": avg_fps,
        "low_1pct_fps": low_1pct_fps,
        "drop_pct": (dropped / n) * 100.0,
        "drop_below_40fps_pct": (perceptual_drops / n) * 100.0,
        "drop_below_30fps_pct": (severe_drops / n) * 100.0,
        "drop_below_40fps_threshold_ms": perceptual_threshold_ms,
        "drop_below_30fps_threshold_ms": severe_threshold_ms,
        "drop_threshold_ms": drop_threshold_ms,
        "p999_ms": percentile_ms(0.999),
        "p9999_ms": percentile_ms(0.9999),
        "worst_ms": sorted_intervals[-1],
        "frame_samples": n,
    }


def _parse_ratios(text: str, channels: int) -> list[float]:
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) < channels:
        raise ValueError(f"Need at least {channels} ratios, got {len(parts)}")
    values = [float(parts[i]) for i in range(channels)]
    for idx, value in enumerate(values, start=1):
        if value < 0.0 or value > 100.0:
            raise ValueError(f"CH{idx} ratio out of range 0..100: {value}")
    return values


def _parse_ratio_sequence(text: str, channels: int) -> list[list[float]]:
    groups = [g.strip() for g in text.split(";") if g.strip()]
    if not groups:
        return []
    sequence: list[list[float]] = []
    for group in groups:
        sequence.append(_parse_ratios(group, channels))
    return sequence


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automated snet_tester2 graph-performance probe")
    parser.add_argument("--duration", type=float, default=30.5, help="measurement duration in seconds")
    parser.add_argument("--warmup", type=float, default=10.0, help="warmup seconds before metric reset")
    parser.add_argument("--mock", action="store_true", help="run in mock mode")
    parser.add_argument("--port", type=str, default="COM1", help="serial port when not mock")
    parser.add_argument("--baud", type=int, default=115200, help="serial baud rate")
    parser.add_argument("--channels", type=int, default=5, help="active channel count")
    parser.add_argument(
        "--sample-period-ms",
        type=float,
        default=None,
        help="override sample period in milliseconds (e.g., 32)",
    )
    parser.add_argument(
        "--ratios",
        type=str,
        default="20,40,60,80,100",
        help="comma-separated setpoint ratios for active channels",
    )
    parser.add_argument(
        "--ratio-sequence",
        type=str,
        default="",
        help=(
            "semicolon-separated ratio sets to apply during measurement, "
            "e.g. '20,40,60,80,100;80,60,40,20,10'"
        ),
    )
    parser.add_argument(
        "--ratio-change-interval",
        type=float,
        default=2.0,
        help="seconds between ratio-sequence applies during measurement",
    )
    parser.add_argument(
        "--diag-mode",
        type=str,
        choices=("normal", "guard_no_skip", "guard_invalidate_on_sample"),
        default="normal",
        help=(
            "normal: current code path; "
            "guard_no_skip: keep signature calc but force no skip for visibility/style; "
            "guard_invalidate_on_sample: full guard + invalidate visibility signature each sample"
        ),
    )
    return parser.parse_args(argv)


def _install_legacy_interval_probe(window: MainWindow) -> dict[str, object]:
    """Install fallback interval/data probes for older code paths.

    Returns a dict with:
    - render_intervals_ms: list[float]
    - data_intervals_ms: list[float]
    - setdata_counts: dict[str, list[int]]
    """
    plot_view = window.plot_view
    setdata_counts = {
        "tx": [0] * 6,
        "rx": [0] * 6,
        "valve": [0] * 6,
    }

    refresh_state = {
        "last_render_s": None,
        "last_data_s": None,
        "render_intervals_ms": [],
        "data_intervals_ms": [],
        "setdata_called_this_refresh": False,
    }

    def _wrap_curve_setdata(series_key: str, ch: int, curve) -> None:
        original = curve.setData

        def _wrapped_setdata(*args, **kwargs):
            setdata_counts[series_key][ch] += 1
            refresh_state["setdata_called_this_refresh"] = True
            return original(*args, **kwargs)

        curve.setData = _wrapped_setdata

    for ch, curve in enumerate(getattr(plot_view, "_curve_tx", [])):
        _wrap_curve_setdata("tx", ch, curve)
    for ch, curve in enumerate(getattr(plot_view, "_curve_rx", [])):
        _wrap_curve_setdata("rx", ch, curve)
    for ch, curve in enumerate(getattr(plot_view, "_curve_valve", [])):
        _wrap_curve_setdata("valve", ch, curve)

    original_refresh = plot_view.refresh

    def _wrapped_refresh(*args, **kwargs):
        t_s = time.perf_counter()
        if refresh_state["last_render_s"] is not None:
            refresh_state["render_intervals_ms"].append((t_s - refresh_state["last_render_s"]) * 1000.0)
        refresh_state["last_render_s"] = t_s

        refresh_state["setdata_called_this_refresh"] = False
        result = original_refresh(*args, **kwargs)
        if refresh_state["setdata_called_this_refresh"]:
            if refresh_state["last_data_s"] is not None:
                refresh_state["data_intervals_ms"].append((t_s - refresh_state["last_data_s"]) * 1000.0)
            refresh_state["last_data_s"] = t_s
        return result

    plot_view.refresh = types.MethodType(lambda self, *a, **k: _wrapped_refresh(*a, **k), plot_view)

    return {
        "render_intervals_ms": refresh_state["render_intervals_ms"],
        "data_intervals_ms": refresh_state["data_intervals_ms"],
        "setdata_counts": setdata_counts,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ratios = _parse_ratios(args.ratios, args.channels)
    ratio_sequence = _parse_ratio_sequence(args.ratio_sequence, args.channels)

    configure_qt_environment()
    app = QtWidgets.QApplication(sys.argv if argv is None else ["run_graph_perf_probe", *argv])
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)

    window = MainWindow(mock_mode=bool(args.mock), port=args.port, baud=int(args.baud))
    window.show()
    plot_view = window.plot_view
    legacy_probe = None
    if not hasattr(window, "_frame_intervals_ms") or not hasattr(window, "_data_frame_intervals_ms"):
        legacy_probe = _install_legacy_interval_probe(window)

    if args.diag_mode == "guard_no_skip":
        if not hasattr(plot_view, "_apply_curve_visibility") or not hasattr(plot_view, "_apply_rx_curve_style"):
            raise RuntimeError("guard_no_skip mode requires visibility/style methods on PlotView")
        original_apply_visibility = plot_view._apply_curve_visibility
        original_apply_rx_style = plot_view._apply_rx_curve_style

        def _apply_visibility_no_skip(self, *, force: bool = False):
            if hasattr(self, "_current_visibility_signature"):
                _ = self._current_visibility_signature()
            if hasattr(self, "_last_visibility_signature"):
                self._last_visibility_signature = None
            return original_apply_visibility()

        def _apply_rx_style_no_skip(self, *, force: bool = False):
            if hasattr(self, "_last_rx_style_stale"):
                self._last_rx_style_stale = None
            return original_apply_rx_style()

        plot_view._apply_curve_visibility = types.MethodType(_apply_visibility_no_skip, plot_view)
        plot_view._apply_rx_curve_style = types.MethodType(_apply_rx_style_no_skip, plot_view)

    elif args.diag_mode == "guard_invalidate_on_sample":
        original_add_point = plot_view.add_point

        def _add_point_invalidate_signature(
            self,
            tx_payload,
            rx_monitor,
            *,
            arrival_monotonic_s=None,
        ):
            result = original_add_point(
                tx_payload,
                rx_monitor,
                arrival_monotonic_s=arrival_monotonic_s,
            )
            if hasattr(self, "_last_visibility_signature"):
                self._last_visibility_signature = None
            return result

        plot_view.add_point = types.MethodType(_add_point_invalidate_signature, plot_view)

    sequence_state = {
        "timer": None,
        "index": 0,
        "applied_count": 0,
        "active": False,
    }

    def _apply_ratios(values: list[float]) -> None:
        window.tx_panel.channelCountCombo.setCurrentText(str(args.channels))
        for idx, value in enumerate(values, start=1):
            getattr(window.tx_panel, f"ratioInput{idx}").setText(f"{value:g}")
        window._on_set_clicked()

    def configure_and_start() -> None:
        if args.sample_period_ms is not None:
            sample_period_s = max(0.001, float(args.sample_period_ms) / 1000.0)
            if hasattr(window, "_worker_config"):
                window._worker_config = replace(window._worker_config, sample_period_s=sample_period_s)
            if hasattr(window.plot_view, "set_sample_period_s"):
                window.plot_view.set_sample_period_s(sample_period_s)
            if hasattr(window, "_restart_worker_with_current_settings"):
                window._restart_worker_with_current_settings()
        _apply_ratios(ratios)
        window._on_run_clicked()

    def start_measurement() -> None:
        if hasattr(window, "_reset_frame_pacing_metrics"):
            window._reset_frame_pacing_metrics()
        if hasattr(window.plot_view, "reset_setdata_counters"):
            window.plot_view.reset_setdata_counters()
        if ratio_sequence:
            sequence_state["active"] = True
            sequence_state["index"] = 0
            sequence_state["applied_count"] = 0

            def _apply_next_ratio() -> None:
                if not sequence_state["active"]:
                    return
                values = ratio_sequence[sequence_state["index"] % len(ratio_sequence)]
                sequence_state["index"] += 1
                sequence_state["applied_count"] += 1
                _apply_ratios(values)

            _apply_next_ratio()
            timer = QtCore.QTimer(window)
            timer.setTimerType(QtCore.Qt.PreciseTimer)
            timer.timeout.connect(_apply_next_ratio)
            timer.start(max(50, int(round(max(0.05, float(args.ratio_change_interval)) * 1000.0))))
            sequence_state["timer"] = timer

    def finish_measurement() -> None:
        sequence_state["active"] = False
        if sequence_state["timer"] is not None:
            sequence_state["timer"].stop()
            sequence_state["timer"] = None
        if legacy_probe is None:
            render_intervals = list(window._frame_intervals_ms)
            data_intervals = list(window._data_frame_intervals_ms)
        else:
            render_intervals = list(legacy_probe["render_intervals_ms"])
            data_intervals = list(legacy_probe["data_intervals_ms"])

        render_fps_cap = int(window._current_render_fps_cap()) if hasattr(window, "_current_render_fps_cap") else 60
        render_timer_ms = float(window._render_timer.interval()) if hasattr(window, "_render_timer") else (1000.0 / render_fps_cap)
        render_metrics = _compute_metrics(
            render_intervals,
            target_fps=float(render_fps_cap),
            timer_interval_ms=render_timer_ms,
        )
        sample_period_s = max(1e-3, float(window.plot_view.sample_period_s())) if hasattr(window.plot_view, "sample_period_s") else 0.05
        data_metrics = _compute_metrics(
            data_intervals,
            target_fps=1.0 / sample_period_s,
            timer_interval_ms=sample_period_s * 1000.0,
        )
        tx_dirty_counts = None
        tx_skip_ratio_pct_total = None
        if hasattr(window.plot_view, "snapshot_tx_dirty_counters"):
            tx_dirty_counts = window.plot_view.snapshot_tx_dirty_counters()
            called_total = sum(tx_dirty_counts.get("called", ()))
            skipped_total = sum(tx_dirty_counts.get("skipped", ()))
            total = called_total + skipped_total
            tx_skip_ratio_pct_total = (skipped_total / total * 100.0) if total > 0 else 0.0
        if hasattr(window.plot_view, "snapshot_setdata_counters"):
            setdata_counts = window.plot_view.snapshot_setdata_counters()
        else:
            setdata_counts = legacy_probe["setdata_counts"] if legacy_probe is not None else None

        load_shed_counters = None
        if hasattr(window.plot_view, "snapshot_load_shed_counters"):
            load_shed_counters = window.plot_view.snapshot_load_shed_counters()

        if hasattr(window.plot_view, "snapshot_channel_sync_skew"):
            channel_sync_skew = window.plot_view.snapshot_channel_sync_skew()
        elif setdata_counts is not None:
            def _skew(values: list[int]) -> int:
                active = [v for v in values[:args.channels] if v >= 0]
                return 0 if len(active) <= 1 else (max(active) - min(active))
            channel_sync_skew = {
                "tx": _skew(setdata_counts.get("tx", [])),
                "rx": _skew(setdata_counts.get("rx", [])),
                "valve": _skew(setdata_counts.get("valve", [])),
            }
        else:
            channel_sync_skew = None

        payload = {
            "run_condition": {
                "mock_mode": bool(args.mock),
                "port": args.port,
                "channels": int(args.channels),
                "ratios": ratios,
                "sample_period_s": sample_period_s,
                "render_fps_cap": render_fps_cap,
                "duration_s": float(args.duration),
                "warmup_s": float(args.warmup),
                "diag_mode": str(args.diag_mode),
                "ratio_sequence": ratio_sequence,
                "ratio_change_interval_s": float(args.ratio_change_interval),
                "ratio_sequence_applied_count": int(sequence_state["applied_count"]),
            },
            "metrics": render_metrics,  # backward-compatible alias (render tick pacing)
            "render_metrics": render_metrics,
            "data_frame_metrics": data_metrics,
            "setdata_counts": setdata_counts,
            "channel_sync_skew": channel_sync_skew,
            "load_shed_counters": load_shed_counters,
            "tx_dirty_counts": tx_dirty_counts,
            "tx_skip_ratio_pct_total": tx_skip_ratio_pct_total,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        window.shutdown()
        app.quit()

    QtCore.QTimer.singleShot(100, configure_and_start)
    QtCore.QTimer.singleShot(int(max(0.0, args.warmup) * 1000.0), start_measurement)
    QtCore.QTimer.singleShot(int((max(0.0, args.warmup) + max(0.1, args.duration)) * 1000.0), finish_measurement)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
