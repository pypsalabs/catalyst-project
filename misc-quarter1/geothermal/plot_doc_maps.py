"""Two half-width EGS maps for the technology-assumptions document (config-pypsa-earth/technology-assumptions).

  figures/egs_doc_gradient.pdf  mean geothermal gradient from the surface to 4.5 km, (T(4.5 km) - T_surface) / 4.5 km,
                                in degC/km on every land cell (build/egs_grid.nc: conduction from Lucazeau 2019 heat flow,
                                Stanford thermal model over CONUS); capped at 60 degC/km, the hotspot outliers of the
                                conduction model run above it
  figures/egs_doc_capex.pdf     EGS CAPEX in USD2024/kW at the cell's LCOE-optimal depth (build/egs_potential.csv,
                                Ricks & Jenkins 2025 cost model, 2025 baseline, no learning); land without a feasible
                                reservoir (< 150 degC down to 6.5 km) in grey

Style follows the document's other maps (scripts/plot_resource_maps.py there): one PDF per panel at half the
160 mm text width, serif 7 pt, colour bar below the map; the gradient in a single-hue colormap without its white end,
the CAPEX in a multi-hue one (viridis, cheap = yellow) so that cost classes stay distinguishable. The CAPEX map marks
the validation sites of config `site_checks` with a red ring and a legend (Fervo Cape Station; see site_check.py).
The full description of the dataset is in README.md (sections "EGS" and "Figures").

Standalone: python plot_doc_maps.py
"""

from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
import yaml
from matplotlib.colors import LinearSegmentedColormap, LogNorm, Normalize

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    GRID, POT = Path(snakemake.input.grid), Path(snakemake.input.potential)
    OUT_GRAD, OUT_CAPEX = Path(snakemake.output.gradient), Path(snakemake.output.capex)
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    GRID, POT = HERE / "build" / "egs_grid.nc", HERE / "build" / "egs_potential.csv"
    OUT_GRAD, OUT_CAPEX = HERE / "figures" / "egs_doc_gradient.pdf", HERE / "figures" / "egs_doc_capex.pdf"

COUNTRIES = (HERE / CFG["archetype_data_dir"] / "ne_50m_admin_0_countries" / "ne_50m_admin_0_countries.shp").resolve()
DEPTH_KM = 4.5
LAT = (-56, 76)
WIDTH_IN = 3.05
CBAR_IN = 0.42
GRAD_RANGE, GRAD_TICKS = (15, 60), [15, 30, 45, 60]
CAPEX_RANGE, CAPEX_TICKS = (7000, 26000), [7500, 15000, 25000]   # 1-99 % of cells: 7,100-25,300 per net kW
NODATA = "#e6e6e6"   # land without a value (no feasible EGS reservoir)


def raster(lon, lat, values, step):
    lons = np.arange(-180 + step / 2, 180, step)
    lats = np.arange(-90 + step / 2, 90, step)
    arr = np.full((len(lats), len(lons)), np.nan)
    i = np.round((np.asarray(lat) - lats[0]) / step).astype(int)
    k = np.round((np.asarray(lon) - lons[0]) / step).astype(int)
    arr[i, k] = values
    return lons, lats, arr


def tinted(name, start=0.15):
    if start == 0:
        return plt.get_cmap(name)
    base = plt.get_cmap(name)
    return LinearSegmentedColormap.from_list(f"{name}_tinted", base(np.linspace(start, 1, 256)))


def draw(lons, lats, arr, world, cmap, norm, label, ticks, out, extend, start=0.15, sites=()):
    plt.rcParams.update({"font.size": 7, "font.family": "serif", "axes.linewidth": 0.4,
                         "mathtext.fontset": "dejavuserif"})
    map_h = WIDTH_IN * (LAT[1] - LAT[0]) / 360
    H = map_h + CBAR_IN
    fig = plt.figure(figsize=(WIDTH_IN, H))
    ax = fig.add_axes([0.0, CBAR_IN / H, 1.0, map_h / H])
    world.plot(ax=ax, color=NODATA, edgecolor="none")
    m = ax.pcolormesh(lons, lats, np.ma.masked_invalid(arr), cmap=tinted(cmap, start), norm=norm, shading="nearest",
                      rasterized=True)
    for lon, lat, name in sites:                       # validation sites: red ring, named in a small legend
        ax.plot(lon, lat, marker="o", markersize=4.2, markerfacecolor="none", markeredgecolor="#d62728",
                markeredgewidth=1.0, zorder=5, linestyle="", label=name)
    if sites:
        ax.legend(loc="lower left", bbox_to_anchor=(0.0, 0.02), frameon=True, framealpha=0.9, edgecolor="none",
                  fontsize=6, handletextpad=0.3, borderpad=0.3, borderaxespad=0.2)
    ax.set_xlim(-180, 180)
    ax.set_ylim(*LAT)
    ax.axis("off")
    cax = fig.add_axes([0.2, 0.30 / H, 0.6, 0.055 / H])
    cb = fig.colorbar(m, cax=cax, orientation="horizontal", extend=extend, ticks=ticks)
    cb.ax.minorticks_off()
    cb.ax.set_xticklabels([f"{t:,g}" for t in ticks])
    cb.outline.set_linewidth(0.3)
    cb.ax.tick_params(width=0.3, length=2, pad=1.5)
    cb.set_label(label, labelpad=1.5)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=300)
    plt.close(fig)


def main():
    step = CFG["grid"]["step_deg"]
    world = gpd.read_file(COUNTRIES)
    world = world[world["CONTINENT"] != "Antarctica"]
    g = xr.open_dataset(GRID)
    t = g["t_c"].sel(depth=DEPTH_KM).values
    grad = (t - g["t_surface_c"].values) / DEPTH_KM
    lons, lats, arr = raster(g["lon"].values, g["lat"].values, grad, step)
    draw(lons, lats, arr, world, "Reds", Normalize(*GRAD_RANGE),
         f"Mean geothermal gradient to {DEPTH_KM:g} km (°C/km)", GRAD_TICKS, OUT_GRAD, "both")
    pot = pd.read_csv(POT, usecols=["lon", "lat", "capex_usd_per_kw"])
    lons, lats, arr = raster(pot["lon"], pot["lat"], pot["capex_usd_per_kw"].values, step)
    sites = [(v["lon"], v["lat"], v["name"]) for v in CFG.get("site_checks", {}).values()]
    draw(lons, lats, arr, world, "viridis_r", LogNorm(*CAPEX_RANGE),
         "EGS CAPEX at the cheapest depth (USD$_{2024}$/kW)", CAPEX_TICKS, OUT_CAPEX, "both", start=0, sites=sites)
    print(f"gradient median {np.nanmedian(grad):.1f} degC/km; CAPEX median {pot['capex_usd_per_kw'].median():,.0f} "
          f"USD/kW over {len(pot):,} feasible cells -> {OUT_GRAD.parent}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
