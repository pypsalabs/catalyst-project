"""World maps of annual mean capacity factor and the LCOE it implies, for solar PV, onshore and offshore wind.

For each technology two small maps (one PDF each, placed side by side in its section):
build/figures/<technology>_cf.pdf     annual mean capacity factor on land (data/resource_cf_<year>.nc)
build/figures/<technology>_lcoe.pdf   LCOE from that capacity factor and the row's own numbers in
                                      technology_assumptions.csv: (annuity x CAPEX + FOM) / (8760 h x CF) + VOM,
                                      at the real discount rate DISCOUNT_RATE (7 %, as in technology-costs)
Each LCOE map has its own logarithmic colour scale (LCOE ~ 1/CF), chosen so the spread within the
technology stays readable; the scales differ between solar and wind. Colormaps
are single-hue and start at a visible tint, so that the lowest values do not vanish into the white sea. Sea and Antarctica are left
blank (Natural Earth 1:50m countries from misc-quarter1/country-classification).
Offshore wind has no octant of its own: its maps take the onshore wind octant's capacity factor over sea (model.energy's
onshore turbine, a proxy) on cells where at least SHALLOW_MIN of the area is 0-50 m deep (data/offwind_shallow_share.nc,
scripts/build_offshore_mask.py, the fork's offwind max_depth), south of the Arctic circle; land is drawn light grey there
and the colormaps start darker, so the cheapest cells stay visible against it.

Standalone:  python scripts/plot_resource_maps.py [--cf data/resource_cf_2011.nc] [--csv technology_assumptions.csv]
                                                  [--shallow data/offwind_shallow_share.nc]
                                                  [--countries <ne_50m_admin_0_countries.shp>] [--outdir build/figures]
"""

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LogNorm, Normalize
import numpy as np
import pandas as pd
import shapely
import xarray as xr

TOP = Path(__file__).resolve().parents[1]
COUNTRIES = TOP / "../../misc-quarter1/country-classification/data/ne_50m_admin_0_countries/ne_50m_admin_0_countries.shp"
DISCOUNT_RATE = 0.07
LAT = (-56, 76)                       # map extent: no Antarctica, no high Arctic
# USD/MWh, log scale, per technology: (vmin, vmax, ticks)
LCOE_SCALE = {"solar-utility": (25, 100, [25, 35, 50, 70, 100]), "onwind": (30, 300, [30, 50, 100, 200, 300]),
              "offwind": (50, 200, [50, 70, 100, 150, 200])}
CF_RANGE = {"solar-utility": (0.08, 0.26), "onwind": (0.0, 0.6), "offwind": (0.2, 0.65)}
CF_CMAP = {"solar-utility": "Oranges", "onwind": "Blues", "offwind": "Greens"}   # one hue, light -> dark
SHALLOW_MIN = 0.25                    # offshore wind: minimum share of a cell 0-50 m deep
OFFWIND_MAX_LAT = 66.5                # offshore wind: none north of the Arctic circle (sea ice)
LCOE_CMAP = "Purples"
WIDTH_IN = 3.05                       # half of the 160 mm text width, less the gap
WIDTH_SEA_IN = 6.3                    # offshore maps: full text width, one above the other
SEA_MARKER_PT = 1.6                   # offshore cells drawn as squares of this side (a 0.5 deg cell is ~0.6 pt wide)
CBAR_IN = 0.42                        # height below the map for the colour bar, its ticks and label


def annuity(rate, years):
    return rate / (1 - (1 + rate) ** -years)


def lcoe(cf, row, rate=DISCOUNT_RATE):
    f = lambda c: float(row[c]) if str(row[c]).strip() not in ("", "nan") else 0.0
    fixed = annuity(rate, f("lifetime_yr")) * f("capex_power_usd_kw") + f("fom_usd_kw_yr")   # USD/kW/yr
    with np.errstate(divide="ignore", invalid="ignore"):
        return fixed * 1e3 / (8760 * cf) + f("vom_usd_mwh")


def land_mask(countries, x, y):
    world = gpd.read_file(countries)
    world = world[world["CONTINENT"] != "Antarctica"] if "CONTINENT" in world else world
    land = shapely.union_all(world.geometry.values)
    shapely.prepare(land)
    X, Y = np.meshgrid(x, y)
    return shapely.contains_xy(land, X, Y), world


def tinted(name, start=0.15):
    """A matplotlib colormap without its near-white end."""
    base = plt.get_cmap(name)
    return LinearSegmentedColormap.from_list(f"{name}_tinted", base(np.linspace(start, 1, 256)))


