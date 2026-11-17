"""EGS as the model sees it in one region: maps of the techno-economics and the supply-curve tranches.

    cd models/pypsa-earth
    pixi run python ../../misc-quarter1/geothermal/plot_model_egs.py JP-cfe Japan

  figures/egs_model_<R>.{png,pdf}   (<R> = the stage's base run, e.g. JP); study plot style (plotstyle/studystyle.py)
      a  reservoir temperature at the cost-optimal depth (deg C, capped at 250)
      b  that depth (km)
      c  developable capacity per 0.25 degree cell (MW): land availability x developable_share
      d  the supply-curve tranche every cell falls into (what the model may build, and at what CAPEX)
      e  the supply curve: cells sorted by CAPEX, with the tranches as blocks split into power plant and
         wellfield (the two learning components)

Inputs: build/egs_potential.csv (this workflow), the `supply_curves: egs:` block of
config-pypsa-earth/overlay.myopic.yaml (capex_bins, tranches, developable_share, filter), the stage's cluster
regions (models/pypsa-earth/resources/<stage>/bus_regions/regions_onshore_elec_s_<n>.geojson) and, as a check,
its supply_curve_egs_*.nc: the tranches are rebuilt here with the binning of the fork's
scripts/build_supply_curve.py and must reproduce the file's p_nom_max. Needs geopandas (the fork's pixi env).
"""

import sys
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
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as MPath

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "plotstyle").is_dir())
sys.path.insert(0, str(ROOT / "plotstyle"))
import studystyle as st  # noqa: E402

PE = ROOT / "models" / "pypsa-earth"
NE = ROOT / "misc-quarter1" / "country-classification" / "data" / "ne_50m_admin_0_countries" / "ne_50m_admin_0_countries.shp"
STEP = 0.25


def model_cells(stage):
    """Cells of the stage's supply curve with their tranche (cheapest = 0), and the cells left out."""
    cfg = yaml.safe_load((ROOT / "config-pypsa-earth" / "overlay.myopic.yaml").read_text())["supply_curves"]["egs"]
    regions = gpd.read_file(next(f for f in sorted((PE / "resources" / stage / "bus_regions").glob("regions_onshore_elec_s_*.geojson"))))
    cells = pd.read_csv(HERE / "build" / "egs_potential.csv")
    box = regions.to_crs(4326).total_bounds
    cells = cells[cells.lon.between(box[0] - 1, box[2] + 1) & cells.lat.between(box[1] - 1, box[3] + 1)].copy()
    pts = gpd.GeoDataFrame(cells[["lon", "lat"]], geometry=gpd.points_from_xy(cells.lon, cells.lat), crs=4326)
    inside = gpd.sjoin(pts, regions[["geometry"]].to_crs(4326), how="left", predicate="within")
    cells["inside"] = inside[~inside.index.duplicated()]["index_right"].reindex(cells.index).notna()
    cells["capex"] = sum(cells[c] for c in cfg["components"].values())
    cells["capacity"] = cells["capacity_mw"] * float(cfg["developable_share"])
    ok = cells.inside & (cells.capacity > 0)
    if cfg.get("filter"):
        ok &= cells.index.isin(cells.query(cfg["filter"]).index)
    # the binning of the fork's build_supply_curve.py (tranche_cells / merge_bins)
    edges, bins = list(cfg["capex_bins"]), []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = cells.index[ok & (cells.capex >= lo) & (cells.capex < hi)]
        if len(sel) and cells.loc[sel, "capacity"].sum() > 0:
            bins.append(dict(cells=list(sel), capacity=cells.loc[sel, "capacity"].sum(), lo=lo, hi=hi))
    while len(bins) > int(cfg["tranches"]):
        k = int(np.argmin([bins[i]["capacity"] + bins[i + 1]["capacity"] for i in range(len(bins) - 1)]))
        a, b = bins[k], bins[k + 1]
        bins[k:k + 2] = [dict(cells=a["cells"] + b["cells"], capacity=a["capacity"] + b["capacity"], lo=a["lo"], hi=b["hi"])]
    cells["tranche"] = np.nan
    for k, b in enumerate(bins):
        cells.loc[b["cells"], "tranche"] = k
    return cells[cells.inside].copy(), bins, cfg, regions.to_crs(4326)


def check(cells, stage):
    f = next((PE / "resources" / stage / "supply_curves").glob("supply_curve_egs_*.nc"))
    ref = xr.open_dataset(f).p_nom_max.values.ravel()
    mine = cells.dropna(subset=["tranche"]).groupby("tranche").capacity.sum().to_numpy()
    if len(ref) != len(mine) or not np.allclose(ref, mine, rtol=1e-3):
        raise SystemExit(f"tranches rebuilt here do not match {f}:\n  file {ref}\n  here {mine}")
    print(f"tranches match {f.name}: {np.round(mine / 1e3, 2)} GW")


