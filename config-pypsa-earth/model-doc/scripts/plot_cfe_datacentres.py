"""Data centres' electricity use by region and its share of electricity demand, 2020-2050 (Demand for 24/7 CFE).

Left: stacked areas per region; right: the same over the region's electricity demand, the world in black. Three stretches
of years: estimates of past years (full fill, solid line), the IEA's Base Case (lighter, dashed) and the extrapolation
without a source (lightest, dotted). Hollow dots: world outlooks of other publishers. Reads the series built in
misc-quarter1/datacentre-demand (build/series_<variant>.csv; data/outlooks.csv).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_cfe_datacentres.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

TOP = Path(__file__).resolve().parents[1]
TOPIC = TOP.parents[1] / "misc-quarter1/datacentre-demand"
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

COLOUR = {"United States": st.BLUE, "China": st.VERMILLION, "Europe": st.GREEN, "Asia excl. China": st.ORANGE,
          "Rest of world": "#9e9e9e"}
STRETCH = {"history": (1.0, "-"), "forecast": (0.7, (0, (4, 1.6))), "extrapolated": (0.4, (0, (1, 1.8)))}
NAMES = {"forecast": "IEA Base Case", "extrapolated": "extrapolated"}


def stretches(basis):
    """[(name, first year, last year)], each stretch starting where the one before ends."""
    name = basis.map({"history": "history", "iea_base": "forecast", "iea_base_world": "forecast"}).fillna("extrapolated")
    out = []
    for s in STRETCH:
        years = name.index[name == s]
        if len(years):
            out.append((s, max(years.min() - 1, name.index.min()), years.max()))
    return out


def spread(values, gap):
    """Label positions at least `gap` apart, order kept."""
    order = np.argsort(values)
    y = np.array(values, dtype=float)[order]
    for _ in range(300):
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


def end_labels(ax, x, items, gap, dx):
    """Names at the right end of lines: [(text, y, colour)], moved apart, joined to their line by a thin leader."""
    pos = spread([y for _, y, _ in items], gap * (ax.get_ylim()[1] - ax.get_ylim()[0]))
    for (text, y0, colour), y1 in zip(items, pos):
        ax.plot([x, x + 0.35 * dx, x + 0.8 * dx], [y0, y1, y1], color=st.FAINT, linewidth=0.5, clip_on=False)
        ax.text(x + dx, y1, text, ha="left", va="center", fontsize=7, color=colour, clip_on=False)


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--series", default=TOPIC / "build/series_trend.csv")
    p.add_argument("--outlooks", default=TOPIC / "data/outlooks.csv")
    p.add_argument("--out", default=TOP / "build/figures/cfe_datacentres.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--series", snakemake.input.series, "--outlooks", snakemake.input.outlooks,
                          "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    s = pd.read_csv(a.series)
    twh = s.pivot(index="year", columns="region", values="twh")
    share = s.pivot(index="year", columns="region", values="share_pct")
    parts = stretches(s.drop_duplicates("year").set_index("year").basis)
    o = pd.read_csv(a.outlooks, comment="#")
    o = o[(o.region == "World") & (o.show == 1)]
    regions = list(COLOUR)
    x0, x1 = twh.index.min(), twh.index.max()

    st.use()
    fig = plt.figure(figsize=(6.3, 2.75), layout="none")
    ax = fig.add_axes([0.075, 0.1, 0.41, 0.78])
    bx = fig.add_axes([0.555, 0.1, 0.235, 0.78])

    for name, y0, y1 in parts:
        seg = twh.loc[y0:y1]
        ax.stackplot(seg.index, seg[regions].T.values, colors=[COLOUR[r] for r in regions], alpha=STRETCH[name][0],
                     linewidth=0)
    ax.set_ylim(0, 1.08 * max(twh[regions].sum(axis=1).max(), o.twh.max()))
    for name, y0, _ in parts[1:]:
        for axis in (ax, bx):
            axis.axvline(y0, color=st.FAINT, linewidth=0.5, zorder=3)
        ax.annotate(NAMES[name], (y0, 1), xycoords=("data", "axes fraction"), xytext=(3, -2), textcoords="offset points",
                    ha="left", va="top", fontsize=6.5, color=st.TICK)
    ax.scatter(o.year, o.twh, s=13, facecolor="white", edgecolor=st.TEXT, linewidth=0.8, zorder=6, clip_on=False)
    for r in o.itertuples():
        ax.annotate(r.label, (r.year, r.twh), xytext=(-5, 0), textcoords="offset points", ha="right", va="center",
                    fontsize=6.5, color=st.TEXT)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
    ax.set_title("Data centres' electricity use, TWh per year", loc="left", fontsize=8.5)
    st.legend_squares(ax, [(COLOUR[r], r) for r in regions[::-1]], loc="upper left", bbox_to_anchor=(0.0, 0.9),
                      fontsize=6.5)

    for r in regions + ["World"]:
        colour = st.TEXT if r == "World" else COLOUR[r]
        for name, y0, y1 in parts:
            seg = share[r].loc[y0:y1]
            bx.plot(seg.index, seg.values, color=colour, linewidth=1.6 if r == "World" else 1.3, linestyle=STRETCH[name][1])
    bx.set_ylim(0, None)
    end_labels(bx, x1, [(f"{'World' if r == 'World' else r} {share[r].iloc[-1]:.1f}", share[r].iloc[-1],
                         st.TEXT if r == "World" else COLOUR[r]) for r in regions + ["World"]], 0.062, 2.2)
    bx.set_title("Share of electricity demand, %", loc="left", fontsize=8.5)
    for axis in (ax, bx):
        axis.set_xlim(x0, x1)
        axis.set_xticks(range(int(x0), int(x1) + 1, 10))
        axis.tick_params(labelsize=7)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"world {twh['World'].loc[2030]:.0f} TWh in 2030, {twh['World'].iloc[-1]:.0f} TWh in {x1} -> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