def draw(field, x, y, world, cmap, norm, label, ticks, out, extend="neither", land_fill=False, low_is_best=False):
    width = WIDTH_SEA_IN if land_fill else WIDTH_IN
    plt.rcParams.update({"font.size": 7, "font.family": "serif", "axes.linewidth": 0.4,
                         "mathtext.fontset": "dejavuserif"})
    map_h = width * (LAT[1] - LAT[0]) / 360
    H = map_h + CBAR_IN
    fig = plt.figure(figsize=(width, H))
    ax = fig.add_axes([0.0, CBAR_IN / H, 1.0, map_h / H])
    if land_fill:                     # offshore maps: grey land, so the coastal cells read as sea
        world.plot(ax=ax, color="#ececec", linewidth=0)
    if land_fill:                     # the shallow-sea cells form thin coastal strips: enlarged squares keep them visible
        X, Y = np.meshgrid(x, y)
        ok = np.isfinite(field)
        order = np.argsort(-field[ok] if low_is_best else field[ok])   # the best cells on top
        m = ax.scatter(X[ok][order], Y[ok][order], c=field[ok][order], s=SEA_MARKER_PT ** 2, marker="s", linewidths=0,
                       cmap=tinted(cmap, 0.35), norm=norm, rasterized=True, zorder=2)
    else:
        m = ax.pcolormesh(x, y, field, cmap=tinted(cmap), norm=norm, shading="nearest", rasterized=True, zorder=2)
    # offshore maps: hairline coasts and borders, so the shallow-sea cells stand out
    world.boundary.plot(ax=ax, color="#b0b0b0" if land_fill else "#8a8a8a", linewidth=0.05 if land_fill else 0.15, zorder=3)
    ax.set_xlim(-180, 180)
    ax.set_ylim(*LAT)
    ax.axis("off")
    cax = fig.add_axes([0.3, 0.30 / H, 0.4, 0.055 / H] if land_fill else [0.2, 0.30 / H, 0.6, 0.055 / H])
    cb = fig.colorbar(m, cax=cax, orientation="horizontal", extend=extend, ticks=ticks)
    cb.ax.minorticks_off()
    cb.ax.set_xticklabels([f"{t:g}" for t in ticks])
    cb.outline.set_linewidth(0.3)
    cb.ax.tick_params(width=0.3, length=2, pad=1.5)
    cb.set_label(label, labelpad=1.5)
    fig.savefig(out, dpi=300)
    plt.close(fig)


def main():
    if "snakemake" in globals():
        cf_path, shallow_path, csv, countries, outdir = (snakemake.input.cf, snakemake.input.shallow, snakemake.input.csv,
                                                         snakemake.input.countries, Path(snakemake.output[0]).parent)
    else:
        p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
        p.add_argument("--cf", default=TOP / "data/resource_cf_2011.nc")
        p.add_argument("--shallow", default=TOP / "data/offwind_shallow_share.nc")
        p.add_argument("--csv", default=TOP / "technology_assumptions.csv")
        p.add_argument("--countries", default=COUNTRIES)
        p.add_argument("--outdir", default=TOP / "build/figures")
        a = p.parse_args()
        cf_path, shallow_path, csv, countries, outdir = a.cf, a.shallow, a.csv, a.countries, Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ds = xr.open_dataset(cf_path)
    rows = pd.read_csv(csv, dtype=str, keep_default_na=False).set_index("technology")
    x, y = ds.x.values, ds.y.values
    mask, world = land_mask(countries, x, y)
    shallow = xr.open_dataset(shallow_path)["share"].reindex_like(ds, method="nearest").values
    fields = {t: np.where(mask, ds.cf.sel(tech=t).values, np.nan) for t in ds.tech.values}
    sea_ok = ~mask & (shallow >= SHALLOW_MIN) & (y[:, None] <= OFFWIND_MAX_LAT)
    fields["offwind"] = np.where(sea_ok, ds.cf.sel(tech="onwind").values, np.nan)
    for tech, cf in fields.items():
        sea = tech == "offwind"
        lo, hi = CF_RANGE[tech]
        draw(cf, x, y, world, CF_CMAP[tech], Normalize(lo, hi), "Annual mean capacity factor",
             list(np.round(np.linspace(lo, hi, 4), 2)), outdir / f"{tech}_cf.pdf",
             extend="both" if lo > 0 else "max", land_fill=sea)
        cost = lcoe(cf, rows.loc[tech])
        vmin, vmax, ticks = LCOE_SCALE[tech]
        draw(cost, x, y, world, LCOE_CMAP, LogNorm(vmin, vmax),
             f"LCOE at {int(DISCOUNT_RATE * 100)} % real discount rate (USD$_{{2024}}$/MWh)",
             ticks, outdir / f"{tech}_lcoe.pdf", extend="both", land_fill=sea, low_is_best=True)
        land = np.isfinite(cf)
        print(f"{tech}: {'shallow-sea' if sea else 'land'} CF median {np.nanmedian(cf):.3f}, LCOE median {np.nanmedian(cost[land]):.0f} USD/MWh")
    print(f"-> {outdir}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
