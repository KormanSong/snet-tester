"""Generate a comparison image for proposed graph themes."""

from __future__ import annotations

import argparse
import os
import pathlib

import matplotlib
import matplotlib.pyplot as plt
import numpy as np


def build_demo_series() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x = np.linspace(0.0, 10.0, 500)
    setpoint = 45.0 + 8.0 * np.sin(x * 0.55)
    actual = setpoint - 3.5 + 2.0 * np.sin((x * 1.7) + 0.5) + 0.7 * np.cos(x * 2.9)
    valve = 2.0 + 0.45 * np.sin((x * 1.3) - 0.4) + 0.12 * np.cos(x * 3.2)
    threshold = np.full_like(x, 70.0)
    return x, setpoint, actual, valve, threshold


_THEMES = {
    "white": {
        "ratio_bg": "#FFFFFF", "valve_bg": "#FBFBFC",
        "major": "#B0B7BF", "minor": "#D8DDE2",
        "axis": "#14171A", "text": "#111111",
        "title": "White Paper Theme", "subtitle": "For XP Gray shell",
        "subtitle_color": "#3A3F45",
        "colors": {
            "setpoint": "#30363D", "actual": "#111111",
            "threshold": "#B42318", "stale": "#6B7280", "valve": "#2F5D8A",
        },
        "accent": "#111111",
    },
    "scope": {
        "ratio_bg": "#000000", "valve_bg": "#080A0D",
        "major": "#2C3238", "minor": "#171B20",
        "axis": "#B7C0C9", "text": "#DCE3EA",
        "title": "Scope Black Theme", "subtitle": "Recommended for Bright Gray shell",
        "subtitle_color": "#9FB5C7",
        "colors": {
            "setpoint": "#FFD400", "actual": "#00E5FF",
            "threshold": "#FF5A4F", "stale": "#FFB347", "valve": "#39FF14",
        },
        "accent": "#DCE3EA",
    },
}


def _apply_theme(ax_ratio, ax_valve, theme: dict) -> None:
    for ax, bg in ((ax_ratio, theme["ratio_bg"]), (ax_valve, theme["valve_bg"])):
        ax.set_facecolor(bg)
        for spine in ax.spines.values():
            spine.set_color(theme["axis"])
            spine.set_linewidth(1.0)
        ax.tick_params(colors=theme["text"], labelsize=9)
        ax.grid(True, which="major", color=theme["major"], linewidth=0.7)
        ax.grid(True, which="minor", color=theme["minor"], linewidth=0.5)
        ax.minorticks_on()

    ax_ratio.set_title(theme["title"], loc="left", color=theme["text"], fontsize=12, fontweight="bold", pad=10)
    ax_ratio.text(
        0.995, 1.02, theme["subtitle"],
        transform=ax_ratio.transAxes, ha="right", va="bottom",
        fontsize=9, color=theme["subtitle_color"],
    )


def draw_panel(ax_ratio, ax_valve, theme_name: str, x, setpoint, actual, valve, threshold) -> None:
    theme = _THEMES[theme_name]
    _apply_theme(ax_ratio, ax_valve, theme)
    colors = theme["colors"]
    accent = theme["accent"]

    ax_ratio.plot(x, setpoint, color=colors["setpoint"], linewidth=1.5, label="Setpoint")
    ax_ratio.plot(x, actual, color=colors["actual"], linewidth=2.2, label="Actual")
    ax_ratio.axhline(threshold[0], color=colors["threshold"], linewidth=1.1, linestyle="--", label="Alarm limit")
    ax_ratio.plot(x[-80:], actual[-80:] - 2.0, color=colors["stale"], linewidth=1.4, linestyle=":", label="Stale sample")

    ax_ratio.set_xlim(0.0, 10.0)
    ax_ratio.set_ylim(0.0, 100.0)
    ax_ratio.set_ylabel("RATIO %", color=accent, fontsize=10, fontweight="bold")

    leg = ax_ratio.legend(
        loc="upper right",
        frameon=False,
        fontsize=8,
        ncol=2,
        labelcolor=accent,
        handlelength=2.2,
    )
    for text in leg.get_texts():
        text.set_color(accent)

    ax_valve.plot(x, valve, color=colors["valve"], linewidth=1.8, label="Valve")
    ax_valve.set_xlim(0.0, 10.0)
    ax_valve.set_ylim(0.0, 5.0)
    ax_valve.set_ylabel("VALVE", color=accent, fontsize=10, fontweight="bold")
    ax_valve.set_xlabel("TIME (S)", color=accent, fontsize=10, fontweight="bold")

    ax_ratio.text(
        0.01,
        0.98,
        "Selected CH: CH1   RUN: LIVE   RESP: 48 ms",
        transform=ax_ratio.transAxes,
        ha="left",
        va="top",
        fontsize=8.5,
        color=accent,
        bbox={
            "facecolor": (1, 1, 1, 0.0),
            "edgecolor": accent,
            "linewidth": 0.8,
            "boxstyle": "round,pad=0.25",
        },
    )


def render_comparison(output_path: pathlib.Path) -> pathlib.Path:
    x, setpoint, actual, valve, threshold = build_demo_series()

    fig = plt.figure(figsize=(14.5, 9.0), dpi=150, facecolor="#E7EBF0")
    outer = fig.add_gridspec(2, 1, height_ratios=[1, 1], hspace=0.26)

    panels = []
    for row in range(2):
        panel = outer[row].subgridspec(2, 1, height_ratios=[4.2, 1.2], hspace=0.08)
        panels.append((fig.add_subplot(panel[0]), fig.add_subplot(panel[1])))

    draw_panel(*panels[0], "white", x, setpoint, actual, valve, threshold)
    draw_panel(*panels[1], "scope", x, setpoint, actual, valve, threshold)

    fig.suptitle(
        "SNET Graph Theme Study\nGraph must be visually independent from the control shell",
        x=0.06,
        y=0.98,
        ha="left",
        va="top",
        fontsize=16,
        fontweight="bold",
        color="#24313D",
    )

    fig.text(
        0.06,
        0.935,
        "Top: White Paper for XP Gray shell    Bottom: Scope Black for Bright Gray shell",
        ha="left",
        va="top",
        fontsize=10,
        color="#52606D",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate graph theme comparison preview.")
    parser.add_argument(
        "--export",
        type=pathlib.Path,
        default=pathlib.Path("artifacts/graph_theme_comparison.png"),
        help="Path to export PNG preview.",
    )
    return parser.parse_args(argv)


def _configure_matplotlib() -> None:
    cache_dir = pathlib.Path.cwd() / ".matplotlib-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    matplotlib.use("Agg")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_matplotlib()
    render_comparison(args.export.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
