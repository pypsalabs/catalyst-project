"""Overview figure (misc-quarter1/toymodel-clean-procurement): the sites on a world map in the middle of the page,
five sites above it and five below, each site a column of two violin axes (4 x 5 grid of axes), every column tied
to its site on the map by a short straight line that crosses no other axis (sites above the map are the five
northernmost in the projection, columns are ordered west to east within a band, a check-and-swap pass removes
residual crossings).

Per site, row "Energy": one violin per generation technology (share of the generation delivered to the bus, %),
a dashed separator, then one violin per storage technology (energy discharged, % of annual demand).
Row "Capacity": one violin per technology for the installed power (MW; generators and storage discharge power),
the separator, then one violin per storage technology for its energy capacity (GWh, right-hand scale). Every violin spans the ten weather years; the ten values are drawn as ink dots, the median
as an ink tick; "–" marks a technology never built. Colours = PyPSA-Eur tech_colors (config.yaml), the rest in
the icon plot style.

Also writes build/summary.csv: per site and technology the median / min / max of the plotted quantities.

Standalone: python plot_overview.py [results.csv] [out dir]
"""

import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import ConnectionPatch, Patch  # noqa: E402

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402

if "snakemake" in globals():
    CFG = snakemake.config  # noqa: F821
    _HERE = Path(snakemake.input.config).resolve().parent  # noqa: F821
    RESULTS = Path(snakemake.input.results)  # noqa: F821
    SITES = Path(snakemake.input.sites)  # noqa: F821
    OUTS = [Path(p) for p in snakemake.output.figure]  # noqa: F821
    TABLE = Path(snakemake.output.table)  # noqa: F821
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    RESULTS = Path(sys.argv[1]) if len(sys.argv) > 1 else _HERE / "build" / "results.csv"
    SITES = _HERE / CFG["sites"]
    _OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else _HERE / "figures"
    OUTS = [_OUT / f"overview.{f}" for f in CFG["plotting"]["formats"]]
    TABLE = (_OUT if len(sys.argv) > 2 else _HERE / "build") / "summary.csv"
OUTS[0].parent.mkdir(parents=True, exist_ok=True)
WY = yaml.safe_load((_HERE / CFG["weather_years_config"]).read_text())
ROBINSON = "ESRI:54030"
PL = CFG["plotting"]
COLOUR = {t: (getattr(ic, c) if not str(c).startswith("#") else c) for t, c in PL["colours"].items()}
SHORT = PL["short"]
NCOL = 5

# ---------------------------------------------------------------- data
res = pd.read_csv(RESULTS)
sites = pd.read_csv(SITES).set_index("key")
gen_techs = [t for t, s in CFG["palette"].items() if s["model"] != "storage"]
sto_techs = [t for t, s in CFG["palette"].items() if s["model"] == "storage"]
res["mean_load_mw"] = res["demand_mwh"] / 8760
per_run = res.groupby(["key", "year"])
res["gen_total"] = per_run["energy_mwh"].transform(lambda s: s[res.loc[s.index, "tech"].isin(gen_techs)].sum())
res["power_total"] = per_run["p_nom_mw"].transform("sum")
is_gen = res["tech"].isin(gen_techs)
res["energy_pct"] = np.where(is_gen, 100 * res["energy_mwh"] / res["gen_total"], 100 * res["energy_mwh"] / res["demand_mwh"])
res["e_nom_gwh"] = res["e_nom_mwh"] / 1e3
lcoe = res.drop_duplicates(["key", "year"]).groupby("key")["lcoe_usd_mwh"].agg(["median", "min", "max"])

rows = []
for (key, tech), g in res.groupby(["key", "tech"]):
    for q in ("energy_pct", "p_nom_mw", "e_nom_gwh"):
        rows.append({"key": key, "site": g["site"].iloc[0], "tech": tech, "quantity": q, "median": g[q].median(), "min": g[q].min(),
                     "max": g[q].max(), "n_years": len(g)})
pd.DataFrame(rows).to_csv(TABLE, index=False, float_format="%.4g")

# ---------------------------------------------------------------- map, bands and column order
world = gpd.read_file((_HERE / WY["world_shapes"]).resolve())
world = world[world.NAME != "Antarctica"].to_crs(ROBINSON)
pts = gpd.GeoDataFrame(sites, geometry=gpd.points_from_xy(sites.point_x, sites.point_y), crs="EPSG:4326").to_crs(ROBINSON)
by_lat = pts.geometry.y.sort_values(ascending=False).index
bands = [list(pts.loc[by_lat[:NCOL]].geometry.x.sort_values().index),      # above the map: the northernmost five, west -> east
         list(pts.loc[by_lat[NCOL:]].geometry.x.sort_values().index)]      # below the map: the rest
