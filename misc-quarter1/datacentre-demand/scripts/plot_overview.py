"""Data-centre electricity demand by region (stacked areas) and its share of total electricity demand (lines).

  build/series_<variant>.csv, build/world_cases.csv, data/outlooks.csv -> figures/datacentre_demand_<variant>.{png,pdf}
      (python scripts/plot_overview.py [variant ...])

Three stretches of years are told apart by the strength of the fill and by the line style: estimates of past years
(full, solid), the IEA's Base Case (lighter, dashed) and the extrapolation without a source (lightest, dotted).
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import patheffects
import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "scripts"))
import ftlook as ft

CFG = yaml.safe_load((HERE / "config.yaml").read_text())
REGIONS = list(CFG["regions"])
COLOUR = dict(zip(REGIONS, [ft.OXFORD, ft.CANDY, ft.TEAL, ft.MANDARIN, ft.SLATE]))
STRETCH = {"history": (1.0, "-"), "forecast": (0.72, (0, (4, 1.6))), "extrapolated": (0.42, (0, (1, 1.8)))}


def stretches(basis):
    """[(name, first year, last year)] of the three stretches, each starting where the one before ends."""
    name = basis.map({"history": "history", "iea_base": "forecast", "iea_base_world": "forecast"}).fillna("extrapolated")
    out = []
    for s in STRETCH:
        years = name.index[name == s]
        if len(years):
            out.append((s, max(years.min() - 1, name.index.min()), years.max()))
    return out


def spread(values, gap):
    """Move label positions apart so that neighbours are at least `gap` from each other; order is kept."""
    order = np.argsort(values)
    y = np.array(values, dtype=float)[order]
    for _ in range(200):
        moved = False
        for i in range(len(y) - 1):
            d = gap - (y[i + 1] - y[i])
            if d > 1e-9:
                y[i] -= d / 2
                y[i + 1] += d / 2
                moved = True
        if not moved:
            break
    out = np.empty_like(y)
    out[order] = y
    return out


def areas(ax, twh, parts):
    for name, a, b in parts:
        alpha, _ = STRETCH[name]
        seg = twh.loc[a:b]
        ax.stackplot(seg.index, seg[REGIONS].T.values, colors=[COLOUR[r] for r in REGIONS], alpha=alpha,
                     edgecolor=ft.PAPER, linewidth=0.7)
    ax.set_xlim(twh.index.min(), twh.index.max())
    # region names right of the stack, at the middle of their band, moved apart where the bands are thin
    top = twh[REGIONS].cumsum(axis=1).iloc[-1]
    mid = (top - twh[REGIONS].iloc[-1] / 2).values
    pos = spread(mid, 0.052 * ax.get_ylim()[1])
    x = twh.index.max()
    for r, y0, y1 in zip(REGIONS, mid, pos):
        ax.annotate(r, (x, y0), xytext=(x + 1.6, y1), textcoords="data", ha="left", va="center", fontsize=9,
                    color=ft.INK, annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=ft.SOFT, linewidth=0.5, shrinkA=1, shrinkB=0))


def stretch_marks(ax, parts, labels=True):
    """A hairline where a stretch begins and, in the left panel, its name above the plot."""
    names = {"forecast": "IEA Base Case", "extrapolated": "Extrapolated"}
    for name, a, b in parts[1:]:
        ax.axvline(a, color=ft.SOFT, linewidth=0.6, linestyle=(0, (2, 2)), zorder=3)
        if labels:
            ax.annotate(names[name], (a, 1), xycoords=("data", "axes fraction"), xytext=(4, -3),
                        textcoords="offset points", ha="left", va="top", fontsize=8, color=ft.SOFT)


def world_range(ax, cases, columns):
    """The span of the IEA's cases in their last year, as a whisker."""
    y = cases.index.max()
    lo, hi = cases.loc[y, columns].min(), cases.loc[y, columns].max()
    ax.plot([y, y], [lo, hi], color=ft.INK, linewidth=1.1, solid_capstyle="butt", zorder=5)
    for v in (lo, hi):
        ax.plot([y - 0.35, y + 0.35], [v, v], color=ft.INK, linewidth=1.1, solid_capstyle="butt", zorder=5)
    ax.annotate("IEA cases", (y, hi), xytext=(-6, 0), textcoords="offset points", ha="right", va="center",
                fontsize=8, color=ft.INK)


