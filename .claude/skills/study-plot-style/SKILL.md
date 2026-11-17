---
name: study-plot-style
description: The DEFAULT style for every matplotlib chart and every chart drawn in an artifact in this repo (since 2026-11-10) - Iegor Riepin's study style from plotstyle/: Libre Franklin, no chart frame, quiet y grid, flat fills without outlines, Okabe-Ito colours. Use whenever you write or change plotting code here, unless the user asks for another look.
---

# Study plot style (repo default since 2026-11-10)

Every new or reworked chart in this repository uses this style unless the user asks otherwise: matplotlib
figures through `plotstyle/study.mplstyle` + `plotstyle/studystyle.py`, and charts drawn by hand in an artifact
(SVG / HTML) with the same tokens. It replaces the icon style (`icon-plot-style`, 2026-10-07), which stays in
`plotstyle/` for the figures already made with it and is used only on request. Older scripts are migrated when
they are touched. Reference look: the Catalyst workflow artifact (https://claude.ai/artifact/G3xtjLuXcmDwpXVtuhzhcf)
and `misc-quarter1/geothermal/figures/egs_model_JP.png`.

| File | Role |
|---|---|
| `plotstyle/study.mplstyle` | the rcParams, by Iegor Riepin (MIT): fonts, colours, grid, ticks, spines, Okabe-Ito cycle |
| `plotstyle/studystyle.py` | `use()`, colour constants, fixed colours of the recurring categories, small helpers |

## Use

```python
import sys
from pathlib import Path
import matplotlib.pyplot as plt
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st

st.use()
fig, ax = plt.subplots()
st.bars(ax, x, values, color=st.TECH["egs"])
ax.set_title("CAPEX, USD2024 per kW", loc="left")     # titles left, bold (the style), quantity and unit
st.legend_squares(ax, [(st.TECH["egs"], "with 24/7 CFE"), (st.NEUTRAL, "without")])
fig.savefig("out.pdf")
```

## The rules

1. **One sans typeface.** Libre Franklin, shipped in `plotstyle/fonts/` (static Regular, Italic, Medium, SemiBold,
   Bold, BoldItalic from github.com/impallari/Libre-Franklin, SIL OFL 1.1, licence in `OFL.txt`) and registered
   by `use()`, so it needs no system install; DejaVu Sans only covers missing glyphs. Text
   `#222222`, axis labels `#333333`, tick labels `#444444` (x) / `#666666` (y), faint notes `#aaaaaa`.
2. **No chart frame, quiet grid.** Only the bottom spine (0.8 pt, `#222222`); y grid `#dcdcdc` 0.5 pt; no tick marks.
3. **Flat fills, no outlines.** Bars, areas and legend squares carry no edge; adjoining blocks are separated by
   colour or a thin white seam. Hatching (`////`, 0.6 pt) marks a subset on top of a stack (e.g. the 24/7 CFE
   buyer's plants).
4. **Okabe-Ito colours**, with fixed meanings for what recurs (`st.TECH`, `st.MIX`): EGS vermillion `#D55E00`,
   Gen IV pink `#CC79A7`, iron-air orange `#E69F00`, SOFC green `#009E73`; coal `#222222`, gas and oil
   `#9e9e9e`, hydro `#0072B2`, wind `#56B4E9`, solar `#F0E442`, other `#d4d4d4`. A reference / "without" series
   is neutral grey `#c4c4c4` (`st.NEUTRAL`); the lighter half of a two-part bar is the same colour at 42 %
   opacity (`st.TINT`).
5. **Labels close to the data.** Values above bars and at line points in 7.5 pt; direct labels at line ends
   instead of a legend where there is room; legends are frameless with flat squares.
6. **Titles** sit top left, bold, and name quantity and unit ("Emissions, Mt CO2 per year"), so the y axis needs
   no label.
7. **Maps** keep their colormaps; land without data `#eeeeee`, coast in `#222222` at 0.5 pt, no ticks or frame
   (`st.map_axes`), and a slim horizontal colour bar whose label (quantity and unit) sits on top
   (`st.colorbar`). Every colour bar has a label.
8. **Layout.** The style turns constrained layout on; a figure laid out by hand needs `plt.figure(layout="none")` (`layout=None` still means "use the style").

## Helpers (`studystyle.py`)

| Helper | Draws |
|---|---|
| `bars(ax, x, h, color, labels=True)` | flat bars with value labels |
| `line(ax, x, y, color, label=None, values=False)` | line with round markers, end label, optional point values |
| `legend_squares(ax, [(colour, label[, alpha]), ...])` | frameless legend of flat squares |
| `map_axes(ax)` | strips grid, ticks and spines from a map panel |
| `colorbar(fig, mappable, cax, label, ticks=None)` | slim horizontal colour bar with the label on top |

Constants: `TEXT, LABEL, TICK, GRID, FAINT, NEUTRAL, LAND, OKABE_ITO` (and its eight names), `TECH`, `MIX`, `TINT`, `FUEL` (the existing fleet by fuel and carrier: coal, lignite, CCGT, OCGT, oil, nuclear, biomass,
geothermal, hydro, wind, solar; used by the model doc's Existing Fleet figures).

## In an artifact (SVG / HTML)

Same tokens: font stack `"Libre Franklin", "DejaVu Sans", "Helvetica Neue", Arial, sans-serif` (Google Fonts
link, weights 400 / 600 / 700), text `#222222`, labels `#444444`, ticks `#666666`, grid `#dcdcdc` at 0.6 px,
bottom spine `#222222` at 0.9 px, flat rects, the colours above. The page commits to a light, white-figure look.
