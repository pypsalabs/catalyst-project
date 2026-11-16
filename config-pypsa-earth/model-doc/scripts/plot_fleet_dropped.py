"""Coal and gas plants of the US: the plant list of the `now` stage, and the plants its filled retirement dates drop.

Dots: plants of resources/US-now/powerplants.csv (after the scaling to the statistic), area by capacity. Rings: plants of
build/fleet_check/dropped_US.csv, which the `now` filter drops only because their missing decommissioning year was filled
from a lifetime (written by ../scripts/check_fleet.py, read-only, no model rerun); capacity as listed, before scaling.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_fleet_dropped.py
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

TOP = Path(__file__).resolve().parents[1]
FORK = TOP.parent.parent / "models/pypsa-earth"
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

GROUPS = {"coal": ["Hard Coal", "Lignite"], "gas": ["CCGT", "OCGT"]}
CRS = "EPSG:5070"   # CONUS Albers


def points(df):
    return gpd.GeoSeries(gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326").to_crs(CRS)


def size(mw):
    return 1.2 + np.asarray(mw) / 40.0


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--plants", default=FORK / "resources/US-now/powerplants.csv")
    p.add_argument("--dropped", default=TOP / "build/fleet_check/dropped_US.csv")
    p.add_argument("--shape", default=FORK / "resources/US/shapes/country_shapes.geojson")
    p.add_argument("--out", default=TOP / "build/figures/fleet_dropped.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--plants", snakemake.input.plants, "--dropped", snakemake.input.dropped,
                          "--shape", snakemake.input.shape, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    ppl = pd.read_csv(a.plants, index_col=0)
    dropped = pd.read_csv(a.dropped)
    shape = gpd.read_file(a.shape).to_crs(CRS)

    st.use()
    fig, axes = plt.subplots(1, 2, figsize=(6.3, 2.5))
    for ax, (group, fuels) in zip(axes, GROUPS.items()):
        st.map_axes(ax)
        shape.plot(ax=ax, color=st.LAND, edgecolor="white", linewidth=0.4)
        kept = ppl[ppl.Fueltype.isin(fuels)]
        drop = dropped[dropped.group == group]
        pk, pd_ = points(kept), points(drop)
        ax.scatter(pk.x, pk.y, s=size(kept.Capacity), color=st.FUEL[group], alpha=0.55, linewidth=0, zorder=2)
        ax.scatter(pd_.x, pd_.y, s=size(drop.Capacity), facecolor="none", edgecolor=st.VERMILLION, linewidth=0.45, alpha=0.85, zorder=3)
        ax.set_title(f"{group.capitalize()}: {kept.Capacity.sum() / 1e3:,.0f} GW in the model, "
                     f"{drop.Capacity.sum() / 1e3:,.0f} GW removed", loc="left", fontsize=8)
        ax.set_aspect("equal")
        x0, y0, x1, y1 = shape.total_bounds
        ax.set_xlim(x0 - 5e4, x1 + 5e4)
        ax.set_ylim(y0 - 5e4, y1 + 5e4)
    fig.legend(handles=[plt.Line2D([], [], marker="o", ls="none", mfc=c, mec="none", alpha=0.55, ms=6) for c in [st.FUEL["coal"], st.FUEL["gas"]]]
               + [plt.Line2D([], [], marker="o", ls="none", mfc="none", mec=st.VERMILLION, mew=0.6, ms=6)],
               labels=["coal plant in the model", "gas plant in the model", "plant removed by an assumed retirement year"],
               loc="lower center", ncol=3, fontsize=6.5, handletextpad=0.3, columnspacing=1.2)
    fig.get_layout_engine().set(rect=(0, 0.08, 1, 0.92))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
