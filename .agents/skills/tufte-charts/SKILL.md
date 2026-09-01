---
name: tufte-charts
description: Make clean, Edward-Tufte-style data visualizations (charts, plots, figures, graphs) with matplotlib — maximise data-ink, erase chartjunk, use direct labels, range-frames, sparklines, slopegraphs, dot plots, and small multiples. Use when the user asks to create charts/plots/figures or wants minimal/honest/elegant data visualization. Ships a ready `tufte.py` style module and an isolated venv so no system Python is touched. Biases toward matplotlib for deterministic PNG/SVG output without a browser.
---

# tufte-charts — minimal-ink matplotlib charts

A reusable matplotlib style module + isolated venv that produces
Edward-Tufte-flavoured charts: high data-ink ratio, no chartjunk, direct
labelling, range-frame axes, muted palette. Designed for agents that need to
emit deterministic PNG/SVG figures without a browser or JS runtime.

Everything the skill needs lives in `<skill-dir>` (= `~/.agents/skills/tufte-charts`).

## Why this over Altair / Plotly / Plotnine

For an *agent* generating charts, matplotlib wins on ergonomics:
deterministic raster (PNG) / vector (SVG) output, no Vega renderer, no browser,
no JS event loop. Tufte's low-ink aesthetic maps directly onto the matplotlib
API (spines off, no grid, muted palette, direct labels). Altair outputs
Vega-Lite JSON that needs a renderer to produce an image — extra friction for
the same visual result.

## Environment (already set up — isolated, system Python untouched)

- venv: `<skill-dir>/.venv`  (Python 3.13, matplotlib + numpy + pandas)
- interpreter: `<skill-dir>/.venv/bin/python`
- The system `/usr/bin/python3` is never modified. Do **not** `pip install`
  into the system; always use the skill venv.

Verify quickly:
```bash
<skill-dir>/.venv/bin/python -c "import matplotlib, numpy, pandas; print('ok')"
```

## Tufte principles applied here (after *The Visual Display of Quantitative Information*)

1. **Maximise data-ink ratio.** Every drop of ink should encode data. Remove
   frames, gridlines, heavy tick marks, backgrounds.
2. **Erase non-data ink.** Drop top/right spines; thin or remove left/bottom.
3. **Direct labelling over legends.** Label series at their endpoint; let the
   reader read values without a legend lookup.
4. **Range-frame axes.** Crop the axis line to the data's own min/max so the
   spine itself summarises extent; put ticks only at the data extremes.
5. **Small multiples.** Prefer faceted panels with shared axes over one dense plot.
6. **Muted, perceptual palette.** One ink for the primary series, restrained
   accents, warm off-white paper. No saturated primaries.

## The `tufte.py` API

Import and activate once per script:
```python
import sys; sys.path.insert(0, "<skill-dir>")  # if running outside the skill dir
import tufte
from tufte import PALETTE, thin_axes, rangeframe, range_ticks, label_endpoints
tufte.tufte_style()          # global rcParams: serif, spines off, no grid, paper bg
mpl.use("Agg")               # already forced inside tufte.py -> headless safe
```

| Helper | Effect |
|---|---|
| `tufte_style()` | set global minimal rcParams (call once at top of script) |
| `PALETTE` | dict: `ink, muted, accent, accent2, good, bad, grid, paper` |
| `thin_axes(ax)` | drop top/right spines, fade left/bottom, shrink ticks |
| `rangeframe(ax, axis="y"\|"x")` | crop the spine to the data range |
| `range_ticks(ax, axis, values=...)` | ticks only at data min/max (+ optional) |
| `label_endpoints(ax, {label: y}, x_end)` | direct-label line ends — kills the legend |

## Chart-type recipes (canonical Tufte forms)

See `examples/generate.py` for full, runnable implementations of all six:

1. **Range-framed line chart** — multi-series, y cropped to data, ticks at
   min/max, direct endpoint labels. `rangeframe(ax,"y")` + `label_endpoints(...)`.
2. **Deviation bar chart** — thin horizontal bars from a zero baseline, values
   at bar tips, no axis box. `thin_axes(ax)` + hide all spines/ticks.
3. **Sparkline row** — word-sized, data-dense, min/max marked. Tiny figure,
   no axes, inline as text.
4. **Slopegraph** — two-timepoint comparison (the table-graphic). Label both
   endpoints; values hug the line, names form outer columns.
5. **Dot plot** — dots over bars for ranked quantities (Cleveland/Tufte).
6. **Small multiples** — faceted, shared axes.

## Minimal end-to-end example

```python
import numpy as np, matplotlib.pyplot as plt
import tufte
from tufte import PALETTE, thin_axes, rangeframe, label_endpoints
tufte.tufte_style()

x = np.arange(2015, 2025)
y = 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0.05, 0.12, x.size)))

fig, ax = plt.subplots(figsize=(6.4, 3.6))
ax.plot(x, y, color=PALETTE["ink"], marker="o", ms=3, mec="none")
lo, hi = y.min(), y.max()
ax.set_ylim(lo - (hi-lo)*0.05, hi + (hi-lo)*0.18)
rangeframe(ax, "y"); ax.set_yticks([round(lo), round(hi)])
thin_axes(ax); ax.spines["left"].set_color(PALETTE["ink"])
label_endpoints(ax, {"Series": y[-1]}, x[-1])
fig.tight_layout(); fig.savefig("out.png", dpi=150)
```

Run any script with the skill interpreter:
```bash
<skill-dir>/.venv/bin/python examples/generate.py
```

## Output checklist (apply before declaring a chart done)

- [ ] top/right spines removed (`thin_axes` or rcParams)
- [ ] no gridlines unless they carry information
- [ ] series direct-labelled — no legend unless ≥ 4 series
- [ ] axis cropped to data range where it aids reading
- [ ] muted palette; one accent reserved for the story
- [ ] values annotated where the reader needs a precise read
