"""Tufte-flavoured matplotlib helpers.

Goal: maximise data-ink ratio. Kill chartjunk (frames, gridlines, heavy
ticks, legends) and let the data carry itself with direct labels, range
frames, and a muted palette.

Principles applied (after Tufte, _The Visual Display of Quantitative Information_):
  - maximise data-ink; erase non-data ink
  - small multiples over single dense plots
  - direct labelling over legends
  - range-frame axes that extend only across the data, with the axis line
    itself encoding the data range
  - muted, perceptually-uniform palette
"""
from __future__ import annotations

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

# Force headless rendering so the module is safe in any environment.
mpl.use("Agg")

# --- Muted, Tufte-ish palette ----------------------------------------------
# Warm neutrals + a few restrained accents. No saturated primaries.
PALETTE = {
    "ink": "#1a1a1a",       # primary data colour
    "muted": "#6b6b6b",     # secondary / context series
    "accent": "#b45309",    # single accent (Tufte-amber)
    "accent2": "#1f6feb",   # cool accent
    "good": "#2f6f3e",      # positive
    "bad": "#9b2c2c",       # negative
    "grid": "#e8e4d9",      # barely-there grid, used sparingly
    "paper": "#fdfcf7",     # warm off-white canvas
}

# Cycle for multiple series, ordered by visual weight.
CYCLE = [PALETTE["ink"], PALETTE["accent2"], PALETTE["accent"],
         PALETTE["muted"], PALETTE["good"]]


def tufte_style() -> None:
    """Set global rcParams toward a minimal, high data-ink default."""
    plt.rcParams.update({
        "figure.facecolor": PALETTE["paper"],
        "axes.facecolor": PALETTE["paper"],
        "savefig.facecolor": PALETTE["paper"],
        "font.family": "serif",
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "axes.edgecolor": PALETTE["ink"],
        "axes.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "axes.prop_cycle": mpl.cycler(color=CYCLE),
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "xtick.color": PALETTE["ink"],
        "ytick.color": PALETTE["ink"],
        "lines.linewidth": 1.1,
        "lines.solid_capstyle": "round",
    })


def rangeframe(ax, axis: str = "y") -> None:
    """Tufte range-frame: crop the axis line to the data's own range.

    The spine itself becomes a mini summary of the data extent.
    """
    if axis == "y":
        lo, hi = ax.get_ylim()
        ax.spines["left"].set_bounds(lo, hi)
    else:
        lo, hi = ax.get_xlim()
        ax.spines["bottom"].set_bounds(lo, hi)


def range_ticks(ax, axis: str = "y", values=None) -> None:
    """Place ticks only at the data min / max (and optionally a midpoint)."""
    if values is None:
        values = []
    if axis == "y":
        ax.set_yticks(sorted(set(values)))
        ax.spines["left"].set_visible(True)
    else:
        ax.set_xticks(sorted(set(values)))
        ax.spines["bottom"].set_visible(True)


def thin_axes(ax) -> None:
    """Leave only faint, unobtrusive left + bottom spines; drop the rest."""
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(PALETTE["muted"])
        ax.spines[s].set_linewidth(0.5)
    ax.tick_params(length=2, width=0.5, colors=PALETTE["muted"])


def label_endpoints(ax, series: dict, x_end, dx: float = 0.02) -> None:
    """Direct-label the end of each line series; replaces a legend.

    `series` maps label -> last y-value.
    """
    for label, y in series.items():
        ax.annotate(label, (x_end, y), xytext=(dx, 0),
                    textcoords="offset fontsize",
                    va="center", ha="left", fontsize=8, color=PALETTE["ink"])
