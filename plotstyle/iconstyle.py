"""Icon plot style: matplotlib translation of the advanced-technology icons (doc/icons).

    import sys
    from pathlib import Path
    sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "plotstyle").is_dir()) / "plotstyle"))
    import iconstyle as ic
    ic.use()
    fig, ax = plt.subplots()
    ic.bars(ax, x, h, color=[ic.STEEL_L, ic.AMBER, ...])
    ic.legend_squares(ax, [(ic.STEEL_L, "mature"), (ic.AMBER, "advanced")])
    ic.ground(ax)              # last: it covers the bottoms of the bars

Every size is in points for the default 5.6 x 3.6 in figure; 1 px of the reference SVGs in reference/ = PX pt.
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager, transforms
from matplotlib.patches import Patch

STYLE = Path(__file__).with_name("icon.mplstyle")

# colours: the icons' ink and steel, plus their accents (blue and teal a little more saturated than in the
# icons, so the categorical set passes the chroma and colour-blind checks of the dataviz validator)
INK, MUTED = "#1f2a36", "#4a5866"
STEEL, STEEL_L, PALE = "#9aa9b7", "#c9d3dc", "#e8edf1"
BLUE, AMBER, TEAL, VIOLET, GOLD, RED = "#2563a6", "#e8772f", "#1f9a7a", "#7d5bb3", "#d9a92e", "#c0392b"
CATEGORICAL = [BLUE, AMBER, TEAL, VIOLET, GOLD, RED]   # fixed order, never cycled past six

# stroke weights (reference px -> pt)
PX = 0.72
OUTLINE = 1.9 * PX        # ground strip, frames, axis baseline
MARK = 1.6 * PX           # outlines of bars, segments, legend squares, end nodes
SEAM = 1.2 * PX           # boundaries between stacked areas
PIPE_CASE, PIPE_CORE = 5.6 * PX, 3.2 * PX   # cased data lines
NODE = 9.2 * PX           # end-node diameter
GROUND = 5 * PX           # ground strip thickness


# emphasis weight: IBM Plex Sans Medium where installed, else regular (the fallbacks have no 500 weight)
EMPH = "medium" if any(f.name == "IBM Plex Sans" for f in font_manager.fontManager.ttflist) else "normal"


def use():
    plt.style.use(STYLE)
    plt.rcParams["axes.titleweight"] = EMPH


def ground(ax, axis="x", at=0.0, overhang=0.012, zorder=4):
    """Steel-light strip with an ink outline just below the baseline (axis="x") or left of it (axis="y").

    Drawn as two stacked lines with projecting caps: the ink casing is OUTLINE wider than the core, so the
    outline shows on all four sides. Call it after the data so it covers the bottom edges of bars."""
    fig = ax.figure
    if axis == "x":
        tr = transforms.offset_copy(ax.get_yaxis_transform(), fig=fig, y=-GROUND / 2, units="points")
        xs, ys = [-overhang, 1 + overhang], [at, at]
        ax.spines["bottom"].set_visible(False)
        ax.tick_params(axis="x", length=0, pad=4 + GROUND)
    else:
        tr = transforms.offset_copy(ax.get_xaxis_transform(), fig=fig, x=-GROUND / 2, units="points")
        xs, ys = [at, at], [-overhang, 1 + overhang]
        ax.spines["left"].set_visible(False)
        ax.tick_params(axis="y", length=0, pad=4 + GROUND)
    for lw, col, z in ((GROUND + OUTLINE, INK, zorder), (GROUND - OUTLINE, STEEL_L, zorder + 0.01)):
        ax.plot(xs, ys, color=col, lw=lw, solid_capstyle="projecting", transform=tr, clip_on=False, zorder=z)


def bars(ax, x, height, color, width=0.62, labels=None, fmt="{:,.0f}", **kw):
    """Square bars with an ink outline; optional value labels above each bar."""
    out = ax.bar(x, height, width=width, color=color, edgecolor=INK, linewidth=MARK, zorder=2, **kw)
    if labels is None or labels:
        for rect, v in zip(out, height):
            ax.annotate(fmt.format(v), (rect.get_x() + rect.get_width() / 2, rect.get_height()), xytext=(0, 4),
                        textcoords="offset points", ha="center", va="bottom", fontsize=7.5, color=INK)
    return out


def stacked_barh(ax, y, parts, colors, totals=True, height=0.66, fmt="{:,.0f}"):
    """Horizontal stacked bars, segments outlined in ink; total at the end of each bar."""
    left = np.zeros(len(y))
    for vals, col in zip(parts, colors):
        vals = np.asarray(vals, dtype=float)
        ax.barh(y, vals, left=left, height=height, color=col, edgecolor=INK, linewidth=MARK, zorder=2)
        left += vals
    if totals:
        for yi, t in zip(y, left):
            ax.annotate(fmt.format(t), (t, yi), xytext=(5, 0), textcoords="offset points", va="center",
                        fontsize=7.5, color=INK)
    return left


def cased_line(ax, x, y, color, label=None, nodes=True, direct_label=True):
    """Data line drawn like the icons' pipes: an ink casing under a coloured core, ringed nodes at both ends."""
    kw = dict(solid_joinstyle="round", solid_capstyle="round")
    ax.plot(x, y, color=INK, lw=PIPE_CASE, zorder=3, **kw)
    ax.plot(x, y, color=color, lw=PIPE_CORE, zorder=3.1, **kw)
    if nodes:
        ax.plot([x[0], x[-1]], [y[0], y[-1]], "o", ms=NODE, mfc=color, mec=INK, mew=MARK, zorder=3.2, clip_on=False)
    if label and direct_label:
        ax.annotate(label, (x[-1], y[-1]), xytext=(7, 0), textcoords="offset points", va="center",
                    color=INK, fontweight=EMPH)