def outlook_marks(ax, outlooks):
    """World outlooks of other publishers: a hollow dot each, named on its left."""
    ax.scatter(outlooks.year, outlooks.twh, s=24, facecolor=ft.PAPER, edgecolor=ft.INK, linewidth=1.1, zorder=6,
               clip_on=False)
    for o in outlooks.itertuples():
        ax.annotate(o.label, (o.year, o.twh), xytext=(-6, 0), textcoords="offset points", ha="right", va="center",
                    fontsize=8, color=ft.INK, zorder=7,
                    path_effects=[patheffects.withStroke(linewidth=2.2, foreground=ft.PAPER)])


def lines(ax, share, parts, reference=None):
    series = REGIONS + ["World"]
    for r in series:
        colour, width = (ft.BLACK, 2.3) if r == "World" else (COLOUR[r], 1.9)
        for name, a, b in parts:
            _, style = STRETCH[name]
            seg = share[r].loc[a:b]
            ax.plot(seg.index, seg.values, color=colour, linewidth=width, linestyle=style,
                    dash_capstyle="round", zorder=4 if r == "World" else 3)
    ends = [("Global" if r == "World" else r, share[r].iloc[-1], r == "World") for r in series]
    if reference:
        years = sorted(reference)
        ax.plot(years, [100 * reference[y] for y in years], color=ft.SOFT, linewidth=1.2, zorder=2)
        ends.append(("24/7 buyers, model", 100 * reference[years[-1]], None))
    ax.set_xlim(share.index.min(), share.index.max())
    ax.set_ylim(0, None)
    # names and last values at the line ends, moved apart where the lines end close together
    x, span = share.index.max(), ax.get_ylim()[1]
    pos = spread([y for _, y, _ in ends], 0.056 * span)
    for (name, y0, world), y1 in zip(ends, pos):
        ax.annotate(f"{name}  {y0:.1f}", (x, y0), xytext=(x + 1.2, y1), textcoords="data", ha="left", va="center",
                    fontsize=9, color=ft.SOFT if world is None else ft.INK, fontweight="bold" if world else "regular",
                    annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=ft.SOFT, linewidth=0.5, shrinkA=0, shrinkB=2)
                    if abs(y1 - y0) > 0.01 * span else None)
        if world is not None:
            ax.plot(x, y0, "o", color=ft.BLACK if world else COLOUR[name], markersize=4.5, zorder=6, clip_on=False)


def figure(variant):
    s = pd.read_csv(HERE / f"build/series_{variant}.csv")
    twh = s.pivot(index="year", columns="region", values="twh")
    share = s.pivot(index="year", columns="region", values="share_pct")
    parts = stretches(s.drop_duplicates("year").set_index("year").basis)
    cases = pd.read_csv(HERE / "build/world_cases.csv", index_col="year")
    outlooks = pd.read_csv(HERE / "data/outlooks.csv", comment="#")
    outlooks = outlooks[(outlooks.region == "World") & (outlooks.show == 1)]

    fig = plt.figure(figsize=(11.2, 5.3), layout="none")
    grid = fig.add_gridspec(1, 2, width_ratios=[1.45, 1], left=0.05, right=0.855, top=0.815, bottom=0.115, wspace=0.42)
    a, b = fig.add_subplot(grid[0]), fig.add_subplot(grid[1])

    a.set_ylim(0, 1.06 * max(twh[REGIONS].sum(axis=1).max(), outlooks.twh.max()))
    areas(a, twh, parts)
    stretch_marks(a, parts)
    world_range(a, cases, ["base", "lift_off", "high_efficiency", "headwinds"])
    outlook_marks(a, outlooks)
    a.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")

    lines(b, share, parts, CFG.get("reference_share"))
    stretch_marks(b, parts, labels=False)

    for ax in (a, b):
        ax.set_xticks(range(int(twh.index.min()), int(twh.index.max()) + 1, 10))
        ax.set_xticks(range(int(twh.index.min()), int(twh.index.max()) + 1, 5), minor=True)
        ax.tick_params(axis="x", which="minor", length=2, width=0.6)

    ft.heading(fig, a, "Data centres' electricity use", "TWh a year, by region")
    ft.heading(fig, b, "Share of all electricity demand", "%")
    ft.source(fig, a, "Sources: IEA; Ember; BNEF; DNV; Rystad; Wood Mackenzie; own extrapolation after 2035")

    (HERE / "figures").mkdir(exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(HERE / f"figures/datacentre_demand_{variant}.{ext}")
    plt.close(fig)


def main():
    ft.use()
    for variant in sys.argv[1:] or list(CFG["variants"]):
        figure(variant)


if __name__ == "__main__":
    main()
