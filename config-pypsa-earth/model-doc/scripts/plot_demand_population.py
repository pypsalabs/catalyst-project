"""Electricity demand per bus region of US East, before and after the two placement corrections (Demand).

Reads build/demand_placement/USE_before_buses.csv and USE_after_buses.csv (annual demand per bus of the base network,
written by ../scripts/check_demand_placement.py on the US East run before and after `load_options: subnational_shares`
and `population_within_units`), the bus regions and the state shapes of the fork's US East run, and draws the demand
per area of each bus region in two maps.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_demand_population.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import BoundaryNorm

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

FORK = TOP.parents[1] / "models/pypsa-earth"
BOUNDS = [0, 0.1, 0.3, 1, 3, 10, 30, 100, 300]   # GWh per km2 and year
PANELS = [("before", "State weights from GDP and population,\nby area inside a state"),
          ("after", "State shares from retail sales,\nby population inside a state")]


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--data", type=Path, default=TOP / "build/demand_placement")
    p.add_argument("--regions", type=Path, default=FORK / "resources/USE/bus_regions/regions_onshore.geojson")
    p.add_argument("--states", type=Path, default=FORK / "resources/USE/shapes/gadm_shapes.geojson")
    p.add_argument("--out", default=None)
    a = p.parse_args([] if "snakemake" in globals() else None)
    if "snakemake" in globals():
        a.data, a.out = Path(snakemake.input.before).parent, str(snakemake.output[0])
        a.regions, a.states = Path(snakemake.input.regions), Path(snakemake.input.states)
    out = Path(a.out or TOP / "build/figures/demand_population.pdf")

    st.use()
    regions = gpd.read_file(a.regions)
    regions["name"] = regions["name"].astype(str)
    regions = regions.set_index("name")
    km2 = regions.to_crs(6933).area / 1e6
    states = gpd.read_file(a.states)
    proj = "ESRI:102003"   # Albers equal area, contiguous United States
    regions, states = regions.to_crs(proj), states.to_crs(proj)
    regions["geometry"] = regions.simplify(1500)
    states["geometry"] = states.simplify(1500)

    cmap = plt.get_cmap("YlOrRd", len(BOUNDS) - 1)
    norm = BoundaryNorm(BOUNDS, cmap.N)
    fig = plt.figure(figsize=(6.3, 3.5), layout="none")
    for i, (key, title) in enumerate(PANELS):
        twh = pd.read_csv(a.data / f"USE_{key}_buses.csv", dtype={"bus": str}).set_index("bus").twh
        density = (1000 * twh.reindex(regions.index).fillna(0.0) / km2).clip(upper=BOUNDS[-1] - 1e-6)
        ax = fig.add_axes([0.005 + 0.5 * i, 0.13, 0.49, 0.72])
        regions.assign(density=density).plot(ax=ax, column="density", cmap=cmap, norm=norm, linewidth=0)
        states.boundary.plot(ax=ax, color=st.TEXT, linewidth=0.3)
        ax.set_aspect("equal")
        st.map_axes(ax)
        fig.text(0.02 + 0.5 * i, 0.925, title, fontsize=7.8, fontweight="bold", color=st.TEXT, va="center", linespacing=1.25)
    cax = fig.add_axes([0.3, 0.075, 0.4, 0.022])
    st.colorbar(fig, plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax, "Electricity demand of 2024 per area of the bus region, GWh per km²",
                ticks=BOUNDS, fmt="%g")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=300)
    fig.savefig(out.with_suffix(".png"), dpi=200)
    print(f"-> {out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
