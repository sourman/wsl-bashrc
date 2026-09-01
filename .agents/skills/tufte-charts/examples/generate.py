"""Generate sample Edward-Tufte-style charts.

Run:  .venv/bin/python generate.py
Outputs PNGs into out/ alongside a contact sheet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# tufte.py lives at the skill root (parent of this examples/ dir).
SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))
import tufte
from tufte import PALETTE, thin_axes, rangeframe, label_endpoints

tufte.tufte_style()

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)

rng = np.random.default_rng(7)


# --------------------------------------------------------------------------- #
# 1. Range-framed line chart with direct labels  (the Tufte workhorse)
# --------------------------------------------------------------------------- #
def line_chart_rangeframe() -> Path:
    years = np.arange(2014, 2025)
    g = 100 * np.exp(np.cumsum(rng.normal(0.06, 0.12, years.size)))
    g = g / g[0] * 100
    h = 100 * np.exp(np.cumsum(rng.normal(0.03, 0.10, years.size)))
    h = h / h[0] * 100

    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.plot(years, g, color=PALETTE["ink"], marker="o", ms=3, mec="none", zorder=3)
    ax.plot(years, h, color=PALETTE["accent2"], marker="o", ms=3, mec="none", zorder=3)

    # Range-frame the y-axis to the pooled data extent.
    lo, hi = min(g.min(), h.min()), max(g.max(), h.max())
    ax.set_ylim(lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.18)
    rangeframe(ax, "y")
    ax.set_yticks([round(lo), round(hi)])
    ax.set_xticks(years[::2])

    thin_axes(ax)
    ax.spines["left"].set_color(PALETTE["ink"])
    ax.spines["left"].set_linewidth(0.8)

    # Direct labels at the right end — no legend.
    label_endpoints(ax, {"Region A": g[-1], "Region B": h[-1]}, years[-1])
    ax.set_title("Indexed output, 2014 = 100", loc="left", color=PALETTE["ink"])
    ax.set_ylabel("")
    ax.text(0, 1.04, "REGIONAL OUTPUT", transform=ax.transAxes,
            fontsize=8, color=PALETTE["muted"])
    fig.tight_layout()
    p = OUT / "01_line_rangeframe.png"
    fig.savefig(p, dpi=150); plt.close(fig)
    return p


# --------------------------------------------------------------------------- #
# 2. Deviation bar chart  (Tufte: thin bars from a baseline, no frame)
# --------------------------------------------------------------------------- #
def deviation_bars() -> Path:
    cats = ["Corn", "Wheat", "Rice", "Soy", "Oats", "Barley", "Rye", "Millet"]
    vals = np.array([+18, +12, +5, -4, -9, -15, -22, -28], dtype=float)

    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    colors = [PALETTE["good"] if v >= 0 else PALETTE["bad"] for v in vals]
    ax.barh(cats, vals, color=colors, height=0.55, zorder=3)
    ax.axvline(0, color=PALETTE["ink"], lw=0.8, zorder=2)

    # Value labels at bar tips.
    for y, v in zip(cats, vals):
        ax.text(v + (1.5 if v >= 0 else -1.5), y,
                f"{v:+.0f}", va="center",
                ha="left" if v >= 0 else "right", fontsize=8,
                color=PALETTE["ink"])
    thin_axes(ax)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(left=False, bottom=False)
    ax.set_xticks([])
    ax.set_xlim(-38, 30)
    ax.invert_yaxis()
    ax.set_title("Yield change vs. 10-yr mean (%)", loc="left")
    ax.text(0, 1.05, "CEREAL YIELDS", transform=ax.transAxes,
            fontsize=8, color=PALETTE["muted"])
    fig.tight_layout()
    p = OUT / "02_deviation_bars.png"
    fig.savefig(p, dpi=150); plt.close(fig)
    return p


# --------------------------------------------------------------------------- #
# 3. Sparklines  (word-sized, data-dense — the small-multiple sparkline grid)
# --------------------------------------------------------------------------- #
def sparklines() -> Path:
    cols = ["A", "B", "C", "D"]
    data = {c: np.cumsum(rng.normal(0, 1, 60)) for c in cols}
    fig, axes = plt.subplots(1, len(cols), figsize=(6.4, 1.4))
    for ax, (c, y) in zip(axes, data.items()):
        ax.plot(y, color=PALETTE["ink"], lw=1.0)
        ax.scatter([y.argmin()], [y.min()], color=PALETTE["bad"], s=6, zorder=3)
        ax.scatter([y.argmax()], [y.max()], color=PALETTE["good"], s=6, zorder=3)
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(f"{c}  {y[-1]:.1f}", fontsize=8, loc="left",
                     color=PALETTE["muted"])
    fig.tight_layout(pad=0.4)
    p = OUT / "03_sparklines.png"
    fig.savefig(p, dpi=150); plt.close(fig)
    return p


# --------------------------------------------------------------------------- #
# 4. Slopegraph  (two-timepoint comparison — Tufte's table-graphic)
# --------------------------------------------------------------------------- #
def slopegraph() -> Path:
    firms = ["Atlas", "Beacon", "Cobalt", "Delta", "Eden"]
    y2020 = [42, 28, 35, 19, 51]
    y2024 = [38, 44, 47, 31, 40]

    fig, ax = plt.subplots(figsize=(4.8, 4.2))
    x = [0, 1]
    for name, a, b in zip(firms, y2020, y2024):
        col = PALETTE["good"] if b >= a else PALETTE["bad"]
        ax.plot(x, [a, b], color=PALETTE["muted"], lw=1.0, zorder=2)
        ax.plot(x, [a, b], color=col, lw=1.0, alpha=0.0)  # reserved
        # Direct label both endpoints.
        ax.text(-0.02, a, f"{name}  {a}", ha="right", va="center", fontsize=8)
        ax.text(1.02, b, f"{b}  {name}", ha="left", va="center",
                fontsize=8, color=col)
    ax.text(0, max(y2020 + y2024) + 6, "2020", ha="center", fontsize=10,
            color=PALETTE["ink"])
    ax.text(1, max(y2020 + y2024) + 6, "2024", ha="center", fontsize=10,
            color=PALETTE["ink"])
    ax.set_xlim(-0.4, 1.4)
    ax.set_ylim(10, max(y2020 + y2024) + 12)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("Market share (%)", loc="left")
    fig.tight_layout()
    p = OUT / "04_slopegraph.png"
    fig.savefig(p, dpi=150); plt.close(fig)
    return p


# --------------------------------------------------------------------------- #
# 5. Dot plot  (Cleveland / Tufte: dots > bars for ranked quantities)
# --------------------------------------------------------------------------- #
def dot_plot() -> Path:
    cities = ["Lima", "Quito", "Bogotá", "Cusco", "La Paz", "Sucre"]
    elev = [154, 2850, 2640, 3400, 3640, 4090][::-1]

    fig, ax = plt.subplots(figsize=(6.0, 3.2))
    ax.hlines(cities, 0, elev, color=PALETTE["grid"], lw=1.4, zorder=1)
    ax.scatter(elev, cities, color=PALETTE["ink"], s=34, zorder=3)
    for y, v in zip(cities, elev):
        ax.text(v + 90, y, f"{v:,} m", va="center", fontsize=8)
    thin_axes(ax)
    ax.spines["left"].set_visible(False)
    ax.tick_params(left=False)
    ax.set_xlim(0, 4900)
    ax.set_title("Capital-city elevation", loc="left")
    ax.text(0, 1.05, "ANDEAN CAPITALS", transform=ax.transAxes,
            fontsize=8, color=PALETTE["muted"])
    fig.tight_layout()
    p = OUT / "05_dot_plot.png"
    fig.savefig(p, dpi=150); plt.close(fig)
    return p


# --------------------------------------------------------------------------- #
# 6. Small multiples  (faceted, shared axes — Tufte's signature device)
# --------------------------------------------------------------------------- #
def small_multiples() -> Path:
    weeks = np.arange(12)
    prods = ["Widget", "Gadget", "Gizmo", "Doohickey"]
    base = rng.normal(0, 1, (len(prods), weeks.size)).cumsum(1)

    fig, axes = plt.subplots(2, 2, figsize=(6.4, 4.0), sharex=True, sharey=True)
    for ax, name, row in zip(axes.ravel(), prods, base):
        ax.plot(weeks, row, color=PALETTE["ink"], marker="o", ms=2.5, mec="none")
        thin_axes(ax)
        ax.set_title(name, loc="left", fontsize=9, color=PALETTE["muted"])
        ax.set_ylim(base.min() - 1, base.max() + 1)
    fig.suptitle("Weekly demand, by product (z-scored)", x=0.02, ha="left",
                 fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    p = OUT / "06_small_multiples.png"
    fig.savefig(p, dpi=150); plt.close(fig)
    return p


if __name__ == "__main__":
    produced = [
        line_chart_rangeframe(),
        deviation_bars(),
        sparklines(),
        slopegraph(),
        dot_plot(),
        small_multiples(),
    ]
    for p in produced:
        print(f"wrote {p}")
