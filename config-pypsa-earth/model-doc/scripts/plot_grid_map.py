"""World map of how the grid of each modelled country enters the model (first figure of the Grid Data subsection).

Each country is coloured by its grid representation, read from the stage configs rather than typed in (only the part
inside its stage's build_shape_options.clip_bbox is coloured: Alaska, Hawaii and overseas territories are not modelled):
  one node        the country is a single bus: the ten rest-of-world groups (config.<G>.yaml, data/row_countries.csv
                  status `modelled`) and archetype stages with `clusters: [1]` (Singapore)
  PyPSA-Earth     multi-node stage whose grid is PyPSA-Earth's OpenStreetMap pipeline with the study-wide settings only
                  (200 kV threshold, HVDC ratings from data/hvdc/hvdc_ratings.csv)
  adjusted        multi-node stage whose config changes the topology for its countries (a `simplify_network` block:
                  isolated OSM fragments below a share of the national load joined to the backbone)
  not modelled    below the demand cut-off of scripts/select_countries.py, or skipped
Natural Earth 1:50m countries (misc-quarter1/country-classification), Equal Earth projection, Antarctica left out.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_grid_map.py [--out build/figures/grid_map.pdf]
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import shapely
import yaml

TOP = Path(__file__).resolve().parents[1]
STUDY = TOP.parent   # config-pypsa-earth
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import iconstyle as ic  # noqa: E402

COUNTRIES = STUDY / "../misc-quarter1/country-classification/data/ne_50m_admin_0_countries/ne_50m_admin_0_countries.shp"
ALIASES = {"HK": "CN", "MO": "CN"}                       # GADM CHN includes Hong Kong and Macau
NAMES = {"Somaliland": "SO", "N. Cyprus": "CY"}          # Natural Earth units without an ISO code
CLASSES = [  # key, colour, legend label
    ("one", ic.TEAL, "one node"),
    ("pypsa-earth", ic.BLUE, "PyPSA-Earth grid"),
    ("adjusted", ic.AMBER, "PyPSA-Earth grid, adjusted"),
    ("none", "white", "not modelled"),
]


def classify(row_countries, configs):
    """Grid class and clip box per ISO2 code, from data/row_countries.csv and the stage configs."""
    rc = pd.read_csv(row_countries, keep_default_na=False)
    out, boxes = {}, {}
    for _, r in rc[rc.status.isin(["modelled", "archetype"])].iterrows():
        cfg = yaml.safe_load(open(configs / f"config.{r.group}.yaml"))
        boxes[r.iso2] = cfg.get("build_shape_options", {}).get("clip_bbox")
        if r.status == "modelled" or cfg["scenario"]["clusters"] == [1]:
            out[r.iso2] = "one"
        else:
            block = cfg.get("cluster_options", cfg.get("clustering", {})) or {}
            out[r.iso2] = "adjusted" if block.get("simplify_network") else "pypsa-earth"
    return out, boxes


def world_by_class(countries, classes, boxes):
    """Natural Earth countries in Equal Earth projection with column `grid` = the class of `classes` (ISO2 -> class),
    "none" for countries not in it and for the parts of a country outside its clip box."""
    world = gpd.read_file(countries)
    world = world[world.CONTINENT != "Antarctica"]
    world["iso"] = world.ISO_A2_EH.where(world.ISO_A2_EH != "-99", world.NAME.map(NAMES)).replace(ALIASES)
    world["grid"] = world.iso.map(classes).fillna("none")
    # the part of a modelled country outside its clip box (Alaska, Hawaii, French Guiana, ...) is not modelled
    parts = []
    for _, r in world.iterrows():
        box = boxes.get(r.iso)
        if r.grid == "none" or box is None:
            parts.append(r.to_frame().T)
            continue
        inside = r.geometry.intersection(shapely.box(*box))
        outside = r.geometry.difference(shapely.box(*box))
        parts.append(gpd.GeoDataFrame([{**r, "geometry": inside}]))
        if not outside.is_empty:
            parts.append(gpd.GeoDataFrame([{**r, "geometry": outside, "grid": "none"}]))
    world = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=world.crs)
    return world.to_crs("EPSG:8857")   # Equal Earth


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--row-countries", default=STUDY / "data/row_countries.csv")
    p.add_argument("--configs", default=STUDY)
    p.add_argument("--countries", default=COUNTRIES)
    p.add_argument("--out", default=TOP / "build/figures/grid_map.pdf")
    p.add_argument("--table", default=None, help="optional csv of the classification")
    if "snakemake" in globals():
        a = p.parse_args(["--row-countries", snakemake.input.row_countries, "--configs", str(Path(snakemake.input.configs[0]).parent),
                          "--countries", snakemake.input.countries, "--out", snakemake.output.map,
                          "--table", snakemake.output.table])
    else:
        a = p.parse_args()

    grid, boxes = classify(a.row_countries, Path(a.configs))
    world = world_by_class(a.countries, grid, boxes)

    ic.use()
    fig = plt.figure(figsize=(6.3, 3.35))
    ax = fig.add_axes([0, 0.09, 1, 0.91])
    ax.set_axis_off()
    for key, colour, _ in CLASSES:
        part = world[world.grid == key]
        if len(part):
            part.plot(ax=ax, color=colour, edgecolor=ic.INK if key != "none" else ic.STEEL, linewidth=0.32 if key != "none" else 0.25)
    ax.set_aspect("equal")
    x0, y0, x1, y1 = world.total_bounds
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    counts = pd.Series(grid).value_counts()
    handles = [(c, f"{label} ({counts.get(k, 0)})" if k != "none" else label) for k, c, label in CLASSES]
    lax = fig.add_axes([0, 0, 1, 0.08])
    lax.set_axis_off()
    ic.legend_squares(lax, handles, on_title_line=False, loc="center", anchor=(0.5, 0.5))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=300)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    if a.table:
        pd.Series(grid, name="grid").rename_axis("country").sort_index().to_csv(a.table)
    print(counts.to_dict(), f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
