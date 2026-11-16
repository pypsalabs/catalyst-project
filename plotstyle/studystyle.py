"""Study plot style: the repo's default matplotlib look since 2026-11-10 (study.mplstyle by Iegor Riepin).

Editorial: one sans typeface (Libre Franklin, DejaVu Sans as fallback), no chart frame, a quiet y grid, flat
fills without outlines, Okabe-Ito colours. The same look as the Catalyst workflow artifact.

    import sys
    from pathlib import Path
    sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "plotstyle").is_dir()) / "plotstyle"))
    import studystyle as st
    st.use()
    fig, ax = plt.subplots()
    st.bars(ax, x, h, color=st.TECH["egs"])
    ax.set_title("CAPEX, USD2024 per kW", loc="left")
    st.legend_squares(ax, [(st.TECH["egs"], "EGS"), (st.NEUTRAL, "reference")])

The style switches constrained layout on; a figure laid out by hand needs plt.figure(layout="none").
"""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch

STYLE = Path(__file__).with_name("study.mplstyle")
FONTS = Path(__file__).with_name("fonts")   # Libre Franklin static .ttf files (SIL OFL 1.1, OFL.txt), registered by use()

TEXT, LABEL, TICK, GRID, FAINT = "#222222", "#333333", "#666666", "#dcdcdc", "#aaaaaa"
NEUTRAL, LAND = "#c4c4c4", "#eeeeee"       # reference / "without" bars; land without data on maps
BLACK, ORANGE, SKY, GREEN, YELLOW, BLUE, VERMILLION, PINK = OKABE_ITO = [
    "#000000", "#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7"]
# fixed colours of the project's recurring categories (as in the workflow artifact)
TECH = {"egs": VERMILLION, "nuclear-gen4": PINK, "iron-air": ORANGE, "sofc": GREEN, "sofc-cc": GREEN}
MIX = {"Nuclear": PINK, "Coal": TEXT, "Gas and oil": "#9e9e9e", "Hydro": BLUE, "Other": "#d4d4d4", "Wind": SKY,
       "Solar": YELLOW, "EGS": VERMILLION, "Other advanced": GREEN,
       "Storage": "#7E6BB0"}                # discharge of batteries, pumped hydro, iron-air; not Okabe-Ito
TINT = 0.42                                # opacity of the lighter half of a two-part bar (e.g. grid vs buyer)
# the existing fleet by fuel (model doc, Existing Fleet): MIX's colours where they exist, gas split into its two carriers
FUEL = {"coal": TEXT, "lignite": "#6e6e6e", "gas": "#9e9e9e", "CCGT": "#9e9e9e", "OCGT": "#cfcfcf", "oil": ORANGE,
        "nuclear": PINK, "biomass": GREEN, "geothermal": VERMILLION, "hydro": BLUE, "wind": SKY, "solar": YELLOW,
        "other": "#d4d4d4"}


def use():
    if FONTS.is_dir():
        for f in FONTS.glob("*.ttf"):
            font_manager.fontManager.addfont(str(f))
    plt.style.use(STYLE)


def bars(ax, x, height, color, width=0.62, labels=True, fmt="{:,.0f}", **kw):
    """Flat bars without outline; optional value labels above."""
    out = ax.bar(x, height, width=width, color=color, linewidth=0, zorder=2, **kw)
    if labels:
        for rect, v in zip(out, height):
            ax.annotate(fmt.format(v), (rect.get_x() + rect.get_width() / 2, rect.get_y() + rect.get_height()), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", fontsize=7.5, color=TEXT)
    return out


def line(ax, x, y, color, label=None, values=False, fmt="{:,.0f}", **kw):
    """Plain line with round markers; `label` is written after the last point, `values` labels every point."""
    out = ax.plot(x, y, color=color, lw=1.4, marker="o", ms=3.4, mew=0, zorder=3, **kw)
    if values:
        for xi, yi in zip(x, y):
            ax.annotate(fmt.format(yi), (xi, yi), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=7.5, color=color)
    if label:
        ax.annotate(label, (x[-1], y[-1]), xytext=(7, 0), textcoords="offset points", va="center", fontsize=7.5, color=color)
    return out


def legend_squares(ax, items, **kw):
    """Frameless legend of flat squares: items = [(colour, label), ...] or [(colour, label, alpha), ...]."""
    handles = [Patch(facecolor=it[0], edgecolor="none", alpha=it[2] if len(it) > 2 else 1, label=it[1]) for it in items]
    kw = dict(dict(loc="upper left", handlelength=0.9, handleheight=0.9, handletextpad=0.5, borderaxespad=0), **kw)
    return ax.legend(handles=handles, **kw)


def map_axes(ax):
    """A map panel: no grid, ticks or spines."""
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def colorbar(fig, mappable, cax, label, ticks=None, fmt=None):
    """Slim horizontal colour bar with its label (quantity and unit) on top."""
    cb = fig.colorbar(mappable, cax=cax, orientation="horizontal", ticks=ticks, format=fmt)
    cb.outline.set_edgecolor(TEXT)
    cb.outline.set_linewidth(0.5)
    cax.tick_params(length=0, pad=3, labelsize=7.5, labelcolor=TICK)
    cax.xaxis.set_label_position("top")
    cax.set_xlabel(label, fontsize=7.5, color=LABEL, labelpad=4)
    return cb