assert all(len(b) == NCOL for b in bands), "the layout expects 2 x 5 sites"

# ---------------------------------------------------------------- figure
ic.use()
plt.rcParams.update({"font.size": 9.5, "axes.titlesize": 10.5, "axes.labelsize": 9.5, "xtick.labelsize": 8.5, "ytick.labelsize": 8.5})
fig = plt.figure(figsize=(17, 20))
gs = fig.add_gridspec(5, NCOL, height_ratios=[1, 1, 1.75, 1, 1], left=0.05, right=0.975, top=0.94, bottom=0.05, hspace=0.55, wspace=0.14)
ax_map = fig.add_subplot(gs[2, :])
world.plot(ax=ax_map, color=ic.PALE, edgecolor=ic.INK, linewidth=0.35)
ax_map.set_axis_off()
sx, sy = pts.geometry.x, pts.geometry.y
ax_map.set_xlim(sx.min() - 1.5e6, sx.max() + 1.5e6)
ax_map.set_ylim(sy.min() - 1.2e6, sy.max() + 1.2e6)

axes = {0: ([fig.add_subplot(gs[0, j]) for j in range(NCOL)], [fig.add_subplot(gs[1, j]) for j in range(NCOL)]),
        1: ([fig.add_subplot(gs[3, j]) for j in range(NCOL)], [fig.add_subplot(gs[4, j]) for j in range(NCOL)])}
# connector anchors (axes fraction): band 0 leaves from below the capacity axis' tick labels, band 1 from above the title
ANCHOR = {0: lambda j: (axes[0][1][j], (0.5, -0.5)), 1: lambda j: (axes[1][0][j], (0.5, 1.24))}


def _cross(p1, p2, q1, q2):
    d = lambda a, b, c: (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])  # noqa: E731
    return (d(p1, p2, q1) > 0) != (d(p1, p2, q2) > 0) and (d(q1, q2, p1) > 0) != (d(q1, q2, p2) > 0)


def _anchor_fig(band, j):
    ax, (fx, fy) = ANCHOR[band](j)
    return fig.transFigure.inverted().transform(ax.transAxes.transform((fx, fy)))


def _marker_fig(key):
    return fig.transFigure.inverted().transform(ax_map.transData.transform((pts.loc[key].geometry.x, pts.loc[key].geometry.y)))


from itertools import permutations  # noqa: E402

for band in range(2):
    # column order per band: over all permutations, no crossings first, then the shortest total connector length
    keys = bands[band]
    anchors = [_anchor_fig(band, j) for j in range(NCOL)]
    markers = {k: _marker_fig(k) for k in keys}
    best = None
    for perm in permutations(keys):
        segs = [(anchors[j], markers[k]) for j, k in enumerate(perm)]
        crossings = sum(_cross(*segs[a], *segs[b]) for a in range(NCOL) for b in range(a + 1, NCOL))
        length = sum(np.hypot(p[0] - q[0], p[1] - q[1] * 0.85) for p, q in segs)   # figure fractions (the page is taller than wide)
        score = (crossings, length)
        if best is None or score < best[0]:
            best = (score, list(perm))
    bands[band] = best[1]

# violin slots: row "Energy" = generation | storage discharge; row "Capacity" = all power shares | storage energy
slots = gen_techs + [None] + sto_techs
xpos = {t: k for k, t in enumerate(slots) if t is not None}
sep_x = slots.index(None)
slots2 = gen_techs + sto_techs + [None] + sto_techs
xpos2 = {t: k for k, t in enumerate(gen_techs + sto_techs)}
xpos2e = {t: len(gen_techs) + len(sto_techs) + 1 + k for k, t in enumerate(sto_techs)}
sep2_x = len(gen_techs) + len(sto_techs)


def violin(ax, x, values, colour, zero_label=True):
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return
    if v.max() - v.min() < 1e-6 * max(1.0, abs(v.max())):
        if v.max() <= 1e-9:
            if zero_label:
                ax.text(x, 0, "–", ha="center", va="bottom", color=ic.STEEL, fontsize=9)
            return
        ax.hlines(v.mean(), x - 0.3, x + 0.3, color=ic.INK, linewidth=ic.MARK, zorder=5)
    else:
        parts = ax.violinplot([v], positions=[x], widths=0.8, showextrema=False, showmedians=False)
        for b in parts["bodies"]:
            b.set_facecolor(colour)
            b.set_edgecolor(ic.INK)
            b.set_linewidth(ic.MARK)
            b.set_alpha(1.0)
        ax.hlines(np.median(v), x - 0.3, x + 0.3, color=ic.INK, linewidth=ic.MARK, zorder=5)
    ax.scatter(x + np.linspace(-0.12, 0.12, len(v)), v, s=5, color=ic.INK, zorder=6, linewidths=0)