def stacked_area(ax, x, layers, colors, labels=None, values_fmt="{:,.0f}", gap_pt=21.6):
    """Stacked bands with thin ink seams, an ink top edge and labels at the right edge pushed apart so they
    never collide. Set the axis limits before calling (the labels are placed in display space)."""
    x = np.asarray(x, dtype=float)
    cum = np.vstack([np.zeros_like(x), np.cumsum(np.asarray(layers, dtype=float), axis=0)])
    for k, col in enumerate(colors):
        ax.fill_between(x, cum[k], cum[k + 1], color=col, lw=0, zorder=2)
        ax.plot(x, cum[k + 1], color=INK, lw=SEAM if k < len(colors) - 1 else OUTLINE, zorder=2.5,
                solid_joinstyle="miter")
    for xe in (x[0], x[-1]):
        ax.plot([xe, xe], [0, cum[-1][0 if xe == x[0] else -1]], color=INK, lw=OUTLINE, zorder=2.5,
                solid_capstyle="butt")
    if labels:
        to_disp, to_data = ax.transData, ax.transData.inverted()
        gap = gap_pt / 72 * ax.figure.dpi
        ys = []
        for k in range(len(colors)):
            yd = to_disp.transform((x[-1], (cum[k][-1] + cum[k + 1][-1]) / 2))[1]
            ys.append(max(yd, ys[-1] + gap) if ys else yd)      # display y grows upwards
        tag = [(-1, -6), (1, -6), (1, 6), (-1, 6), (-1, -6)]
        for k, (col, lab, yd) in enumerate(zip(colors, labels, ys)):
            yv = to_data.transform((0, yd))[1]
            ax.plot([x[-1]], [yv], marker=tag, ms=17, mfc=col, mec=INK, mew=SEAM, ls="none", clip_on=False,
                    transform=transforms.offset_copy(ax.transData, fig=ax.figure, x=10, units="points"))
            ax.annotate(lab, (x[-1], yv), xytext=(16, 2), textcoords="offset points", va="bottom",
                        color=INK, fontweight=EMPH, annotation_clip=False)
            ax.annotate(values_fmt.format(cum[k + 1][-1] - cum[k][-1]), (x[-1], yv), xytext=(16, -1),
                        textcoords="offset points", va="top", fontsize=7.2, color=MUTED, annotation_clip=False)
    return cum


def legend_squares(ax, items, loc="lower right", anchor=(1.0, 1.0), on_title_line=True, **kw):
    """Legend of ink-outlined squares, by default on the title line at the top right."""
    handles = [Patch(facecolor=c, edgecolor=INK, linewidth=MARK, label=l) for c, l in items]
    if on_title_line and "bbox_transform" not in kw:
        # lift the legend by the title pad so its baseline meets the title's
        kw["bbox_transform"] = transforms.offset_copy(ax.transAxes, fig=ax.figure, units="points",
                                                      y=plt.rcParams["axes.titlepad"] - 3.5)
    return ax.legend(handles=handles, loc=loc, bbox_to_anchor=anchor, ncol=len(items), **kw)
