"""Figures for the EGS dataset.

  figures/egs_maps.{png,pdf}            four global maps: reservoir temperature at 4.5 km,
                                        LCOE-optimal depth, CAPEX, LCOE (cheapest feasible depth)
  figures/egs_supply_curves.{png,pdf}   cumulative developable capacity vs LCOE for the modelled
                                        regions, plus the IEA/InnerSpace comparison groups
Standalone: python plot_maps.py
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
from matplotlib.colors import BoundaryNorm, ListedColormap

HERE = Path(__file__).parent
if "snakemake" in globals():
    CFG = snakemake.config
    GRID, POT, CURVES = Path(snakemake.input.grid), Path(snakemake.input.potential), Path(snakemake.input.curves)
    OUT_MAPS = [Path(f) for f in snakemake.output.maps]
    OUT_SC = [Path(f) for f in snakemake.output.curves]
else:
    CFG = yaml.safe_load((HERE / "config.yaml").read_text())
    GRID, POT, CURVES = (HERE / "build" / f for f in ("egs_grid.nc", "egs_potential.csv", "egs_supply_curves.csv"))
    OUT_MAPS = [HERE / "figures" / f"egs_maps.{f}" for f in CFG["plotting"]["formats"]]
    OUT_SC = [HERE / "figures" / f"egs_supply_curves.{f}" for f in CFG["plotting"]["formats"]]

# perceptually uniform, colourblind-safe multi-hue sequential ramps (matplotlib): the single-hue
# blue ramp did not separate neighbouring classes enough on a global map
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, MUTED, GRIDC, SURFACE = "#0b0b0b", "#52514e", "#dcdcdc", "#fcfcfb"
LAND = "#efeeea"


def raster(df, col, step):
    lons = np.arange(-180 + step / 2, 180, step)
    lats = np.arange(-90 + step / 2, 90, step)
    arr = np.full((len(lats), len(lons)), np.nan)
    i = np.round((df["lat"].values - lats[0]) / step).astype(int)
    k = np.round((df["lon"].values - lons[0]) / step).astype(int)
    arr[i, k] = df[col].values
    return lons, lats, arr


def classed(name, n, reverse=False):
    """n evenly spaced colours of a matplotlib colormap as a discrete ListedColormap."""
    cm = matplotlib.colormaps[name]
    cols = cm(np.linspace(0.15, 0.95, n))
    return ListedColormap(cols[::-1] if reverse else cols)


def draw_map(ax, lons, lats, arr, cmap, norm, world, title, cbar_label, ticks=None, ticklabels=None):
    world.plot(ax=ax, color=LAND, edgecolor="none")
    step = lons[1] - lons[0]
    im = ax.pcolormesh(np.append(lons - step / 2, lons[-1] + step / 2), np.append(lats - step / 2, lats[-1] + step / 2),
                       np.ma.masked_invalid(arr), cmap=cmap, norm=norm, shading="flat", rasterized=True)
    world.boundary.plot(ax=ax, color="white", linewidth=0.25)
    ax.set_xlim(-180, 180); ax.set_ylim(-58, 84); ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(title, fontsize=10, color=INK, loc="left")
    cb = plt.colorbar(im, ax=ax, orientation="horizontal", fraction=0.04, pad=0.02, aspect=45)
    cb.set_label(cbar_label, fontsize=8, color=MUTED)
    cb.ax.tick_params(labelsize=7, colors=MUTED)
    cb.outline.set_visible(False)
    if ticks is not None:
        cb.set_ticks(ticks)
        if ticklabels is not None:
            cb.set_ticklabels(ticklabels)


def maps():
    step = CFG["grid"]["step_deg"]
    g = xr.open_dataset(GRID)
    pot = pd.read_csv(POT, dtype={"admin1": str, "iso3": str})
    world = gpd.read_file((HERE / CFG["archetype_data_dir"] / "ne_50m_admin_0_countries" / "ne_50m_admin_0_countries.shp").resolve())
    cells = pd.DataFrame({"lon": g["lon"].values, "lat": g["lat"].values, "t45": g["t_c"].sel(depth=4.5).values})
    fig, axes = plt.subplots(2, 2, figsize=(15, 9.2))
    fig.patch.set_facecolor(SURFACE)
    axes = axes.ravel()
    e = CFG["egs"]
    year = CFG["base_currency_year"]

    b = [50, 100, 150, 200, 250, 300, 400]
    draw_map(axes[0], *raster(cells, "t45", step), classed("inferno", len(b) - 1), BoundaryNorm(b, len(b) - 1),
             world, "a  Rock temperature at 4.5 km depth", "°C (1-D conduction on Lucazeau heat flow; Stanford model over CONUS)")
    depths = CFG["grid"]["depths_km"]
    b = [d - 0.5 for d in depths] + [depths[-1] + 0.5]
    draw_map(axes[1], *raster(pot, "depth_km", step), classed("viridis", len(depths), reverse=True), BoundaryNorm(b, len(depths)),
             world, f"b  LCOE-optimal depth where the reservoir reaches {e['t_min_c']} °C", "km", ticks=depths)
    b = [3000, 4000, 5000, 6000, 8000, 10000, 12000, 15000, 20000, 30000]
    draw_map(axes[2], *raster(pot, "capex_usd_per_kw", step), classed("viridis", len(b) - 1), BoundaryNorm(b, len(b) - 1),
             world, f"c  EGS CAPEX at that depth (surface plant + wellfield, incl. interest during construction)",
             f"USD{year}/kW", ticks=b, ticklabels=[f"{x / 1000:g}k" for x in b])
    b = [50, 75, 100, 125, 150, 200, 250, 300, 400, 600]
    draw_map(axes[3], *raster(pot, "lcoe_usd_per_mwh", step), classed("viridis", len(b) - 1), BoundaryNorm(b, len(b) - 1),
             world, f"d  LCOE ({e['wacc']:.0%} real WACC, {e['lifetime_years']} y, CF {e['capacity_factor']:.0%}, no grid connection)",
             f"USD{year}/MWh", ticks=b)
    fig.suptitle("Enhanced geothermal systems: cost model of Ricks & Jenkins (Joule 2025) on a global temperature-at-depth grid "
                 f"({step}°, {len(pot):,} feasible land cells)", fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    for f in OUT_MAPS:
        f.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(f, dpi=CFG["plotting"]["dpi"], facecolor=SURFACE)
    plt.close(fig)


def supply_curves():
    pot = pd.read_csv(POT, dtype={"admin1": str, "iso3": str})
    from aggregate_regions import region_masks   # same region definitions as the tables
    masks, names = region_masks(pot)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    groups = [("Modelled archetype regions", [r for r in CFG["modelled_regions"] if r in masks]),
              ("Comparison groups of the IEA Future of Geothermal (2024)", ["USA", "CHN", "AFRICA", "ASEAN", "EUROPE", "IND", "CSAMERICA"])]
    for ax, (title, regs) in zip(axes, groups):
        for c, r in zip(CAT, regs):
            if r not in masks:
                continue
            sub = pot[masks[r]].sort_values("lcoe_usd_per_mwh")
            if sub.empty:
                continue
            x = np.cumsum(sub["capacity_mw"].values) / 1000
            y = sub["lcoe_usd_per_mwh"].values
            ax.step(x, y, where="post", color=c, lw=2, label=names.get(r, r))
        ax.set_xscale("log")
        ax.set_ylim(0, 400)
        ax.set_xlim(1, 3e5)
        ax.set_xlabel("cumulative developable capacity (GW)", fontsize=9, color=MUTED)
        ax.set_title(title, fontsize=10, color=INK, loc="left")
        ax.grid(axis="y", color=GRIDC, lw=0.6)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(labelsize=8, colors=MUTED)
        ax.legend(fontsize=8, frameon=False, loc="upper left")
        ax.set_facecolor(SURFACE)
    axes[0].set_ylabel(f"LCOE (USD{CFG['base_currency_year']}/MWh)", fontsize=9, color=MUTED)
    e = CFG["egs"]
    fig.suptitle(f"EGS supply curves at the cheapest feasible depth (≤ {max(CFG['grid']['depths_km'])} km, ≥ {e['t_min_c']} °C, "
                 f"land as for onshore wind; {e['wacc']:.0%} WACC, {e['lifetime_years']} y, no grid connection)",
                 fontsize=10, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    for f in OUT_SC:
        f.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(f, dpi=CFG["plotting"]["dpi"], facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__" or "snakemake" in globals():
    import sys
    sys.path.insert(0, str(HERE))
    maps()
    supply_curves()
