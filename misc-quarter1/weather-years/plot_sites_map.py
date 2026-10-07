"""World map of the places with weather-year data (misc-quarter1/weather-years): the sites (demand location, label,
Open-Meteo cache coverage of their stencils), their procurable wind and solar resource locations (linked to the site),
the 3 x 3 ERA5 stencil points, and the single-point place of the years dataset. Natural Earth 50 m countries in the
Robinson projection; icon plot style.

Standalone: python plot_sites_map.py
"""

import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402

if "snakemake" in globals():
    CFG = snakemake.config  # noqa: F821
    _HERE = Path(snakemake.input.config).resolve().parent  # noqa: F821
    SITES = Path(snakemake.input.sites)  # noqa: F821
    POINTS = Path(snakemake.input.points)  # noqa: F821
    OUTS = [Path(p) for p in snakemake.output]  # noqa: F821
else:
    _HERE = Path(__file__).resolve().parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    SITES = _HERE / "build" / "sites.csv"
    POINTS = _HERE / "build" / "siteyears_points.csv"
    OUTS = [_HERE / "figures" / f"sites_map.{f}" for f in CFG["plotting"]["formats"]]
OUTS[0].parent.mkdir(parents=True, exist_ok=True)
CACHE = _HERE / "data" / "openmeteo"
ROBINSON = "ESRI:54030"

SY = CFG["siteyears"]
years = list(range(min(SY["first"], SY["calibration_year"]), SY["last"] + 1))
sites = pd.read_csv(SITES)
pts = pd.read_csv(POINTS)
have = {f.name for f in CACHE.glob("pt_*.csv")}
cov = {k: sum(f"pt_{la:.2f}_{lo:.2f}_{y}.csv" in have for la, lo in g[["lat", "lon"]].drop_duplicates().itertuples(index=False) for y in years)
       for k, g in pts.groupby("key")}
need = {k: len(years) * len(g[["lat", "lon"]].drop_duplicates()) for k, g in pts.groupby("key")}
sites["cached"] = sites.key.map(cov)
Y = CFG["years"]
ng_years = sum((CACHE / f"{Y['site']['key']}_{y}.csv").exists() for y in range(Y["first"], Y["last"] + 1))

world = gpd.read_file((_HERE / CFG["world_shapes"]).resolve())
world = world[world.NAME != "Antarctica"].to_crs(ROBINSON)
site_g = gpd.GeoDataFrame(sites, geometry=gpd.points_from_xy(sites.point_x, sites.point_y), crs="EPSG:4326").to_crs(ROBINSON)
res_g = {r: gpd.GeoDataFrame(sites, geometry=gpd.points_from_xy(sites[f"{r}_x"], sites[f"{r}_y"]), crs="EPSG:4326").to_crs(ROBINSON) for r in ("wind", "solar")}
pt_g = gpd.GeoDataFrame(pts, geometry=gpd.points_from_xy(pts.lon, pts.lat), crs="EPSG:4326").to_crs(ROBINSON)
ng = gpd.GeoSeries(gpd.points_from_xy([Y["site"]["lon"]], [Y["site"]["lat"]]), crs="EPSG:4326").to_crs(ROBINSON)

ic.use()
fig, ax = plt.subplots(figsize=(14, 7.2))
world.plot(ax=ax, color=ic.PALE, edgecolor=ic.INK, linewidth=0.35)
pt_g.plot(ax=ax, color=ic.STEEL, markersize=5, zorder=3)
for r, colour in (("wind", ic.BLUE), ("solar", ic.GOLD)):
    g = res_g[r]
    for i in range(len(g)):
        ax.plot([site_g.geometry.x.iloc[i], g.geometry.x.iloc[i]], [site_g.geometry.y.iloc[i], g.geometry.y.iloc[i]], color=ic.MUTED, linewidth=ic.SEAM, zorder=4)
    g.plot(ax=ax, color=colour, edgecolor=ic.INK, linewidth=ic.MARK, markersize=36, zorder=6)
site_g.plot(ax=ax, color=ic.AMBER, edgecolor=ic.INK, linewidth=ic.MARK, markersize=70, zorder=5)
ax.scatter(ng.x, ng.y, s=70, color=ic.VIOLET, edgecolor=ic.INK, linewidth=ic.MARK, zorder=5)

# label placement: alternate sides, nudge known neighbours apart
side = {"fr-south": (-14, -12), "ma": (-14, 8), "ke-naivasha": (12, -10), "sg": (12, 6), "cn-hebei": (12, 10),
        "us-idaho": (-14, 8), "us-texas": (-14, -12), "us-pennsylvania": (12, 8), "br-sergipe": (12, 6), "in-karnataka": (12, -10)}
for _, r in site_g.iterrows():
    dx, dy = side.get(r.key, (12, 6))
    ax.annotate(f"{r.site}\n{r.cached}/{need[r.key]} point-years", (r.geometry.x, r.geometry.y), xytext=(dx, dy),
                textcoords="offset points", fontsize=8, color=ic.INK, ha="left" if dx > 0 else "right", va="center")
ax.annotate(f"{Y['site']['name']}\n{ng_years}/{Y['last'] - Y['first'] + 1} years", (ng.x.iloc[0], ng.y.iloc[0]), xytext=(14, 14),
            textcoords="offset points", fontsize=8, color=ic.INK)
ax.set_title("Places with ERA5 weather years (Open-Meteo archive cache)", loc="left", color=ic.INK)
ax.text(0.0, -0.02, f"amber = the sites (demand); blue / yellow = their procurable wind / solar resource locations (best bus of the grid or a "
        f"hand-placed point), each with a 3 x 3 stencil of 0.25° cells (grey dots), years {years[0]}–{years[-1]} "
        f"({sum(cov.values())} of {sum(need.values())} point-years cached; {SY['calibration_year']} calibrates to the resource bus);  "
        f"violet = single point, {Y['first']}–{Y['last']}", transform=ax.transAxes, fontsize=8, color=ic.MUTED, va="top")
ax.set_axis_off()
xmin, ymin, xmax, ymax = world.total_bounds
ax.set_xlim(xmin, xmax)
ax.set_ylim(-5.5e6, 8.2e6)
for out in OUTS:
    fig.savefig(out, dpi=CFG["plotting"]["dpi"], bbox_inches="tight")
print("wrote", *OUTS)
