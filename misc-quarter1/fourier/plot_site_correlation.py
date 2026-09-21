"""Independence check for the ten selected sites (misc-quarter1/fourier).

Left: site map on a world outline. Middle / right: pairwise Pearson correlation of the
wind and solar anomaly bands (daily mean minus 31-day rolling mean) from
build/site_correlation.csv. The title reports the worst pair against the configured limit.

Standalone: python plot_site_correlation.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

if "snakemake" in globals():
    CFG = snakemake.config  # noqa: F821
    SITES = Path(snakemake.input.sites)  # noqa: F821
    CORR = Path(snakemake.input.correlation)  # noqa: F821
    OUTPUTS = [Path(p) for p in snakemake.output]  # noqa: F821
    _HERE = Path(snakemake.input.config).resolve().parent  # noqa: F821
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    SITES = _HERE / "build" / "sites.csv"
    CORR = _HERE / "build" / "site_correlation.csv"
    OUTPUTS = [_HERE / "figures" / f"site_correlation.{fmt}" for fmt in CFG["plotting"]["formats"]]
OUTPUTS[0].parent.mkdir(parents=True, exist_ok=True)

sites = pd.read_csv(SITES, index_col=0)
corr = pd.read_csv(CORR, index_col=[0, 1])
names = sites.site.tolist()
ramp = CFG["colours"]["ramps"]["wind"]
cmap = LinearSegmentedColormap.from_list("wind", [ramp["light"], ramp["dark"]])
site_colours = [cmap(k / max(len(names) - 1, 1)) for k in range(len(names))]
limit = CFG["selection"]["max_abs_corr"]

fig = plt.figure(figsize=(14, 4.8), layout="constrained")
gs = fig.add_gridspec(1, 3, width_ratios=[1.9, 1, 1])

# --- map
ax = fig.add_subplot(gs[0, 0])
world = gpd.read_file((_HERE / CFG["world_shapes"]).resolve())
world = world[world.geometry.centroid.y > -60]           # drop Antarctica
world.plot(ax=ax, color="0.93", edgecolor="0.78", linewidth=0.4)
# modelled countries: shaded, and their connected part (largest polygon; CONUS, Jutland, ...) sets the extent
iso = world["ISO_A2_EH"] if "ISO_A2_EH" in world else world["ISO_A2"]
modelled = world[iso.isin([c for spec in CFG["regions"].values() for c in spec["countries"]])]
modelled.plot(ax=ax, color="0.84", edgecolor="0.7", linewidth=0.4)
main_parts = modelled.geometry.apply(lambda g: max(getattr(g, "geoms", [g]), key=lambda p: p.area))
x0, y0, x1, y1 = gpd.GeoSeries(main_parts).total_bounds
for k, (key, row) in enumerate(sites.iterrows()):
    ax.plot(row.x, row.y, "o", ms=7, color=site_colours[k], mec="white", mew=1.2, zorder=3)
    ax.annotate(f"{k + 1}", (row.x, row.y), xytext=(4, 4), textcoords="offset points", fontsize=7.5, color="0.2")
pad = 3
ax.set_xlim(x0 - pad, x1 + pad)
ax.set_ylim(y0 - pad, y1 + pad)
ax.set_aspect("equal")
ax.set_axis_off()
handles = [plt.Line2D([], [], marker="o", ls="", color=site_colours[k], mec="white", mew=1.0, ms=6.5,
                      label=f"{k + 1}  {n}") for k, n in enumerate(names)]
ax.legend(handles=handles, loc="lower left", fontsize=7.2, frameon=False, ncol=1, handletextpad=0.3,
          columnspacing=1.0, borderaxespad=0.0)

# --- heatmaps
short = [f"{k + 1}" for k in range(len(names))]
for col, (kind, title) in enumerate([("wind_anomaly", "wind anomaly band"), ("solar_anomaly", "solar anomaly band")], start=1):
    ax = fig.add_subplot(gs[0, col])
    m = corr.loc[kind].reindex(index=names, columns=names).values
    im = ax.imshow(m, cmap="RdBu_r", vmin=-1, vmax=1)
    off = m.copy()
    np.fill_diagonal(off, 0)
    for i in range(len(names)):
        for j in range(len(names)):
            if i != j:
                ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center", fontsize=6.2,
                        color="0.15" if abs(m[i, j]) < 0.6 else "white")
    ax.set_xticks(range(len(names)), short, fontsize=7.5)
    ax.set_yticks(range(len(names)), short, fontsize=7.5)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(f"Pearson ρ, {title}\nworst |ρ| = {np.abs(off).max():.2f} (limit {limit})", loc="left", fontsize=10)
cb = fig.colorbar(im, ax=fig.axes[1:], shrink=0.75, pad=0.02)
cb.set_label("ρ", rotation=0)
cb.outline.set_visible(False)

for out in OUTPUTS:
    fig.savefig(out, dpi=CFG["plotting"]["dpi"], bbox_inches="tight")
plt.close(fig)
print("wrote", ", ".join(str(o) for o in OUTPUTS))
