"""A look close to the charts of the Financial Times, for this topic's figures only (asked for on 2026-11-18; the
repo default stays plotstyle/studystyle.py): a short black rule over a left-aligned title, a grey
subtitle that carries the unit, horizontal grid lines only, value labels on the right, series named at the data
instead of in a legend, and one short source line. The layout is the FT's, the colours of paper, ink and grid are not
(white background, neutral greys).

The typeface is the repo's Libre Franklin (plotstyle/fonts, SIL OFL 1.1); the FT's own faces are not free.
"""

from pathlib import Path

import matplotlib as mpl
from matplotlib import font_manager

PAPER = "#FFFFFF"       # white, as the repo's other figures (the FT's salmon paper was too recognisable)
INK = "#2B2B2B"
SOFT = "#666666"
GRID = "#E2E2E2"
BLACK = "#000000"

# the FT's chart colours, by name
OXFORD, CLARET, TEAL, CANDY, MANDARIN, WASABI, VELVET, SKY, SLATE = (
    "#0F5499", "#990F3D", "#0D7680", "#EB5E8D", "#FF8833", "#96CC28", "#593380", "#70DCE6", "#8A8A8A")

_FONTS = next(p for p in Path(__file__).resolve().parents if (p / "plotstyle").is_dir()) / "plotstyle" / "fonts"


_HAS_SEMIBOLD = False


def use():
    global _HAS_SEMIBOLD
    for f in sorted(_FONTS.glob("*.ttf")):
        font_manager.fontManager.addfont(str(f))
    _HAS_SEMIBOLD = any(f.name == "Libre Franklin SemiBold" for f in font_manager.fontManager.ttflist)
    mpl.rcParams.update({
        "font.family": ["Libre Franklin", "DejaVu Sans"],
        "font.size": 9.5,
        "text.color": INK,
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "savefig.facecolor": PAPER,
        "axes.edgecolor": SOFT,
        "axes.labelcolor": SOFT,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "xtick.color": SOFT,
        "ytick.color": SOFT,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "xtick.major.size": 3.5,
        "xtick.major.width": 0.8,
        "ytick.major.size": 0,
        "lines.linewidth": 2.0,
        "lines.solid_capstyle": "round",
        "pdf.fonttype": 42,
        "svg.fonttype": "none",
        "figure.dpi": 110,
        "savefig.dpi": 220,
    })


def right_axis(ax):
    """Value labels on the right, sitting on their grid line."""
    ax.yaxis.tick_right()
    ax.tick_params(axis="y", pad=4)
    for lab in ax.get_yticklabels():
        lab.set_horizontalalignment("left")


def heading(fig, ax, title, subtitle=None):
    """The FT heading over one panel: a short black rule, a title and a grey subtitle (the unit), all flush left
    with the panel. Distances in inches above the panel."""
    box = ax.get_position()
    h, w = fig.get_figheight(), fig.get_figwidth()
    y = box.y1 + 0.14 / h
    if subtitle:
        fig.text(box.x0, y, subtitle, color=SOFT, fontsize=9.5, ha="left", va="bottom")
        y += 0.23 / h
    fig.text(box.x0, y, title, color=INK, fontsize=12.5, fontfamily=["Libre Franklin SemiBold", "Libre Franklin"],
             fontweight="bold" if not _HAS_SEMIBOLD else "normal", ha="left", va="bottom")
    fig.add_artist(mpl.patches.Rectangle((box.x0, y + 0.31 / h), 0.42 / w, 0.045 / h, transform=fig.transFigure,
                                         color=BLACK, linewidth=0, clip_on=False))


def source(fig, ax, text):
    box = ax.get_position()
    fig.text(box.x0, 0.022, text, color=SOFT, fontsize=7.5, ha="left", va="bottom")
