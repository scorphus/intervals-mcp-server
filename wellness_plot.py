#!/usr/bin/env python3
"""Plot wellness data from Intervals.icu.

Generates a multi-panel chart showing HRV, RHR, Sleep Score, Sleep Hours,
and Training Load metrics with 7-day moving averages and baseline ranges.

Usage:
    uv run python wellness_plot.py                  # Default 42 days
    uv run python wellness_plot.py -d 28            # Last 28 days
    uv run python wellness_plot.py --dark           # Dark mode
    uv run python wellness_plot.py --pdf            # PDF output
    uv run python wellness_plot.py -d 90 --dark -o wellness.pdf

Environment variables (via .env):
    API_KEY: Intervals.icu API key
    ATHLETE_ID: Intervals.icu athlete ID (e.g., i12345)
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from dotenv import load_dotenv
from scipy.interpolate import make_interp_spline

if TYPE_CHECKING:
    from matplotlib.axes import Axes

load_dotenv()

API_KEY = os.getenv("API_KEY", "")
ATHLETE_ID = os.getenv("ATHLETE_ID", "")
BASE_URL = "https://intervals.icu/api/v1"

# Chart colors
COLOR_HRV = "#2E86AB"
COLOR_RHR = "#A23B72"
COLOR_SLEEP_SCORE = "#F18F01"
COLOR_SLEEP_HOURS = "#6A994E"
COLOR_DAILY_LOAD = "#6A994E"
COLOR_CTL = "#2E86AB"
COLOR_ATL = "#E63946"
COLOR_TSB = "#9B5DE5"


def fetch_wellness_data(days: int) -> list[dict]:
    """Fetch wellness data from Intervals.icu API.

    Args:
        days: Number of days to fetch (looking back from today)

    Returns:
        List of wellness records
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    response = httpx.get(
        f"{BASE_URL}/athlete/{ATHLETE_ID}/wellness",
        params={"oldest": start_date, "newest": end_date},
        auth=("API_KEY", API_KEY),
        timeout=30,
    )

    if response.status_code != 200:
        print(f"Error fetching wellness data: {response.status_code}", file=sys.stderr)
        print(response.text, file=sys.stderr)
        sys.exit(1)

    return response.json()


