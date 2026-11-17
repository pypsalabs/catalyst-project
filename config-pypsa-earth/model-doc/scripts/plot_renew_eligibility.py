"""Land cover and land eligibility of wind and solar in one region (Renewables & Weather, standard procedure).

A 260 x 230 km box of north-east Scotland (Inverness to Aberdeen) on a 200 m grid:
(a) the land cover of the Copernicus map in the classes the rule distinguishes, protected areas hatched;
(b) onshore wind, (c) solar: where the technology may be built, and why not elsewhere;
(d) offshore wind: the sea depth of GEBCO as the rule reads it, the depth limit and the distance to the coast that
    separates the two carriers as lines, and the sea where no offshore wind may be built hatched.
The eligibility is computed by ../scripts/check_renewables.py (`eligibility`) with atlite from the rule's rasters, codes and
buffers at 100 m; a 200 m cell counts as eligible where at least half of it is. The reason for an ineligible cell is read
off the 200 m rasters (protected, then land cover or depth, else the buffer around built-up land). Reads
build/renewables_check/eligibility_NWE.npz and the fork's config.default.yaml (the land-cover codes per technology).

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_renew_eligibility.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml
from matplotlib.colors import LinearSegmentedColormap, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from pyproj import Transformer

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

FORK = TOP / "../../models/pypsa-earth"
# land-cover classes of the Copernicus map as the rule's code lists group them: label, codes, colour
COVER = [("forest", list(range(111, 127)), "#3f8f4f"), ("shrubland", [20], "#d9b45a"), ("grassland", [30], "#e6e08a"),
         ("cropland", [40], "#e3a3cf"), ("built-up", [50], "#d7301f"), ("bare", [60, 70, 100], "#b9b9b9"),
         ("wetland", [90], "#3aa6a6"), ("inland water", [80], "#4a78c8"), ("sea", [200, 0], "#dbe9f6")]
SEA, PROTECTED, NOT_ALLOWED, BUFFER = "#eef3f8", "#7E6BB0", "#c9c9c9", st.VERMILLION
LAND = "#d8d2c4"                                   # the land in the sea panel: a warm grey, apart from every blue of the depth
DEPTH = LinearSegmentedColormap.from_list("depth", ["#eaf4fb", "#9ecae1", "#4292c6", "#1f5a99"])
DEPTH_MAX = 120                                    # m, upper end of the depth colours
HATCH = "#2b2b2b"
CITIES = {"Inverness": (-4.22, 57.48), "Aberdeen": (-2.10, 57.15), "Dundee": (-2.97, 56.46)}
SCALE_KM = 50


def hatch(mask, period=20, width=2, down=False):
    """Diagonal lines over the cells of `mask`, as a boolean raster."""
    iy, ix = np.indices(mask.shape)
    return mask & (((ix - iy if down else ix + iy) % period) < width)


def rgb(index, colours):
    return ListedColormap(colours)(index)


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--eligibility", default=TOP / "build/renewables_check/eligibility_NWE.npz")
    p.add_argument("--config", default=FORK / "config.default.yaml")
    p.add_argument("--out", default=TOP / "build/figures/renew_eligibility.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--eligibility", snakemake.input.eligibility, "--config", snakemake.input.config, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    z = np.load(a.eligibility)
    renewable = yaml.safe_load(open(a.config))["renewable"]
    cover = z["landcover"].astype(int)
    land, offshore = z["country"], z["offshore"] & ~z["country"]
    protected = z["protected"] == 1
    extent = z["extent"]
    eligible = {t: z[f"eligible_{t}"] >= 0.5 for t in ["onwind", "solar", "offwind-ac", "offwind-dc"]}

    st.use()
    W = 6.3                                               # inches; every panel: title, map, legend
    pw = 0.485 * W
    ph = pw * (extent[3] - extent[2]) / (extent[1] - extent[0])
    title, legend, gap = 0.22, [0.80, 1.08], 0.12       # legend height per row
    H = 2 * title + 2 * ph + sum(legend) + gap
    fig = plt.figure(layout="none", figsize=(W, H))
    axes, legends = [], []
    top = H
    for row in range(2):
        top -= title
        for x in [0.0, 0.515 * W]:
            axes.append(fig.add_axes([x / W, (top - ph) / H, pw / W, ph / H]))
            legends.append(fig.add_axes([x / W, (top - ph - legend[row]) / H, pw / W, (legend[row] - 0.06) / H]))
        top -= ph + legend[row] + gap
    to_m = Transformer.from_crs("EPSG:4326", "ESRI:54009", always_xy=True)

    # (a) land cover
    index = np.full(cover.shape, len(COVER) - 1)
    for i, (_, codes, _) in enumerate(COVER):
        index[np.isin(cover, codes)] = i
    axes[0].imshow(rgb(index, [c for _, _, c in COVER]), extent=extent, interpolation="nearest")
    axes[0].contourf(np.linspace(extent[0], extent[1], cover.shape[1]), np.linspace(extent[3], extent[2], cover.shape[0]),
                     protected.astype(float), levels=[0.5, 1.5], colors="none", hatches=["//////"])
    axes[0].contour(np.linspace(extent[0], extent[1], cover.shape[1]), np.linspace(extent[3], extent[2], cover.shape[0]),
                    protected.astype(float), levels=[0.5], colors="#222222", linewidths=0.35)
    share = {label: np.isin(cover, codes)[land].mean() for label, codes, _ in COVER}
    items = [(c, f"{label} ({share[label]:.0%})" if label != "sea" else label) for label, _, c in COVER]
    st.legend_squares(legends[0], items, loc="upper left", ncol=3, fontsize=6.3, columnspacing=1.0)
    legends[0].text(0.0, 0.30, f"hatched: protected areas ({protected[land].mean():.0%} of the land)", fontsize=6.3, color=st.TEXT,
                    va="top", transform=legends[0].transAxes)

    # (b), (c) onshore wind and solar: eligible, or the reason why not
    notes = {"onwind": "water, wetland, built-up", "solar": "forest, water"}
    for ax, lax, tech in [(axes[1], legends[1], "onwind"), (axes[2], legends[2], "solar")]:
        cfg = renewable[tech]["copernicus"]
        allowed = np.isin(cover, cfg["grid_codes"])
        k = np.full(cover.shape, 0)                      # 0 sea / outside
        k[land] = 4                                       # buffer around built-up land (what remains)
        k[land & ~allowed] = 3
        k[land & protected] = 2
        k[land & eligible[tech]] = 1
        colours = [SEA, st.GREEN, PROTECTED, NOT_ALLOWED, BUFFER]
        ax.imshow(rgb(k, colours), extent=extent, interpolation="nearest")
        s = {i: (k[land] == i).mean() for i in range(1, 5)}
        items = [(st.GREEN, f"may be built ({s[1]:.0%} of the land)"), (PROTECTED, f"protected area ({s[2]:.0%})"),
                 (NOT_ALLOWED, f"land cover not allowed: {notes[tech]} ({s[3]:.0%})")]
        if cfg.get("distance"):
            items.append((BUFFER, f"within {cfg['distance'] / 1000:.0f} km of built-up land ({s[4]:.0%})"))
        st.legend_squares(lax, items, loc="upper left", ncol=1, fontsize=6.3)
        print(tech, {i: round(v, 3) for i, v in s.items()})

    # (d) offshore wind: the depth the rule reads, lines at its two limits, hatched where nothing may be built
    depth_limit = renewable["offwind-ac"]["max_depth"]
    km = renewable["offwind-ac"]["max_shore_distance"] / 1000
    depth = -z["depth"]
    k = np.full(cover.shape, 0)                          # land
    k[offshore] = 5                                       # shallow, but not sea in the land-cover map (what remains)
    k[offshore & (depth > depth_limit)] = 4
    k[offshore & protected] = 3
    k[offshore & eligible["offwind-dc"]] = 2
    k[offshore & eligible["offwind-ac"]] = 1
    image = DEPTH(np.clip(depth, 0, DEPTH_MAX) / DEPTH_MAX)
    image[~offshore] = matplotlib.colors.to_rgba(LAND)
    for mask, colour, alpha in [(hatch(np.isin(k, [4, 5])), HATCH, 0.8), (hatch(k == 3, down=True), PROTECTED, 1.0)]:
        image[mask] = (1 - alpha) * image[mask] + alpha * np.array(matplotlib.colors.to_rgba(colour))
    axes[3].imshow(image, extent=extent, interpolation="nearest")
    xs = np.linspace(extent[0], extent[1], cover.shape[1])
    ys = np.linspace(extent[3], extent[2], cover.shape[0])
    axes[3].contour(xs, ys, np.where(offshore, depth, np.nan), levels=[depth_limit], colors="#111111", linewidths=0.8)
    axes[3].contour(xs, ys, np.where(land, 1.0, z["near_shore"].astype(float)), levels=[0.5], colors="#111111", linewidths=0.8,
                    linestyles=[(0, (3, 2))])
    s = {i: (k[offshore] == i).mean() for i in range(1, 6)}
    lax = legends[3]
    cax = fig.add_axes([lax.get_position().x0, lax.get_position().y1 - 0.24 / H, 0.5 * pw / W, 0.07 / H])
    st.colorbar(fig, plt.cm.ScalarMappable(plt.Normalize(0, DEPTH_MAX), DEPTH), cax, "Sea depth, m", ticks=[0, depth_limit, 100])
    cax.tick_params(labelsize=6.3, pad=2)
    cax.xaxis.label.set_fontsize(6.3)
    handles = [Patch(facecolor="white", edgecolor=HATCH, hatch="//////", linewidth=0, label=f"no offshore wind: deeper than {depth_limit} m ({s[4] + s[5]:.0%} of the sea)"),
               Patch(facecolor="white", edgecolor=PROTECTED, hatch="\\\\\\\\\\\\", linewidth=0, label=f"no offshore wind: protected area ({s[3]:.0%})"),
               Line2D([], [], color="#111111", linewidth=0.8, label=f"{depth_limit} m depth"),
               Line2D([], [], color="#111111", linewidth=0.8, linestyle=(0, (3, 2)),
                      label=f"{km:.0f} km from the coast: AC connection within ({s[1]:.0%}), DC beyond ({s[2]:.0%})")]
    lax.legend(handles=handles, loc="lower left", fontsize=6.3, handlelength=1.4, handleheight=0.9, handletextpad=0.5, borderaxespad=0,
               labelspacing=0.3)
    print("offshore", {i: round(v, 3) for i, v in s.items()})

    for ax, title in zip(axes, ["(a) Land cover", "(b) Onshore wind", "(c) Solar", "(d) Offshore wind"]):
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_title(title, loc="left", fontsize=8.5)
        for name, (lon, lat) in CITIES.items():
            x, y = to_m.transform(lon, lat)
            ax.plot(x, y, marker="o", markersize=2.2, color="#111111", markeredgecolor="white", markeredgewidth=0.4, zorder=6)
            ax.annotate(name, (x, y), xytext=(-3, 3), textcoords="offset points", ha="right", va="bottom", fontsize=6,
                        color="#111111", zorder=6, bbox=dict(facecolor="white", edgecolor="none", alpha=0.7, pad=0.4))
    x0, y0 = extent[1] - 12e3 - SCALE_KM * 1e3, extent[2] + 10e3
    axes[0].plot([x0, x0 + SCALE_KM * 1e3], [y0, y0], color="#111111", linewidth=1.2, solid_capstyle="butt")
    axes[0].text(x0 + SCALE_KM * 5e2, y0 + 3e3, f"{SCALE_KM} km", ha="center", va="bottom", fontsize=6, color="#111111")
    for lax in legends:
        lax.set_axis_off()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=300)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=220)
    print({k: round(v, 3) for k, v in share.items()}, f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