def raster(df, col, ext):
    lons = np.arange(ext[0], ext[1] + STEP / 2, STEP)
    lats = np.arange(ext[2], ext[3] + STEP / 2, STEP)
    arr = np.full((len(lats) - 1, len(lons) - 1), np.nan)
    i = np.floor((df.lat.to_numpy() - ext[2]) / STEP).astype(int)
    k = np.floor((df.lon.to_numpy() - ext[0]) / STEP).astype(int)
    arr[i, k] = df[col].to_numpy()
    return lons, lats, np.ma.masked_invalid(arr)


def land_path(geom):
    verts, codes = [], []
    for poly in getattr(geom, "geoms", [geom]):
        for ring in [poly.exterior, *poly.interiors]:
            xy = np.asarray(ring.coords)
            verts.extend(xy)
            codes.extend([MPath.MOVETO] + [MPath.LINETO] * (len(xy) - 2) + [MPath.CLOSEPOLY])
    return MPath(np.asarray(verts), codes)


def draw_map(ax, cells, col, ext, land, cmap, norm, title):
    path = land_path(land)
    ax.add_patch(PathPatch(path, facecolor=st.LAND, edgecolor="none", zorder=1))
    lons, lats, arr = raster(cells.dropna(subset=[col]), col, ext)
    mesh = ax.pcolormesh(lons, lats, arr, cmap=cmap, norm=norm, zorder=2, rasterized=True)
    mesh.set_clip_path(PathPatch(path, transform=ax.transData))
    ax.add_patch(PathPatch(path, facecolor="none", edgecolor=st.TEXT, linewidth=0.5, zorder=3))
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_aspect(1 / np.cos(np.deg2rad((ext[2] + ext[3]) / 2)))
    ax.set_anchor("NW")
    ax.set_title(title, loc="left")
    st.map_axes(ax)
    return mesh


def colorbar(fig, ax, mesh, label, ticks=None):
    """Colour bar in the empty sea at the lower right of a map panel, labelled with quantity and unit."""
    return st.colorbar(fig, mesh, ax.inset_axes([0.50, 0.10, 0.44, 0.030]), label, ticks=ticks)


