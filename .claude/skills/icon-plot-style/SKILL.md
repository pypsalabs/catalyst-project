---
name: icon-plot-style
description: SUPERSEDED as the repo default on 2026-11-10 by study-plot-style. The icon plot style from plotstyle/ (ink outlines, steel greys, icon accent colours, ground strip), kept for figures already made with it. Use ONLY when the user asks for the icon look or when touching a figure that must stay in it.
---

# Icon plot style for matplotlib (superseded 2026-11-10)

**No longer the repo default: new and reworked charts use the study style (`study-plot-style` skill,
`plotstyle/studystyle.py`). What follows describes the icon style for the figures that keep it.**

Every new or reworked matplotlib chart in this repository uses this style unless the user asks otherwise
(decided 2026-10-07). Maps keep their own colormaps but take the fonts, ink, and outline weights from here.
Existing scripts are migrated when they are touched, or all at once on request.

The look comes from the six technology icons in
`config-pypsa-earth/technology-assumptions/doc/icons/` and was worked out as SVG plates on the Claude Design
canvas "Advanced technology icons" (https://claude.ai/artifact/4zeTUJok52JaALh8LTDQaG, artboard "Plots in the
icon style"). The code lives in `plotstyle/` at the repo root; `plotstyle/reference/*.svg` holds those plates,
the target look:

| File | Role |
|---|---|
| `icon.mplstyle` | rcParams: fonts, colours, grid, ticks, spines, legend, line and patch defaults |
| `iconstyle.py` | palette constants, stroke weights, and the drawing helpers below |
| `examples.py` | the four reference plots rebuilt with the helpers; `--compare` checks them against `reference/` |

## Use

```python
import sys
from pathlib import Path
import matplotlib.pyplot as plt
# works from any script in the repo, whatever the working directory
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic

ic.use()                                   # style sheet + emphasis weight
fig, ax = plt.subplots()                   # 5.6 x 3.6 in by default
ic.bars(ax, x, values, color=[ic.STEEL_L, ic.AMBER, ...])
ax.set_title("CAPEX, USD2024 per kW")      # the axis title doubles as the y label, top left
ic.legend_squares(ax, [(ic.STEEL_L, "mature"), (ic.AMBER, "advanced")])
ic.ground(ax)                              # LAST: it covers the bottoms of the bars
fig.savefig("out.pdf")
```

## The rules (what makes it the icon style)

1. **Ink outlines on every filled mark.** Ink `#1f2a36`. Bars and segments get `MARK` (1.15 pt), frames and
   baselines `OUTLINE` (1.37 pt), seams between stacked areas `SEAM` (0.86 pt).
2. **Square corners and miter joins.** Rounded corners looked comic; the only rounded joins are on data lines,
   so curves stay smooth. No highlights, sheens or gradients.
3. **Colour has one job each.** Steel-light `#c9d3dc` and steel `#9aa9b7` for the mature, neutral or "rest";
   the icon accents (`CATEGORICAL`: blue, amber, teal, violet, gold, red, in that fixed order) for what the plot
   is about. Amber is the default "advanced" highlight. Never more than six categories: fold the rest into a
   steel-light "Rest of ..." band.
4. **The ground strip is the baseline.** A 3.6 pt steel-light strip with an ink outline replaces the bottom
   spine (`ground(ax)`), or the left spine for horizontal bars (`ground(ax, axis="y")`).
5. **Data lines are pipes.** Ink casing 4.0 pt under a coloured 2.3 pt core, ink-ringed nodes at both ends,
   label at the end of the line (`cased_line`).
6. **Recessive scaffolding.** Pale `#e8edf1` grid on the value axis only, no y tick marks, muted `#4a5866`
   tick labels, no top/right/left spines.
7. **Labels in ink, never in the series colour.** Values above bars or after stacked bars; direct labels at
   line ends and at the right edge of stacked areas (pushed apart so they never collide); a legend of
   ink-outlined squares on the title line whenever there are two or more series.
8. **Type.** IBM Plex Sans (Helvetica / Arial / Liberation Sans fallback) at 7.9 pt; the title sits top left in
   ink, medium weight where Plex is installed.

## Helpers (`iconstyle.py`)

| Helper | Draws |
|---|---|
| `bars(ax, x, h, color, labels=True)` | outlined bars with value labels |
| `stacked_barh(ax, y, parts, colors)` | horizontal stacked bars, outlined segments, totals at the end |
| `cased_line(ax, x, y, color, label)` | pipe-style line, end nodes, direct label |
| `stacked_area(ax, x, layers, colors, labels)` | bands, seams, ink top edge and side edges, de-collided right-edge labels |
| `legend_squares(ax, [(colour, label), ...])` | outlined-square legend on the title line (`on_title_line=False` + `loc`/`anchor` to place it elsewhere) |
| `ground(ax, axis="x"/"y", at=0)` | the ground strip |

Constants: `INK, MUTED, STEEL, STEEL_L, PALE, BLUE, AMBER, TEAL, VIOLET, GOLD, RED, CATEGORICAL`, the stroke
weights above, and `PX = 0.72` (1 px of a 560 x 360 reference plate = 0.72 pt on a 5.6 x 3.6 in figure).

## Pitfalls

- Sizes are absolute points. For a much smaller figure (e.g. half text width, 3 in) the strokes are heavy
  relative to the plot: scale fonts and the stroke constants together rather than shrinking the saved image.
- `stacked_area` places its labels in display space: set `xlim`/`ylim` before calling it.
- `ground` must come after the data and after any change of limits along the strip.
- On a log axis call `ax.minorticks_off()`; minor ticks break the quiet scaffolding.
- Colour checks: the categorical set passes the dataviz validator (chroma, CVD separation, normal vision);
  amber and gold fall below 3:1 contrast on white, which the ink outlines and direct labels compensate for.
  Run `node <dataviz skill>/scripts/validate_palette.js "<hexes>" --mode light` before adding a colour.

## Test the translation

```bash
models/priam-myopic/.pixi/envs/default/bin/python plotstyle/examples.py --compare
```

Writes `plotstyle/build/{bars,lines,area,lcoe}.{png,pdf}` and `plotstyle/build/compare.png` (reference SVG rendered by
headless Chrome on the left, matplotlib on the right). Last check (2026-10-07): the four plots match in colour,
stroke weights, ground strip, outlines, labels and legend placement; remaining differences are
layout-only (tick-label padding, legend spacing), because matplotlib lays out text itself.
