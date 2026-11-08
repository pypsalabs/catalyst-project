"""The layer stack of one country model, drawn for Brazil (the figure beside the introduction of the Model section).

Seven plates in oblique projection, one per data layer, bottom to top in the order of the Model subsections: the
transmission grid (base network lines, HVDC in red), demand (mean load per base bus), weather (annual mean onshore-wind capacity factor), the existing
fleet without hydro, the hydropower plants, the costs and technology assumptions (CAPEX bars of six technologies from
technology_assumptions.csv) and the fuel costs (one price per fuel and country: a flat tint). Every plate shows the real
data of the Brazil stage; the figure is a schematic, so the weather plate uses the tracked 0.5 degree capacity-factor
grid of the technology-assumptions document (ERA5 2011) rather than the model's 2013 cutout.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_layers.py [--out build/figures/layers.pdf]
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely
import xarray as xr
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import PathPatch, Polygon
from matplotlib.path import Path as MPath

TOP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402

FORK = TOP / "../../models/pypsa-earth"
DEFAULTS = dict(
    network=FORK / "networks/BR/base.nc",
    shape=FORK / "resources/BR/shapes/country_shapes.geojson",
    plants=FORK / "resources/BR-now/powerplants.csv",
    demand=FORK / "resources/BR-now/demand_profiles.csv",
    cf=TOP / "../technology-assumptions/data/resource_cf_2011.nc",
    csv=TOP / "../technology-assumptions/technology_assumptions.csv",
)
# plates bottom -> top: (title, one-line content note)
LAYERS = [
    ("Grid", "OSM lines from 200 kV, HVDC"),
    ("Demand", "hourly load per bus"),
    ("Renewables & weather", "ERA5 capacity factors"),
    ("Existing fleet", "plants by fuel, 2024"),
    ("Hydropower", "plants and inflow"),
    ("Costs & technologies", "CAPEX, O&M, lifetimes"),
    ("Fuel costs", "one price per fuel"),
]
SKEW, DEPTH, TILT = 0.55, 0.42, 0.10   # oblique projection: x = u + SKEW v, y = DEPTH v - TILT u
GAP = 0.56                             # vertical pitch between plates (a plate spans 0.52 in y)
THICK = 0.035                          # drawn thickness of a plate
FLEET = {  # existing fleet colours by powerplantmatching fuel type (hydro has its own plate)
    "Wind": ic.TEAL, "Solar": ic.GOLD, "CCGT": ic.AMBER, "OCGT": ic.AMBER, "Natural Gas": ic.AMBER,
    "Solid Biomass": ic.STEEL, "Biogas": ic.STEEL, "Waste": ic.STEEL, "Oil": ic.MUTED, "Hard Coal": ic.INK,
    "Lignite": ic.INK, "Nuclear": ic.VIOLET,
}
COST_TECHS = ["solar-utility", "onwind", "CCGT", "nuclear-lwr-row", "egs", "nuclear-gen4"]


class Plate:
    """Maps lon/lat of the country into plate k of the stack."""

    def __init__(self, bounds):
        x0, y0, x1, y1 = bounds
        self.x0, self.y0 = x0, y0
        self.scale = 1 / max(x1 - x0, y1 - y0)

    def __call__(self, lon, lat, k):
        u = (np.asarray(lon) - self.x0) * self.scale
        v = (np.asarray(lat) - self.y0) * self.scale
        return u + SKEW * v, DEPTH * v - TILT * u + k * GAP


def uv(u, v, k):
    u, v = np.asarray(u, float), np.asarray(v, float)
    return u + SKEW * v, DEPTH * v - TILT * u + k * GAP


def draw_plate(ax, k, z):
    """Slab outline of plate k: top face (white), front and right edge faces (steel)."""
    corners = np.array([uv(u, v, k) for u, v in [(0, 0), (1, 0), (1, 1), (0, 1)]])
    a, b, c = corners[0], corners[1], corners[2]
    t = np.array([0, -THICK])
    for face in ([a, b, b + t, a + t], [b, c, c + t, b + t]):
        ax.add_patch(Polygon(face, closed=True, fc=ic.STEEL_L, ec=ic.INK, lw=ic.SEAM, joinstyle="miter", zorder=z))
    ax.add_patch(Polygon(corners, closed=True, fc="white", ec=ic.INK, lw=ic.MARK, joinstyle="miter", zorder=z + 0.1))
    return corners


def country_patch(geom, proj, k, **kw):
    """The country polygon(s) on plate k as one PathPatch (holes respected)."""
    verts, codes = [], []
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    for poly in polys:
        for ring in [poly.exterior, *poly.interiors]:
            x, y = proj(*np.asarray(ring.coords).T, k)
            verts += list(zip(x, y))
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(x) - 2) + [MPath.CLOSEPOLY]
    return PathPatch(MPath(verts, codes), **kw)


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    for key, val in DEFAULTS.items():
        p.add_argument(f"--{key}", default=val)
    p.add_argument("--out", default=TOP / "build/figures/layers.pdf")
    a = p.parse_args(snakemake_args() if "snakemake" in globals() else None)

    ic.use()
    geom = shapely.union_all(gpd.read_file(a.shape).geometry.values).simplify(0.05)
    geom = max(geom.geoms, key=lambda g: g.area) if geom.geom_type == "MultiPolygon" else geom   # mainland only
    minx, miny, maxx, maxy = geom.bounds
    pad = 0.04 * max(maxx - minx, maxy - miny)
    proj = Plate((minx - pad, miny - pad, maxx + pad, maxy + pad))

    xlim = (-0.30, 2.92)
    ylim = (-0.14 - THICK, (len(LAYERS) - 1) * GAP + DEPTH + 0.04)
    width = 2.95   # inches; the height follows from the drawing (equal aspect)
    fig = plt.figure(figsize=(width, width * (ylim[1] - ylim[0]) / (xlim[1] - xlim[0])))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.grid(False)

    for k, (title, note) in enumerate(LAYERS):
        z = 10 * k
        corners = draw_plate(ax, k, z)
        land = country_patch(geom, proj, k, fc=ic.PALE, ec=ic.MUTED, lw=0.45, zorder=z + 0.2)
        ax.add_patch(land)
        clip = country_patch(geom, proj, k, transform=ax.transData)

        if title == "Grid":
            ds = xr.open_dataset(a.network)
            bx = pd.Series(ds.buses_x.values, ds.buses_i.values)
            by = pd.Series(ds.buses_y.values, ds.buses_i.values)
            for comp, col in (("lines", ic.INK), ("links", ic.RED)):
                b0, b1 = ds[f"{comp}_bus0"].values, ds[f"{comp}_bus1"].values
                if comp == "links":
                    keep = ds.links_carrier.values == "DC"
                    b0, b1 = b0[keep], b1[keep]
                    lw = 0.9
                else:
                    lw = np.where(ds.lines_v_nom.values >= 500, 0.55, 0.25)
                x0, y0 = proj(bx[b0].values, by[b0].values, k)
                x1, y1 = proj(bx[b1].values, by[b1].values, k)
                segs = np.stack([np.c_[x0, y0], np.c_[x1, y1]], axis=1)
                lc = matplotlib.collections.LineCollection(segs, colors=col, linewidths=lw, zorder=z + 0.4 + (comp == "links"),
                                                           capstyle="round")
                ax.add_collection(lc)
        elif title == "Demand":
            ds = xr.open_dataset(a.network)
            bx = pd.Series(ds.buses_x.values, ds.buses_i.values.astype(str))
            by = pd.Series(ds.buses_y.values, ds.buses_i.values.astype(str))
            load = pd.read_csv(a.demand, index_col=0).mean().sort_values()   # mean MW per base bus, small on top last
            load = load[load.index.isin(bx.index)].iloc[::-1]
            x, y = proj(bx[load.index].values, by[load.index].values, k)
            sc = ax.scatter(x, y, s=load.values ** 0.5 * 0.16, color=ic.VIOLET, ec=ic.INK, lw=0.2, alpha=0.9,
                            zorder=z + 0.4)
            sc.set_clip_path(clip)
        elif title == "Renewables & weather":
            ds = xr.open_dataset(a.cf)
            cf = ds.cf.sel(tech="onwind")
            cf = cf.sel(x=slice(minx - 1, maxx + 1), y=slice(miny - 1, maxy + 1)) if cf.y[0] < cf.y[-1] else \
                cf.sel(x=slice(minx - 1, maxx + 1), y=slice(maxy + 1, miny - 1))
            x, y = cf.x.values, cf.y.values
            dx, dy = abs(x[1] - x[0]), abs(y[1] - y[0])
            xe = np.r_[x - dx / 2, x[-1] + dx / 2] if x[0] < x[-1] else None
            ye = np.r_[y - np.sign(y[1] - y[0]) * dy / 2, y[-1] + np.sign(y[1] - y[0]) * dy / 2]
            LON, LAT = np.meshgrid(xe, ye)
            X, Y = proj(LON, LAT, k)
            cmap = LinearSegmentedColormap.from_list("w", ["#eef3f8", "#9fbfdd", ic.BLUE, "#163d68"])
            m = ax.pcolormesh(X, Y, cf.values, cmap=cmap, vmin=0.02, vmax=0.35, shading="flat", zorder=z + 0.3,
                              rasterized=True, lw=0)
            m.set_clip_path(clip)
        elif title in ("Existing fleet", "Hydropower"):
            pp = pd.read_csv(a.plants, index_col=0)
            pp = pp[pp.Fueltype == "Hydro"] if title == "Hydropower" else pp[pp.Fueltype.isin(FLEET)]
            pp = pp[pp.Capacity >= 30].sort_values("Capacity", ascending=False)   # small plants would only add clutter
            x, y = proj(pp.lon.values, pp.lat.values, k)
            col = ic.BLUE if title == "Hydropower" else pp.Fueltype.map(FLEET).values
            sc = ax.scatter(x, y, s=pp.Capacity.values ** 0.5 * 0.11, c=col, ec=ic.INK, lw=0.2,
                            zorder=z + 0.4)
            sc.set_clip_path(clip)
        elif title == "Costs & technologies":
            rows = pd.read_csv(a.csv).set_index("technology")
            capex = rows.loc[COST_TECHS, "capex_power_usd_kw"].astype(float)
            h = 0.28 * (capex / capex.max()) ** 0.5   # square root: the cheap technologies stay visible
            for i, (t, hi) in enumerate(h.items()):
                bx_, by_ = uv(0.30 + 0.09 * i, 0.42, k)
                w = 0.05
                ax.add_patch(Polygon([(bx_ - w / 2, by_), (bx_ + w / 2, by_), (bx_ + w / 2, by_ + hi), (bx_ - w / 2, by_ + hi)],
                                     closed=True, fc=ic.CATEGORICAL[i], ec=ic.INK, lw=0.5, joinstyle="miter",
                                     zorder=z + 0.5 + i * 0.01))
        elif title == "Fuel costs":
            land.set_facecolor("#f6d9bd")

        # label to the right of the plate's right corner
        rx, ry = corners[2][0] + 0.07, (corners[1][1] + corners[2][1]) / 2
        ax.text(rx, ry + 0.035, title, ha="left", va="bottom", fontsize=7.4, color=ic.INK, weight=ic.EMPH, zorder=200)
        ax.text(rx, ry + 0.01, note, ha="left", va="top", fontsize=6.2, color=ic.MUTED, zorder=200)

    # bracket on the left: the stack is one PyPSA network, optimised as one problem
    xb = -0.10
    yb0, yb1 = -THICK, (len(LAYERS) - 1) * GAP + DEPTH
    ax.plot([xb + 0.04, xb, xb, xb + 0.04], [yb0, yb0, yb1, yb1], color=ic.INK, lw=ic.MARK, solid_joinstyle="miter")
    ax.text(xb - 0.05, (yb0 + yb1) / 2, "one PyPSA network, solved as one linear programme",
            rotation=90, ha="right", va="center", fontsize=6.4, color=ic.MUTED)

    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=400)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=250)
    print(f"-> {a.out}")


def snakemake_args():
    args = []
    for key in DEFAULTS:
        args += [f"--{key}", str(snakemake.input[key])]
    return args + ["--out", str(snakemake.output[0])]


if __name__ == "__main__" or "snakemake" in globals():
    main()