def plot_wellness(
    wellness_data: list[dict], output_file: str, num_days: int, dark_mode: bool = False
) -> None:
    """Generate wellness plot from data.

    Args:
        wellness_data: List of wellness records from API (includes warmup days)
        output_file: Path to save the plot
        num_days: Number of days to actually plot (excluding warmup)
        dark_mode: Whether to use dark mode colors
    """
    # Colors that adapt to theme
    baseline_fill_color = "#444444" if dark_mode else "lightgray"
    baseline_line_color = "#888888" if dark_mode else "gray"
    text_color = "#AAAAAA" if dark_mode else "black"
    spine_color = "#AAAAAA" if dark_mode else "black"

    if not wellness_data:
        print("No wellness data to plot", file=sys.stderr)
        sys.exit(1)

    # Parse all data (including warmup days for MA calculation)
    dates_full = []
    hrv_full = []
    rhr_full = []
    sleep_full = []
    sleep_hours_full = []
    loads_full = []
    ctl_full = []
    atl_full = []

    for day in wellness_data:
        dates_full.append(datetime.strptime(day["id"], "%Y-%m-%d"))
        hrv_full.append(day.get("hrv"))
        rhr_full.append(day.get("restingHR"))
        sleep_full.append(day.get("sleepScore"))
        sleep_secs = day.get("sleepSecs")
        sleep_hours_full.append(sleep_secs / 3600 if sleep_secs else None)
        loads_full.append(day.get("ctlLoad") or 0)
        ctl_full.append(day.get("ctl"))
        atl_full.append(day.get("atl"))

    # Slice to get only the plot period (last num_days)
    warmup = len(dates_full) - num_days
    dates = dates_full[warmup:]
    hrv_values = hrv_full[warmup:]
    rhr_values = rhr_full[warmup:]
    sleep_scores = sleep_full[warmup:]
    sleep_hours = sleep_hours_full[warmup:]
    loads = loads_full[warmup:]
    ctl_values = ctl_full[warmup:]
    atl_values = atl_full[warmup:]

    # Calculate date range for title
    date_start = dates[0].strftime("%b %d")
    date_end = dates[-1].strftime("%b %d, %Y")

    def moving_average_std(
        values: list[float | None], window: int = 7
    ) -> tuple[list[float | None], list[float | None]]:
        """Calculate moving average and standard deviation."""
        ma: list[float | None] = []
        std: list[float | None] = []
        for i in range(len(values)):
            start = max(0, i - window + 1)
            window_vals = [v for v in values[start : i + 1] if v is not None]
            if window_vals:
                mean = sum(window_vals) / len(window_vals)
                ma.append(mean)
                if len(window_vals) > 1:
                    variance = sum((x - mean) ** 2 for x in window_vals) / len(window_vals)
                    std.append(variance**0.5)
                else:
                    std.append(0)
            else:
                ma.append(None)
                std.append(None)
        return ma, std

    def baseline_range(
        values: list[float | None], window: int = 28
    ) -> tuple[list[float | None], list[float | None]]:
        """Calculate baseline range (28-day MA with std)."""
        return moving_average_std(values, window)

    def style_legend(ax: "Axes", loc: str = "lower left") -> None:
        """Apply consistent styling to legend."""
        leg = ax.legend(loc=loc, framealpha=0.5, fontsize="small", handlelength=1.5)
        for text in leg.get_texts():
            text.set_alpha(0.5)
        for handle in leg.legend_handles:
            if handle is not None:
                handle.set_alpha(0.5)

    def setup_axis(
        ax: "Axes", ylabel: str, tick_interval: float, legend_loc: str = "lower left"
    ) -> None:
        """Configure axis with common settings."""
        ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.yaxis.set_major_locator(plt.MultipleLocator(tick_interval))
        style_legend(ax, loc=legend_loc)
        ax.tick_params(axis="y", right=True, labelright=True)

    def plot_metric(
        ax: "Axes",
        values: list[float | None],
        ma_full: list[float | None],
        std_full: list[float | None],
        color: str,
        point_zorder: int = 2,
        use_bars: bool = False,
    ) -> None:
        """Plot metric data points and smooth MA curve."""
        clean = [(d, v) for d, v in zip(dates, values, strict=False) if v is not None]
        if clean:
            d, v = zip(*clean, strict=False)
            if use_bars:
                ax.bar(d, v, width=0.8, color=color, alpha=0.3, zorder=point_zorder)
            else:
                ax.plot(
                    d,
                    v,
                    marker="o",
                    linewidth=1,
                    markersize=4,
                    color=color,
                    alpha=0.375,
                    zorder=point_zorder,
                )
        ma, std = ma_full[warmup:], std_full[warmup:]
        smooth_d, smooth_v, lower, upper = smooth_curve(dates, ma, std)
        if (
            smooth_d is not None
            and smooth_v is not None
            and lower is not None
            and upper is not None
        ):
            ax.fill_between(smooth_d, lower, upper, color=color, alpha=0.2, zorder=point_zorder + 1)
            ax.plot(
                smooth_d,
                smooth_v,
                linewidth=2,
                color=color,
                label="7-day MA",
                zorder=point_zorder + 2,
            )

    def plot_baseline(
        ax: "Axes",
        bl_ma_full: list[float | None],
        bl_std_full: list[float | None],
        fmt: str = ".0f",
        show_range: bool = True,
        line_color: str | None = None,
    ) -> None:
        """Plot baseline range and line on axis."""
        bl_ma, bl_std = bl_ma_full[warmup:], bl_std_full[warmup:]
        bl_clean = [
            (d, m, s)
            for d, m, s in zip(dates, bl_ma, bl_std, strict=False)
            if m is not None and s is not None
        ]
        if not bl_clean:
            return
        bd, bm, bs = zip(*bl_clean, strict=False)
        if show_range:
            bl_lower = [m - s for m, s in zip(bm, bs, strict=False)]
            bl_upper = [m + s for m, s in zip(bm, bs, strict=False)]
            ax.fill_between(
                bd,
                bl_lower,
                bl_upper,
                color=baseline_fill_color,
                alpha=0.5,
                label="Baseline range",
                zorder=1,
            )
        # Baseline line: 7-day MA of the 28-day MA
        bl_ma_7d, _ = moving_average_std(list(bm))
        bl_line_clean = [(d, m) for d, m in zip(bd, bl_ma_7d, strict=False) if m is not None]
        if bl_line_clean:
            bld, blm = zip(*bl_line_clean, strict=False)
            color = line_color or baseline_line_color
            ax.plot(
                bld,
                blm,
                color=color,
                linestyle="--",
                alpha=0.75,
                label=f"Baseline ({blm[-1]:{fmt}})",
                zorder=0,
            )

    def smooth_curve(
        date_list: list[datetime],
        ma_values: list[float | None],
        std_values: list[float | None],
    ) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None, np.ndarray | None]:
        """Create smooth spline through MA points with confidence band."""
        clean = [
            (d, m, s)
            for d, m, s in zip(date_list, ma_values, std_values, strict=False)
            if m is not None and s is not None
        ]
        if len(clean) < 4:
            return None, None, None, None
        d, m, s = zip(*clean, strict=False)
        x = np.array([mdates.date2num(dt) for dt in d])
        y = np.array(m)
        y_std = np.array(s)
        x_smooth = np.linspace(x.min(), x.max(), 200)
        spline_ma = make_interp_spline(x, y, k=3)
        spline_std = make_interp_spline(x, y_std, k=3)
        y_smooth = spline_ma(x_smooth)
        std_smooth = spline_std(x_smooth)
        return x_smooth, y_smooth, y_smooth - std_smooth, y_smooth + std_smooth

    # Create figure with 5 subplots
    fig, axes = plt.subplots(5, 1, figsize=(14, 14), sharex=True)
    fig.suptitle(
        f"{num_days}-Day Wellness & Training Load ({date_start} - {date_end})",
        fontsize=16,
        fontweight="bold",
        color=text_color,
    )

    # Plot 1: HRV
    hrv_ma_full, hrv_std_full = moving_average_std(hrv_full)
    hrv_bl_ma, hrv_bl_std = baseline_range(hrv_full)
    plot_baseline(axes[0], hrv_bl_ma, hrv_bl_std)
    plot_metric(axes[0], hrv_values, hrv_ma_full, hrv_std_full, COLOR_HRV)
    setup_axis(axes[0], "HRV (ms)", 2.5)

    # Plot 2: RHR
    rhr_ma_full, rhr_std_full = moving_average_std(rhr_full)
    rhr_bl_ma, rhr_bl_std = baseline_range(rhr_full)
    plot_baseline(axes[1], rhr_bl_ma, rhr_bl_std)
    plot_metric(axes[1], rhr_values, rhr_ma_full, rhr_std_full, COLOR_RHR)
    setup_axis(axes[1], "RHR (bpm)", 1)

    # Plot 3: Sleep Score
    sleep_bl_ma, sleep_bl_std = baseline_range(sleep_full)
    plot_baseline(
        axes[2], sleep_bl_ma, sleep_bl_std, show_range=False, line_color=COLOR_SLEEP_SCORE
    )
    sleep_ma_full, sleep_std_full = moving_average_std(sleep_full)
    plot_metric(axes[2], sleep_scores, sleep_ma_full, sleep_std_full, COLOR_SLEEP_SCORE)
    axes[2].set_ylim(60, 100)
    setup_axis(axes[2], "Sleep Score", 5)

    # Plot 4: Sleep Hours
    hours_bl_ma, hours_bl_std = baseline_range(sleep_hours_full)
    plot_baseline(
        axes[3],
        hours_bl_ma,
        hours_bl_std,
        fmt=".1f",
        show_range=False,
        line_color=COLOR_SLEEP_HOURS,
    )
    hours_ma_full, hours_std_full = moving_average_std(sleep_hours_full)
    plot_metric(
        axes[3],
        sleep_hours,
        hours_ma_full,
        hours_std_full,
        COLOR_SLEEP_HOURS,
        point_zorder=1,
        use_bars=True,
    )
    axes[3].set_ylim(0, 10)
    setup_axis(axes[3], "Sleep Hours", 1)

    # Plot 5: Training Load & Fitness
    # TSB (Form) on secondary axis - plot first (behind)
    ax3_tsb = axes[4].twinx()
    tsb_values = [
        (c - a) if c is not None and a is not None else None
        for c, a in zip(ctl_values, atl_values, strict=False)
    ]
    tsb_clean = [(d, v) for d, v in zip(dates, tsb_values, strict=False) if v is not None]
    if tsb_clean:
        d, v = zip(*tsb_clean, strict=False)
        ax3_tsb.plot(d, v, linewidth=2, color=COLOR_TSB, linestyle="--", label="TSB", zorder=1)
        ax3_tsb.axhline(y=0, color=COLOR_TSB, linestyle=":", alpha=0.5, zorder=0)
    ax3_tsb.set_ylabel("TSB", fontsize=12, fontweight="bold")
    style_legend(ax3_tsb, loc="upper right")

    # Daily Load bars (in front)
    axes[4].bar(
        dates, loads, width=0.8, color=COLOR_DAILY_LOAD, alpha=0.5, label="Daily Load", zorder=3
    )

    # CTL (Fitness) and ATL (Fatigue)
    ctl_clean = [(d, v) for d, v in zip(dates, ctl_values, strict=False) if v is not None]
    atl_clean = [(d, v) for d, v in zip(dates, atl_values, strict=False) if v is not None]
    if ctl_clean:
        d, v = zip(*ctl_clean, strict=False)
        axes[4].plot(d, v, linewidth=2, color=COLOR_CTL, label="CTL", zorder=4)
    if atl_clean:
        d, v = zip(*atl_clean, strict=False)
        axes[4].plot(d, v, linewidth=2, color=COLOR_ATL, label="ATL", zorder=4)

    # Calculate aligned axis limits based on data
    load_max = max(loads) if loads else 100
    tsb_vals = [v for v in tsb_values if v is not None]
    tsb_min = min(tsb_vals) if tsb_vals else -20
    tsb_max = max(tsb_vals) if tsb_vals else 40

    # Round load to nice interval (multiples of 15)
    load_upper = int(np.ceil(load_max / 15) * 15) + 15

    # Calculate TSB limits snugly around data
    # Add small padding (5 units on each side)
    tsb_lower = int(np.floor((tsb_min - 5) / 5) * 5)
    tsb_upper = int(np.ceil((tsb_max + 5) / 5) * 5)
    tsb_range = tsb_upper - tsb_lower

    # Pick a nice interval (5 or 10) that gives reasonable number of ticks
    if tsb_range <= 50:
        tsb_interval = 5
    elif tsb_range <= 100:
        tsb_interval = 10
    else:
        tsb_interval = 15

    # Adjust limits to be multiples of interval
    tsb_lower = int(np.floor(tsb_lower / tsb_interval) * tsb_interval)
    tsb_upper = int(np.ceil(tsb_upper / tsb_interval) * tsb_interval)

    axes[4].set_ylim(0, load_upper)
    axes[4].yaxis.set_major_locator(plt.MultipleLocator(15))
    ax3_tsb.set_ylim(tsb_lower, tsb_upper)
    ax3_tsb.yaxis.set_major_locator(plt.MultipleLocator(tsb_interval))

    axes[4].set_ylabel("Training Load", fontsize=12, fontweight="bold")
    axes[4].grid(True, alpha=0.3, axis="y")
    style_legend(axes[4], loc="upper left")
    axes[4].set_zorder(ax3_tsb.get_zorder() + 1)
    axes[4].patch.set_visible(False)

    axes[4].set_xlabel("Date", fontsize=12, fontweight="bold")

    # Format x-axis
    axes[4].xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    interval = max(1, num_days // 30)
    axes[4].xaxis.set_major_locator(mdates.DayLocator(interval=interval))

    # Remove margins on x-axis and apply text colors
    margin = timedelta(hours=12)
    for ax in axes:
        ax.set_xlim(dates[0] - margin, dates[-1] + margin)
        ax.tick_params(axis="x", labelsize=7, rotation=22.5, labelbottom=True, colors=text_color)
        ax.tick_params(axis="y", colors=text_color)
        ax.xaxis.label.set_color(text_color)
        ax.yaxis.label.set_color(text_color)
        plt.setp(ax.get_xticklabels(), alpha=0.75)
        for spine in ax.spines.values():
            spine.set_color(spine_color)
    ax3_tsb.tick_params(axis="y", colors=text_color)
    ax3_tsb.yaxis.label.set_color(text_color)
    for spine in ax3_tsb.spines.values():
        spine.set_color(spine_color)

    # Adjust layout
    plt.tight_layout()

    # Save plot
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    print(f"Plot saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Plot wellness data from Intervals.icu",
        epilog="""
Examples:
  # Last 42 days (default)
  %(prog)s

  # Last 7 days
  %(prog)s -d 7

  # Last 90 days with custom output
  %(prog)s -d 90 -o wellness_90days.png
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--days",
        type=int,
        default=42,
        help="Number of days to plot (default: 42)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output file (default: wellness_{days}days.png)",
    )
    parser.add_argument(
        "--dark",
        action="store_true",
        help="Use dark mode theme",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Output as PDF instead of PNG",
    )

    args = parser.parse_args()

    if args.dark:
        plt.style.use("dark_background")

    if not API_KEY or not ATHLETE_ID:
        print("Error: API_KEY and ATHLETE_ID must be set in .env file", file=sys.stderr)
        sys.exit(1)

    ext = "pdf" if args.pdf else "png"
    output_file = args.output or f"wellness_{args.days}days.{ext}"

    warmup = 28  # Extra days for baseline calculation
    print(f"Fetching {args.days} days of wellness data...", file=sys.stderr)
    wellness_data = fetch_wellness_data(args.days + warmup)
    print(f"Got {len(wellness_data)} records", file=sys.stderr)

    plot_wellness(wellness_data, output_file, args.days, args.dark)


if __name__ == "__main__":
    main()