ylim_e = max(1.0, res["energy_pct"].max()) * 1.12
ylim_cp = max(1.0, res["p_nom_mw"].max()) * 1.12
ylim_h = max(0.1, res[res.tech.isin(sto_techs)]["e_nom_gwh"].max()) * 1.12

for band, order in enumerate(bands):
    for j, key in enumerate(order):
        sub = res[res.key == key]
        short = sites.loc[key, "site"].split(" · ", 1)[1]
        ax = axes[band][0][j]
        for t in gen_techs + sto_techs:
            violin(ax, xpos[t], sub[sub.tech == t]["energy_pct"], COLOUR[t])
        ax.axvline(sep_x, color=ic.INK, linewidth=ic.SEAM, linestyle=(0, (3, 2)), zorder=1)
        ax.set_xlim(-0.7, len(slots) - 0.3)
        ax.set_ylim(0, ylim_e)
        ax.set_xticks(list(xpos.values()))
        ax.set_xticklabels([SHORT.get(t, t) for t in xpos], rotation=90)
        l = lcoe.loc[key]
        ax.set_title(f"{short}   {l['median']:.0f} $/MWh ({l['min']:.0f}–{l['max']:.0f})", loc="left")
        ic.ground(ax)

        ax = axes[band][1][j]
        for t in gen_techs + sto_techs:
            violin(ax, xpos2[t], sub[sub.tech == t]["p_nom_mw"], COLOUR[t])
        ax.axvline(sep2_x, color=ic.INK, linewidth=ic.SEAM, linestyle=(0, (3, 2)), zorder=1)
        ax.set_xlim(-0.7, len(slots2) - 0.3)
        ax.set_ylim(0, ylim_cp)
        ax2 = ax.twinx()
        for t in sto_techs:
            violin(ax2, xpos2e[t], sub[sub.tech == t]["e_nom_gwh"], COLOUR[t])
        ax2.set_ylim(0, ylim_h)
        ax2.set_xlim(-0.7, len(slots2) - 0.3)
        ax2.grid(False)
        for s in ax2.spines.values():
            s.set_visible(False)
        ax2.tick_params(axis="y", length=0, colors=ic.MUTED)
        if j < NCOL - 1:
            ax2.set_yticklabels([])
        ax.set_xticks(list(xpos2.values()) + list(xpos2e.values()))
        ax.set_xticklabels([SHORT.get(t, t) for t in xpos2] + [f"{SHORT.get(t, t)} GWh" for t in xpos2e], rotation=90)
        ic.ground(ax)
        if j > 0:
            axes[band][0][j].set_yticklabels([])
            ax.set_yticklabels([])
        anchor_ax, anchor = ANCHOR[band](j)
        fig.add_artist(ConnectionPatch(xyA=anchor, coordsA="axes fraction", axesA=anchor_ax,
                                       xyB=(pts.loc[key].geometry.x, pts.loc[key].geometry.y), coordsB="data", axesB=ax_map,
                                       color=ic.MUTED, linewidth=ic.SEAM, zorder=1))
    axes[band][0][0].set_ylabel("Energy, %: generation share | discharge / demand")
    axes[band][1][0].set_ylabel("Installed power, MW | storage energy, GWh (right)")

pts.plot(ax=ax_map, color=ic.AMBER, edgecolor=ic.INK, linewidth=ic.MARK, markersize=80, zorder=5)
demand_mw = float(res["demand_mwh"].iloc[0] / 8760)
fig.suptitle(f"A constant {demand_mw:.0f} MW supplied 100 % clean in isolation, per site and weather year ({len(res.year.unique())} years): "
             "technology_assumptions.csv, 7 % real, no imports",
             x=0.05, y=0.985, ha="left", color=ic.INK, fontsize=12, fontweight=ic.EMPH)
handles = [Patch(facecolor=COLOUR[t], edgecolor=ic.INK, linewidth=ic.MARK, label=SHORT.get(t, t)) for t in gen_techs + sto_techs]
fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.975, 0.975), ncol=len(handles), frameon=False, handlelength=1.0,
           handleheight=1.0, columnspacing=1.2)
for out in OUTS:
    fig.savefig(out, dpi=PL["dpi"])
print("wrote", *OUTS, TABLE)