def main(stage, name):
    st.use()
    cells, bins, cfg, regions = model_cells(stage)
    check(cells, stage)
    used = cells.dropna(subset=["tranche"])
    ext = [np.floor(used.lon.min()) - 1, np.ceil(used.lon.max()) + 1, np.floor(used.lat.min()) - 1, np.ceil(used.lat.max()) + 1]
    ne = gpd.read_file(NE)
    iso = used.iso3.mode().iloc[0]
    land = ne[ne.ADM0_A3 == iso].geometry.union_all().intersection(regions.union_all().buffer(0.5))

    n = len(bins)
    tcol = [matplotlib.colors.to_hex(c) for c in plt.get_cmap("YlOrBr_r")(np.linspace(0.05, 0.78, max(n, 2)))][:n]

    fig = plt.figure(figsize=(11.0, 8.4), layout="none")   # laid out by hand (map aspect, inset colour bars)
    gs = fig.add_gridspec(2, 3, left=0.03, right=0.985, top=0.90, bottom=0.085, wspace=0.04, hspace=0.20)
    fig.suptitle(f"Enhanced geothermal in the model: {name}", x=0.03, y=0.975, ha="left", fontsize=11, fontweight="bold", color=st.TEXT)

    ax = fig.add_subplot(gs[0, 0])
    m = draw_map(ax, cells, "t_reservoir_c", ext, land, "YlOrRd", plt.Normalize(100, 250),
                 "Reservoir temperature at the chosen depth")
    colorbar(fig, ax, m, "reservoir temperature, \N{DEGREE SIGN}C", ticks=[100, 150, 200, 250])
    ax = fig.add_subplot(gs[0, 1])
    m = draw_map(ax, cells, "depth_km", ext, land, "viridis_r", plt.Normalize(2.5, 6.5), "Cost-optimal drilling depth")
    colorbar(fig, ax, m, "drilling depth, km", ticks=[2.5, 3.5, 4.5, 5.5, 6.5])
    ax = fig.add_subplot(gs[0, 2])
    top = float(np.ceil(used.capacity.quantile(0.98) / 50) * 50)
    m = draw_map(ax, cells.assign(capacity=cells.capacity.where(cells.capacity > 0)), "capacity", ext, land, "cividis_r",
                 plt.Normalize(0, top), f"Developable capacity ({cfg['developable_share']:.0%} of the available land)")
    colorbar(fig, ax, m, "MW per 0.25\N{DEGREE SIGN} cell")

    ax = fig.add_subplot(gs[1, 0])
    draw_map(ax, cells, "tranche", ext, land, ListedColormap(tcol), BoundaryNorm(np.arange(-0.5, n), n),
             "Supply-curve tranche of each cell")
    handles = [Patch(facecolor=c, edgecolor="none",
                     label=f"{b['lo']:,.0f}\N{EN DASH}{b['hi']:,.0f}   {b['capacity'] / 1e3:,.1f} GW")
               for c, b in zip(tcol, bins)]
    out = cells[cells.tranche.isna()]
    if len(out):
        handles.append(Patch(facecolor=st.LAND, edgecolor="none", label="not in the model"))
    leg = ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, 0.97), handlelength=0.9, handleheight=0.9,   # the empty sea, top left
                    labelspacing=0.45, borderaxespad=0, title="CAPEX, USD2024 per kW   capacity", title_fontsize=7.5, alignment="left")
    leg.get_title().set_color(st.LABEL)

    # e: the supply curve, cells as a step line, tranches as blocks (power plant below, wellfield on top)
    ax = fig.add_subplot(gs[1, 1:])
    pos = ax.get_position()
    ax.set_position([pos.x0 + 0.045, pos.y0 + 0.02, pos.width - 0.05, pos.height - 0.07])
    x0 = 0.0
    for k, (b, c) in enumerate(zip(bins, tcol)):
        g = used.loc[b["cells"]]
        w = g.capacity / g.capacity.sum()
        plant, well = float((g.plant_capex_usd_per_kw * w).sum()), float((g.well_capex_usd_per_kw * w).sum())
        lcoe, gw = float((g.lcoe_usd_per_mwh * w).sum()), b["capacity"] / 1e3
        ax.bar(x0, plant, width=gw, align="edge", color=st.NEUTRAL, edgecolor="white", linewidth=0.6, zorder=2)
        ax.bar(x0, well, width=gw, bottom=plant, align="edge", color=c, edgecolor="white", linewidth=0.6, zorder=2)
        if gw > 12:
            ax.annotate(f"{plant + well:,.0f}\n{lcoe:,.0f} USD/MWh\n{gw:,.1f} GW", (x0 + gw / 2, plant + well), xytext=(0, 5),
                        textcoords="offset points", ha="center", va="bottom", fontsize=7.5, color=st.TEXT, linespacing=1.25)
        else:   # a sliver of a tranche: label it to the side with a leader
            ax.annotate(f"{plant + well:,.0f}, {lcoe:,.0f} USD/MWh, {gw:,.1f} GW", (x0 + gw / 2, plant + well), xytext=(14, 62),
                        textcoords="offset points", ha="left", va="bottom", fontsize=7.5, color=st.TEXT,
                        arrowprops=dict(arrowstyle="-", color=st.TEXT, lw=0.6, shrinkA=1, shrinkB=0))
        x0 += gw
    s = used.sort_values("capex")
    xs = np.concatenate([[0], s.capacity.cumsum().to_numpy() / 1e3])
    ax.step(xs, np.concatenate([[s.capex.iloc[0]], s.capex.to_numpy()]), where="pre", color=st.TEXT, lw=0.9, zorder=3)
    ax.set_xlim(0, x0 * 1.02)
    ax.set_ylim(0, cfg["capex_bins"][-1] * 1.12)
    ax.set_yticks(np.arange(2500, cfg["capex_bins"][-1] + 1, 2500))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel("cumulative developable capacity, GW")
    ax.set_title("Supply curve: CAPEX per net kW, USD2024 (2025 costs, before learning)", loc="left")
    st.legend_squares(ax, [(tcol[min(1, n - 1)], "wellfield, colour = tranche"), (st.NEUTRAL, "power plant")], loc="upper left",
                      bbox_to_anchor=(0.0, 0.99))

    fig.text(0.03, 0.022, f"Cells of misc-quarter1/geothermal/build/egs_potential.csv inside the {stage.rsplit('-', 1)[0]} region; "
             f"line = single cells, blocks = the {n} tranches the model can build ({x0:,.0f} GW). Capacity factor 0.85, lifetime 30 a.",
             fontsize=7.5, color=st.TICK)
    for fmt in ("png", "pdf"):
        f = HERE / "figures" / f"egs_model_{stage.rsplit('-', 1)[0]}.{fmt}"
        fig.savefig(f)
        print("wrote", f)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "JP-cfe", sys.argv[2] if len(sys.argv) > 2 else "Japan")
