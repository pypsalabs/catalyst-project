"""Circuit length and the loadability limit of long AC circuits in the six spatially resolved regions (Grid Data).

One of four figures, chosen by --figure:
  lengths   share of the AC capacity between clusters by the length of the circuit, one row per region on one length
            axis, regions sorted by their median, with the length from which the loadability is below the thermal rating
  curve     (a) the St. Clair curve in multiples of the surge impedance loading and the thermal rating of the line
            types; (b) share of the thermal rating that is loadable, per clustered line, against the length of its circuits
  map       the clustered networks, line width = thermal rating, colour = usable share of it
  check     (a) sum of the line limits per GW of peak load, PyPSA-Earth and here; (b) capacity across the borders with a
            published transfer capacity, model over published (Europe also against its reference grid of 2030)

Reads build/loadability/*.csv, written by ../scripts/check_loadability.py (read-only, no model rerun), and for the
maps the country shapes of the runs.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_loadability.py --figure lengths
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.patches import Patch

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

FORK = TOP / "../../models/pypsa-earth"
DATA = TOP / "build/loadability"
REGIONS = {"USW": "US West", "USE": "US East", "BR": "Brazil", "IN": "India", "CN": "China", "NWE": "North-West Europe"}
COLOUR = {"USW": st.BLUE, "USE": st.PINK, "BR": st.GREEN, "IN": st.ORANGE, "CN": st.VERMILLION, "NWE": st.SKY}
SHAPES = {"USW": "USW", "USE": "USE", "BR": "BR", "IN": "IN", "CN": "CN", "NWE": "NWE"}   # resources/<run>/shapes
MILE = 1.609344


def read(data):
    s = pd.read_csv(data / "summary.csv", index_col=0)
    lines = {r: pd.read_csv(data / f"lines_{r}.csv", index_col=0) for r in REGIONS}
    return s, lines


def binds_from(curve, v=380):
    """Length from which the loadability of the line type is below its thermal rating."""
    return float(curve.length_km[curve[f"share_{v}"] < 1].iloc[0])


def lengths(a):
    """Capacity between clusters by circuit length, one row per region, sorted by the median."""
    s, _ = read(a.data)
    c380 = binds_from(pd.read_csv(a.data / "curve.csv"))
    order = s.circuit_between_km_median.reindex(list(REGIONS)).sort_values(ascending=False).index
    bins = np.geomspace(1, 1500, 45)
    fig, axes = plt.subplots(len(order), 1, layout="none", figsize=(6.3, 4.5), sharex=True, sharey=True)
    plt.subplots_adjust(left=0.215, right=0.985, top=0.885, bottom=0.095, hspace=0.12)
    for ax, r in zip(axes, order):
        c = pd.read_csv(a.data / f"circuits_{r}.csv", index_col=0)
        c = c[c.between_clusters]
        h = np.histogram(c.length.clip(bins[0], bins[-1]), bins=bins, weights=c.s_nom)[0] / c.s_nom.sum()
        ax.axvspan(c380, bins[-1], color=st.FAINT, alpha=0.35, linewidth=0, zorder=0)
        ax.bar(bins[:-1], 100 * h, width=np.diff(bins) * 0.92, align="edge", color=COLOUR[r], linewidth=0, zorder=2)
        m = s.circuit_between_km_median[r]
        ax.plot([m, m], [0, 15.5], color=st.TEXT, lw=1.0, zorder=3, solid_capstyle="butt")
        ax.text(m * 1.07, 15.2, f"{m:.0f} km", fontsize=6.6, color=st.TEXT, va="top", ha="left")
        ax.text(-0.012, 0.62, REGIONS[r], transform=ax.transAxes, fontsize=7.4, ha="right", va="center", color=st.TEXT, fontweight="bold")
        ax.text(-0.012, 0.24, f"{100 * s.capacity_limited_share[r]:.0f} % limited", transform=ax.transAxes, fontsize=6.6, ha="right",
                va="center", color=st.TICK)
        ax.set_xscale("log")
        ax.set_xlim(bins[0], bins[-1])
        ax.set_ylim(0, 16)
        ax.set_yticks([0, 10])
        ax.tick_params(labelsize=6.6, labelleft=False)
        ax.grid(axis="x", visible=False)
        ax.set_xticks([1, 3, 10, 30, 100, 300, 1000], ["1", "3", "10", "30", "100", "300", "1,000"])
        ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    axes[-1].set_xlabel("Length of the circuit, km", fontsize=7)
    fig.text(0.215, 0.972, "Share of the AC capacity between clusters by the length of the circuit, % per length bin", fontsize=8,
             fontweight="bold", color=st.TEXT, va="center")
    fig.text(0.215, 0.93, "Circuits of the base network; black line = median by capacity; grey area = loadability below the thermal rating (380 kV); grid line = 10 %",
             fontsize=6.5, color=st.TICK, va="center")
    return fig


def curve(a):
    """The curve, and where the clustered lines sit on it."""
    s, lines = read(a.data)
    c = pd.read_csv(a.data / "curve.csv")
    fig, (ax0, ax1) = plt.subplots(1, 2, layout="none", figsize=(6.3, 2.75))
    plt.subplots_adjust(left=0.06, right=0.985, top=0.84, bottom=0.15, wspace=0.2)

    sel = c[(c.length_km >= 50 * MILE * 0.999) & (c.length_km <= 1300)]
    ax0.plot(sel.length_km, sel.sil_multiples, color=st.TEXT, lw=1.3, zorder=3)
    pts = c[c.point]
    ax0.scatter(pts.length_km, pts.sil_multiples, s=11, color=st.TEXT, linewidths=0, zorder=4)
    # thermal rating of a line type in multiples of its SIL = 1 / (SIL per thermal): where its curve leaves 1 in share_<v>
    for v, colour, dy in [(380, st.BLUE, 0.06), (750, st.VERMILLION, -0.13)]:
        first = c[c[f"share_{v}"] < 1].iloc[0]
        level = first.sil_multiples / first[f"share_{v}"]
        ax0.plot([0, first.length_km], [level, level], color=colour, lw=1.0, zorder=2)
        ax0.plot([first.length_km, 1300], [level, level], color=colour, lw=0.7, ls=(0, (3, 2)), zorder=2)
        ax0.text(1290, level + dy, f"thermal rating, {v} kV line type", fontsize=6.4, color=colour, ha="right", va="bottom" if dy > 0 else "top")
    ax0.set_xlim(0, 1300)
    ax0.set_ylim(0, 3.3)
    ax0.set_xlabel("Length of the circuit, km", fontsize=7)
    ax0.set_title("(a) Loadability, multiples of the surge impedance loading", loc="left", fontsize=7.5)
    ax0.annotate("St. Clair curve", (430, float(np.interp(430, c.length_km, c.sil_multiples))), xytext=(8, 12), textcoords="offset points",
                 fontsize=6.6, color=st.TEXT)
    ax0.tick_params(labelsize=6.8)

    sel = c[c.length_km <= 620]
    ax1.plot(sel.length_km, sel.share_380, color=st.NEUTRAL, lw=1.0, zorder=1)
    ax1.text(615, float(sel.share_380.iloc[-1]) - 0.03, "one 380 kV circuit", fontsize=6.4, color=st.TICK, ha="right", va="top")
    for r in REGIONS:
        L = lines[r].dropna(subset=["circuit_length"])
        ax1.scatter(L.circuit_length, L.factor, s=2 + 28 * L.s_nom / 60e3, color=COLOUR[r], alpha=0.75, linewidths=0, zorder=3)
    ax1.set_xlim(0, 620)
    ax1.set_ylim(0, 1.05)
    ax1.set_xlabel("Mean length of the line's circuits, km", fontsize=7)
    ax1.set_title("(b) Loadable share of the thermal rating, per line", loc="left", fontsize=7.5)
    ax1.tick_params(labelsize=6.8)
    st.legend_squares(ax1, [(COLOUR[r], n) for r, n in REGIONS.items()], loc="lower left", bbox_to_anchor=(0.0, 0.0), fontsize=6.4,
                      ncol=2, columnspacing=1.0, handletextpad=0.5)
    return fig


def maps(a):
    """Clustered networks, coloured by the usable share of the thermal rating."""
    import geopandas as gpd

    s, lines = read(a.data)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("share", plt.get_cmap("viridis")(np.linspace(0.0, 0.9, 256)))
    norm = matplotlib.colors.Normalize(0.15, 0.4)
    fig, axes = plt.subplots(2, 3, layout="none", figsize=(6.3, 4.6))
    plt.subplots_adjust(left=0.005, right=0.995, top=0.955, bottom=0.14, wspace=0.03, hspace=0.12)
    for ax, (r, name) in zip(axes.flat, REGIONS.items()):
        shape = gpd.read_file(a.fork / f"resources/{SHAPES[r]}/shapes/country_shapes.geojson")
        shape.plot(ax=ax, color=st.LAND, edgecolor=st.FAINT, linewidth=0.3, zorder=0)
        L = lines[r].sort_values("s_max_pu", ascending=False)   # the most limited lines on top
        segs = np.stack([L[["x0", "y0"]].values, L[["x1", "y1"]].values], axis=1)
        ax.add_collection(LineCollection(segs, colors=cmap(norm(L.s_max_pu.values)), linewidths=0.35 + 2.6 * np.sqrt(L.s_nom.values / 60e3),
                                         capstyle="round", zorder=2))
        nodes = pd.concat([L[["x0", "y0"]].set_axis(["x", "y"], axis=1), L[["x1", "y1"]].set_axis(["x", "y"], axis=1)]).drop_duplicates()
        ax.scatter(nodes.x, nodes.y, s=2.2, color=st.TEXT, linewidths=0, zorder=3)
        x0, y0, x1, y1 = shape.total_bounds
        if r == "USE":
            x0 = max(x0, -107)
        px, py = 0.03 * (x1 - x0), 0.03 * (y1 - y0)
        ax.set_xlim(x0 - px, x1 + px)
        ax.set_ylim(y0 - py, y1 + py)
        ax.set_aspect(1 / np.cos(np.deg2rad((y0 + y1) / 2)), adjustable="datalim")
        ax.set_axis_off()
        ax.set_title(f"{name}: {s.s_max_pu_after[r]:.2f}", loc="left", fontsize=7.4, pad=2, x=0.02)
    cax = fig.add_axes([0.3, 0.05, 0.4, 0.016])
    st.colorbar(fig, matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap), cax,
                "Usable share of the thermal rating (PyPSA-Earth: 0.7 for every line); line width = thermal rating",
                ticks=[0.15, 0.2, 0.25, 0.3, 0.35, 0.4])
    return fig


def check(a):
    """Line limits per GW of peak load, and the model against published transfer capacities."""
    s, _ = read(a.data)
    t = pd.read_csv(a.data / "transfer.csv")
    t = t[t.ac_circuits > 0]
    g = t.groupby("region")
    ratio = pd.DataFrame({k: (g[k].sum() + g.hvdc_gw.sum()) / g.published_gw.sum() for k in ["ac_default_gw", "ac_loadable_default_gw", "ac_after_gw"]})
    borders = g.size()
    fig, (ax0, ax1) = plt.subplots(1, 2, layout="none", figsize=(6.3, 2.7), gridspec_kw=dict(width_ratios=[1.0, 1.0]))
    plt.subplots_adjust(left=0.155, right=0.975, top=0.8, bottom=0.17, wspace=0.78)

    h = 0.36
    y = np.arange(len(REGIONS))[::-1]
    for k, (col, colour) in enumerate([("limit_per_peak_default", st.NEUTRAL), ("limit_per_peak_after", st.BLUE)]):
        v = s[col].reindex(list(REGIONS))
        ax0.barh(y + (1 - 2 * k) * h / 2, v, height=h, color=colour, linewidth=0, zorder=2)
        for yy, val in zip(y + (1 - 2 * k) * h / 2, v):
            ax0.text(val + 0.06, yy, f"{val:.1f}", fontsize=6.4, va="center", color=st.TEXT)
    ax0.set_yticks(y, list(REGIONS.values()), fontsize=7)
    ax0.set_ylim(-0.6, len(REGIONS) - 0.4)
    ax0.set_xlim(0, 1.12 * s.limit_per_peak_default.max())
    ax0.grid(axis="x", visible=True)
    ax0.grid(axis="y", visible=False)
    ax0.tick_params(labelsize=6.8)
    ax0.set_title("(a) Sum of the AC line limits,\nGW per GW of peak load", loc="left", fontsize=7.5, x=-0.42, linespacing=1.25)

    # rows: (label, at PyPSA-Earth's margin, with loadability and margin); Europe also against its reference grid of 2030
    rows = [(f"{REGIONS[r]} ({borders[r]})", ratio.ac_default_gw[r], ratio.ac_after_gw[r]) for r in REGIONS if r in ratio.index]
    e = t[(t.region == "NWE") & t.published_2030_gw.notna()]
    if len(e):
        i = next(k for k, row in enumerate(rows) if row[0].startswith(REGIONS["NWE"]))
        rows[i] = (f"{REGIONS['NWE']} ({borders['NWE']}), 2024", *rows[i][1:])
        pub = e.published_2030_gw.sum()
        rows.insert(i + 1, ("same borders, 2030 reference grid", (e.ac_default_gw.sum() + e.hvdc_gw.sum()) / pub,
                            (e.ac_after_gw.sum() + e.hvdc_gw.sum()) / pub))
    y = np.arange(len(rows))[::-1]
    ax1.axvline(1.0, color=st.TEXT, lw=0.8, zorder=1)
    for yy, (label, before, after) in zip(y, rows):
        ax1.barh(yy + h / 2, before, height=h, color=st.NEUTRAL, linewidth=0, zorder=2)
        ax1.barh(yy - h / 2, after, height=h, color=st.BLUE, linewidth=0, zorder=2)
        ax1.text(before + 0.04, yy + h / 2, f"{before:.1f}", fontsize=6.4, va="center", color=st.TEXT)
        ax1.text(after + 0.04, yy - h / 2, f"{after:.1f}", fontsize=6.4, va="center", color=st.TEXT)
    ax1.set_yticks(y, [r[0] for r in rows], fontsize=7)
    ax1.set_ylim(-0.6, len(rows) - 0.4)
    ax1.set_xlim(0, 3.0)
    ax1.grid(axis="x", visible=True)
    ax1.grid(axis="y", visible=False)
    ax1.tick_params(labelsize=6.8)
    ax1.set_title("(b) Capacity across borders with a published transfer\ncapacity, model over published (number of borders)", loc="left",
                  fontsize=7.5, x=-0.7, linespacing=1.25)
    fig.legend(handles=[Patch(facecolor=c, linewidth=0, label=l) for c, l in
                        [(st.NEUTRAL, "PyPSA-Earth: thermal rating × 0.7"), (st.BLUE, "with the loadability and a margin of 0.4")]],
               loc="lower center", bbox_to_anchor=(0.5, -0.005), ncol=2, fontsize=6.6, frameon=False, columnspacing=1.6, handletextpad=0.5,
               handlelength=0.9, handleheight=0.9)
    return fig


FIGURES = {"lengths": lengths, "curve": curve, "map": maps, "check": check}


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--figure", choices=list(FIGURES), required="snakemake" not in globals())
    p.add_argument("--data", type=Path, default=DATA)
    p.add_argument("--fork", type=Path, default=FORK)
    p.add_argument("--out", default=None)
    if "snakemake" in globals():
        a = p.parse_args(["--figure", snakemake.params.figure, "--data", str(Path(snakemake.input.summary).parent), "--out", str(snakemake.output[0])])
    else:
        a = p.parse_args()
    out = Path(a.out or TOP / f"build/figures/{'line_lengths' if a.figure == 'lengths' else 'loadability_' + a.figure}.pdf")

    st.use()
    fig = FIGURES[a.figure](a)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=300)
    fig.set_layout_engine("none")   # the style's constrained layout would take over for a second save
    fig.savefig(out.with_suffix(".png"), dpi=200)
    print(f"-> {out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
